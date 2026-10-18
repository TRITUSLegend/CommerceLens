"""Independent pandas check of every DAX measure in powerbi/dax_measures.md.

Usage (from the repo root, after scripts/build_powerbi_data.py):
    python scripts/verify_powerbi_measures.py

Power BI Desktop cannot run here, so each DAX measure is re-implemented in pandas
on the same powerbi/data/*.parquet files Power BI loads. The model's filter
context and relationship propagation are applied explicitly (see Ctx and
Model.masks), then the results are compared with the SQL layer:

    A  SQL export vs Streamlit build   recon_sql vs dashboard/data/*.parquet
    B  Core measures (14)              pandas mirror of each DAX measure vs recon_sql
    C  Relationship propagation        dim_state -> fact_orders -> fact_order_items vs sql/05
    D  Report-page measures            each sliced like its visual, vs the SQL file it mirrors:
                                       D1 sql/03 Pareto, D2 sql/06 monthly + MoM, D3 sql/11
                                       delay buckets, D4 sql/14 customer state, D5 sql/21
                                       seller state, D6 sql/13 category, D7 sql/15 freight,
                                       D8 Streamlit what-if, D9 sql/09 RFM segments,
                                       D10 Model page lookups on the copied model tables,
                                       D11 sql/17 seller tiers
    E  Lane lead time (Stage 6)        pandas re-derivation of sql/22 from the star schema

A pass in B, C or D means the measure's LOGIC (filters, scope flags, relationships)
reproduces SQL. The DAX itself is not executed, so those measures are
LOGIC-CHECKED, not VERIFIED. Section A compares two SQL outputs directly, so it is
VERIFIED. Exit code 0 when every check matches, 1 otherwise.

Reconciliation scope: this tests the DAX layer against SQL. It does not
re-derive delay_days, latest review or category, which come from sql/00.
"""

import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi" / "data"
DASH = ROOT / "dashboard" / "data"

MODEL_TABLES = ["fact_orders", "fact_order_items", "dim_customer", "dim_product",
                "dim_seller", "dim_state", "dim_date"]

# The model's six relationships: one-side table -> (key, many-side table, foreign key).
# All are one-to-many with single-direction filtering (one side filters the many side).
RELATIONSHIPS = {
    "dim_state":    ("state_code",         "fact_orders",      "customer_state"),
    "dim_customer": ("customer_unique_id", "fact_orders",      "customer_unique_id"),
    "dim_date":     ("date",               "fact_orders",      "purchase_date"),
    "fact_orders":  ("order_id",           "fact_order_items", "order_id"),
    "dim_product":  ("product_id",         "fact_order_items", "product_id"),
    "dim_seller":   ("seller_id",          "fact_order_items", "seller_id"),
}


# ---------------------------------------------------------------- filter context
@dataclass(frozen=True)
class All:
    """ALL(table) or ALL(table[col], ...): removes filters inside CALCULATE."""
    table: str
    columns: tuple = ()

    def removes(self, key: tuple) -> bool:
        return key[0] == self.table and (not self.columns or key[1] in self.columns)


BOTH = "CROSSFILTER(fact_order_items[order_id], fact_orders[order_id], BOTH)"


def eq(table: str, column: str, value):
    """A DAX boolean filter table[column] = value (BLANK never equals a non-zero value)."""
    return (table, column), (lambda s: s == value)


@dataclass(frozen=True)
class Ctx:
    """A DAX filter context: column filters plus the CROSSFILTER override."""
    filters: tuple = ()
    items_filter_orders: bool = False

    def calc(self, *modifiers) -> "Ctx":
        """CALCULATE semantics: a filter on a column replaces any existing filter on
        that same column; All() removes filters; BOTH turns on bidirectional
        filtering between fact_order_items and fact_orders."""
        filters, both = dict(self.filters), self.items_filter_orders
        for mod in modifiers:
            if isinstance(mod, All):
                filters = {k: v for k, v in filters.items() if not mod.removes(k)}
            elif mod == BOTH:
                both = True
            else:
                key, pred = mod
                filters[key] = pred
        return Ctx(tuple(filters.items()), both)


DELIVERED = eq("fact_orders", "is_delivered", 1)
DELAY_SCOPE = eq("fact_orders", "in_delay_scope", 1)
REVIEW_SCOPE = eq("fact_orders", "in_review_scope", 1)
LATE, ON_TIME = eq("fact_orders", "is_late", 1), eq("fact_orders", "is_late", 0)


class Model:
    """The Power BI semantic model's tables and relationships."""

    def __init__(self, data_dir: Path):
        self.t = {name: pd.read_parquet(data_dir / f"{name}.parquet") for name in MODEL_TABLES}
        # Integer codes for each relationship key (position in the one-side table's key
        # list, -1 when absent) so propagation is an array lookup, not a string match.
        self.codes, self.n_keys = {}, {}
        for one, (key, many, fk) in RELATIONSHIPS.items():
            keys = pd.Index(self.t[one][key].unique())
            self.n_keys[one] = len(keys)
            self.codes[(one, "one")] = keys.get_indexer(self.t[one][key])
            self.codes[(one, "many")] = keys.get_indexer(self.t[many][fk])

    def _allowed(self, one: str, visible_codes: np.ndarray) -> np.ndarray:
        allowed = np.zeros(self.n_keys[one] + 1, dtype=bool)   # last slot catches -1 (orphans)
        allowed[visible_codes[visible_codes >= 0]] = True
        return allowed

    def masks(self, ctx: Ctx) -> dict:
        """Visible rows of every table under ctx, after relationship propagation."""
        mask, filtered = {}, {}
        for name, df in self.t.items():
            m = np.ones(len(df), dtype=bool)
            preds = [(col, p) for (tbl, col), p in ctx.filters if tbl == name]
            for col, pred in preds:
                m &= pred(df[col]).fillna(False).to_numpy(dtype=bool)
            mask[name], filtered[name] = m, bool(preds)

        def push(one: str) -> None:
            """Filter flows from the one side to the many side (single direction): a
            many-side row stays visible only if its key is among the visible one-side keys."""
            many = RELATIONSHIPS[one][1]
            if filtered[one]:
                allowed = self._allowed(one, self.codes[(one, "one")][mask[one]])
                mask[many] &= allowed[self.codes[(one, "many")]]
                filtered[many] = True

        for one in ("dim_state", "dim_customer", "dim_date"):
            push(one)                                    # dims -> fact_orders
        for one in ("dim_product", "dim_seller"):
            push(one)                                    # dims -> fact_order_items
        if ctx.items_filter_orders and filtered["fact_order_items"]:
            # BOTH: the filtered items filter fact_orders back to orders that contain
            # at least one visible item. An unfiltered table does not filter the
            # other side, so this only applies when something filters the items.
            allowed = self._allowed("fact_orders", self.codes[("fact_orders", "many")][mask["fact_order_items"]])
            mask["fact_orders"] &= allowed[self.codes[("fact_orders", "one")]]
            filtered["fact_orders"] = True
        push("fact_orders")                              # fact_orders -> fact_order_items
        return mask

    def rows(self, table: str, ctx: Ctx) -> pd.DataFrame:
        return self.t[table][self.masks(ctx)[table]]


def divide(a: float, b: float) -> float:
    """DIVIDE(): BLANK (nan) instead of an error when the denominator is 0 or BLANK."""
    return a / b if b and not math.isnan(b) else math.nan


# ---------------------------------------------------------------- measures
class Measures:
    """pandas mirror of powerbi/dax_measures.md. One method per DAX measure."""

    def __init__(self, model: Model):
        self.m = model

    def fo(self, c: Ctx) -> pd.DataFrame:
        return self.m.rows("fact_orders", c)

    def fi(self, c: Ctx) -> pd.DataFrame:
        return self.m.rows("fact_order_items", c)

    # Total Orders = COUNTROWS ( fact_orders )   (COUNTROWS of an empty table is BLANK)
    def total_orders(self, c: Ctx) -> float:
        n = len(self.fo(c))
        return float(n) if n else math.nan

    # Delivered Orders = CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[is_delivered] = 1 )
    def delivered_orders(self, c: Ctx) -> float:
        return self.total_orders(c.calc(DELIVERED))

    # Revenue = CALCULATE ( SUM ( fact_order_items[price] ), fact_orders[is_delivered] = 1 )
    # The filter on fact_orders reaches fact_order_items through fact_orders 1 -> * items.
    def revenue(self, c: Ctx) -> float:
        rows = self.fi(c.calc(DELIVERED))
        return float(rows["price"].sum()) if len(rows) else math.nan

    # AOV = CALCULATE ( AVERAGE ( fact_orders[items_value] ), fact_orders[is_delivered] = 1 )
    # AVERAGE skips BLANKs, like SQL AVG skips NULLs.
    def aov(self, c: Ctx) -> float:
        return float(self.fo(c.calc(DELIVERED))["items_value"].mean())

    # Customers = CALCULATE ( DISTINCTCOUNT ( fact_orders[customer_unique_id] ), is_delivered = 1 )
    def customers(self, c: Ctx) -> float:
        n = self.fo(c.calc(DELIVERED))["customer_unique_id"].nunique()
        return float(n) if n else math.nan

    # Repeat Customer % : VALUES(customer) under is_delivered = 1, then ADDCOLUMNS with
    # CALCULATE ( COUNTROWS ( fact_orders ), is_delivered = 1 ) per customer. The inner
    # CALCULATE's context transition adds customer_unique_id = <row> to the outer
    # context c, so the per-customer count is a group-by over the delivered rows of c.
    def repeat_customer_pct(self, c: Ctx) -> float:
        delivered = self.fo(c.calc(DELIVERED))
        customers = delivered["customer_unique_id"].unique()
        n_orders = delivered.groupby("customer_unique_id").size().reindex(customers)
        return divide(float((n_orders >= 2).sum()), float(len(n_orders)))

    # Avg Review = CALCULATE ( AVERAGE ( fact_orders[review_score] ), is_delivered = 1 )
    def avg_review(self, c: Ctx) -> float:
        return float(self.fo(c.calc(DELIVERED))["review_score"].mean())

    # Late % = CALCULATE ( AVERAGE ( fact_orders[is_late] ), fact_orders[in_delay_scope] = 1 )
    def late_pct(self, c: Ctx) -> float:
        return float(self.fo(c.calc(DELAY_SCOPE))["is_late"].mean())

    # Late % (reviewed) = CALCULATE ( AVERAGE ( fact_orders[is_late] ), in_review_scope = 1 )
    def late_pct_reviewed(self, c: Ctx) -> float:
        return float(self.fo(c.calc(REVIEW_SCOPE))["is_late"].mean())

    # Low Review % = CALCULATE ( AVERAGE ( fact_orders[is_low_review] ), in_review_scope = 1 )
    def low_review_pct(self, c: Ctx) -> float:
        return float(self.fo(c.calc(REVIEW_SCOPE))["is_low_review"].mean())

    # Low Review % (Late) = CALCULATE ( [Low Review %], fact_orders[is_late] = 1 )
    def low_review_pct_late(self, c: Ctx) -> float:
        return self.low_review_pct(c.calc(LATE))

    # Low Review % (On time) = CALCULATE ( [Low Review %], fact_orders[is_late] = 0 )
    def low_review_pct_on_time(self, c: Ctx) -> float:
        return self.low_review_pct(c.calc(ON_TIME))

    # ------------------------------------------------ report-page measures (Stage 3)
    # Revenue Share = DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_product ) ) )
    def revenue_share(self, c: Ctx) -> float:
        return divide(self.revenue(c), self.revenue(c.calc(All("dim_product"))))

    @lru_cache(maxsize=None)
    def _category_revenue(self, c: Ctx) -> pd.Series:
        """ADDCOLUMNS ( ALL ( dim_product[category] ), "@rev", [Revenue] ) evaluated in c.
        The measure reference is an implicit CALCULATE, so each category row becomes a
        filter (context transition) that replaces the visual's category filter."""
        base = c.calc(All("dim_product", ("category",)))
        cats = sorted(self.m.t["dim_product"]["category"].unique())
        return pd.Series({cat: self.revenue(base.calc(eq("dim_product", "category", cat))) for cat in cats})

    # Category Rank = IF ( HASONEVALUE ( category ) && NOT ISBLANK ( [Revenue] ),
    #                      RANKX ( ALL ( dim_product[category] ), [Revenue], , DESC, SKIP ) )
    def category_rank(self, c: Ctx) -> float:
        cur = self.revenue(c)
        revs = self._category_revenue(c).dropna()          # BLANK ranks last in DESC order
        return math.nan if math.isnan(cur) else float(1 + (revs > cur).sum())

    # Cumulative Revenue % : SUMX over categories whose @rev >= current revenue, divided by
    # SUMX over all. A BLANK @rev fails ">= _cur" (BLANK acts as 0) and SUMX skips it.
    def cumulative_revenue_pct(self, c: Ctx) -> float:
        cur = self.revenue(c)
        if math.isnan(cur):
            return math.nan
        revs = self._category_revenue(c).dropna()
        return divide(float(revs[revs >= cur].sum()), float(revs.sum()))

    # Cumulative % of Categories = DIVIDE ( [Category Rank],
    #     COUNTROWS ( FILTER ( ALL ( dim_product[category] ), NOT ISBLANK ( [Revenue] ) ) ) )
    def cumulative_pct_of_categories(self, c: Ctx) -> float:
        return divide(self.category_rank(c), float(self._category_revenue(c).notna().sum()))

    # Revenue MoM % : previous month = DATEADD ( dim_date[date], -1, MONTH ). dim_date is a
    # marked date table, so that filter also clears other dim_date filters (is_partial_edge).
    # Blank unless the previous month has >= 500 delivered orders (sql/06 rule).
    def revenue_mom_pct(self, month_start: pd.Timestamp) -> float:
        prev_start = month_start - pd.DateOffset(months=1)
        cur = Ctx().calc(eq("dim_date", "month_start", month_start.date()))
        prev = Ctx().calc(eq("dim_date", "month_start", prev_start.date()))
        prev_orders = self.delivered_orders(prev)
        if not prev_orders >= 500:                       # BLANK >= 500 is FALSE
            return math.nan
        return divide(self.revenue(cur), self.revenue(prev)) - 1

    # Orders (delay scope) = CALCULATE ( COUNTROWS ( fact_orders ), in_delay_scope = 1 )
    def orders_delay_scope(self, c: Ctx) -> float:
        return self.total_orders(c.calc(DELAY_SCOPE))

    # Orders (review scope) = CALCULATE ( COUNTROWS ( fact_orders ), in_review_scope = 1 )
    def orders_review_scope(self, c: Ctx) -> float:
        return self.total_orders(c.calc(REVIEW_SCOPE))

    # % of Orders (delay bucket) = DIVIDE ( [Orders (review scope)], CALCULATE (
    #     [Orders (review scope)], ALL ( delay_bucket, delay_bucket_order ) ) )
    def pct_of_orders_delay_bucket(self, c: Ctx) -> float:
        all_buckets = All("fact_orders", ("delay_bucket", "delay_bucket_order"))
        return divide(self.orders_review_scope(c), self.orders_review_scope(c.calc(all_buckets)))

    # The (seller/category) measures wrap the order-level measure in
    # CALCULATE ( ..., CROSSFILTER ( fact_order_items[order_id], fact_orders[order_id], BOTH ) )
    def orders_items_filter(self, c: Ctx) -> float:
        return self.orders_delay_scope(c.calc(BOTH))

    def reviewed_orders_items_filter(self, c: Ctx) -> float:
        return self.orders_review_scope(c.calc(BOTH))

    def late_pct_items_filter(self, c: Ctx) -> float:
        return self.late_pct(c.calc(BOTH))

    def low_review_pct_items_filter(self, c: Ctx) -> float:
        return self.low_review_pct(c.calc(BOTH))

    # Freight % of Price = DIVIDE ( CALCULATE ( SUM ( fact_order_items[freight_value] ),
    #     fact_orders[is_delivered] = 1 ), [Revenue] )
    def freight_pct_of_price(self, c: Ctx) -> float:
        return divide(float(self.fi(c.calc(DELIVERED))["freight_value"].sum()), self.revenue(c))

    # Freight Gap On Time (pp) = ( CALCULATE ( [Low Review % (On time)], freight_bucket_order = 5 )
    #     - CALCULATE ( [Low Review % (On time)], freight_bucket_order = 1 ) ) * 100
    def freight_gap_on_time_pp(self, c: Ctx) -> float:
        hi = self.low_review_pct_on_time(c.calc(eq("fact_orders", "freight_bucket_order", 5)))
        lo = self.low_review_pct_on_time(c.calc(eq("fact_orders", "freight_bucket_order", 1)))
        return (hi - lo) * 100

    # Lateness Gap (pp) = ( [Low Review % (Late)] - [Low Review % (On time)] ) * 100
    def lateness_gap_pp(self, c: Ctx) -> float:
        return (self.low_review_pct_late(c) - self.low_review_pct_on_time(c)) * 100

    # Late Orders (review scope) = CALCULATE ( [Orders (review scope)], is_late = 1 )
    def late_orders_review_scope(self, c: Ctx) -> float:
        return self.orders_review_scope(c.calc(LATE))

    # Orders Rescued (what-if) = [Late Orders (review scope)] * [Late Cut % Value]
    def orders_rescued(self, c: Ctx, cut: float) -> float:
        return self.late_orders_review_scope(c) * cut

    # Low Reviews Avoided (upper bound) = [Orders Rescued (what-if)]
    #     * ( [Low Review % (Late)] - [Low Review % (On time)] )
    def low_reviews_avoided(self, c: Ctx, cut: float) -> float:
        return self.orders_rescued(c, cut) * (self.low_review_pct_late(c) - self.low_review_pct_on_time(c))

    # Low Reviews Avoided % (upper bound) = DIVIDE ( [Low Reviews Avoided (upper bound)],
    #     CALCULATE ( [Orders (review scope)], fact_orders[is_low_review] = 1 ) )
    def low_reviews_avoided_pct(self, c: Ctx, cut: float) -> float:
        low_now = self.orders_review_scope(c.calc(eq("fact_orders", "is_low_review", 1)))
        return divide(self.low_reviews_avoided(c, cut), low_now)

    # % of Revenue (seller) = DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_seller ) ) )
    def pct_of_revenue_seller(self, c: Ctx) -> float:
        return divide(self.revenue(c), self.revenue(c.calc(All("dim_seller"))))

    # % of Customers (segment) = DIVIDE ( [Customers], CALCULATE ( [Customers], ALL ( dim_customer ) ) )
    def pct_of_customers(self, c: Ctx) -> float:
        return divide(self.customers(c), self.customers(c.calc(All("dim_customer"))))

    # % of Revenue (segment) = DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_customer ) ) )
    def pct_of_revenue_segment(self, c: Ctx) -> float:
        return divide(self.revenue(c), self.revenue(c.calc(All("dim_customer"))))


# ---------------------------------------------------------------- checks
RESULTS: list[dict] = []
NOTES: dict[str, list[str]] = {}       # extra lines printed under a section's results


def check(section: str, name: str, value: float, expected: float, tol: float, label: str) -> None:
    """Record one comparison. tol is the largest allowed absolute difference.
    Two BLANKs (nan) match, e.g. MoM growth after a sparse month (SQL NULL vs DAX BLANK)."""
    value, expected = float(value), float(expected)
    if math.isnan(value) and math.isnan(expected):
        diff = 0.0
    elif math.isnan(value) or math.isnan(expected):
        diff = math.inf
    else:
        diff = abs(value - expected)
    RESULTS.append({"section": section, "check": name, "value": value, "expected": expected,
                    "diff": diff, "tol": tol, "status": "Match" if diff <= tol + 1e-9 else "MISMATCH",
                    "label": label})


def section_a_sql_vs_dashboard(recon: pd.DataFrame) -> None:
    """recon_sql (this export) vs the Streamlit build's parquet files. Both are SQL output."""
    k = pd.read_parquet(DASH / "kpis.parquet").iloc[0]
    lv = pd.read_parquet(DASH / "late_vs_ontime.parquet").set_index("delivery")
    so = pd.read_parquet(DASH / "state_ops.parquet").set_index("customer_state")
    rfm = pd.read_parquet(DASH / "rfm_segments.parquet").set_index("segment")
    dashboard = {
        "Total orders (all statuses)":      ("kpis", k["total_orders_all_statuses"]),
        "Delivered orders":                 ("kpis", k["delivered_orders"]),
        "Revenue (R$)":                     ("kpis", k["revenue"]),
        "Average order value (R$)":         ("kpis", k["avg_order_value"]),
        "Customers (1+ delivered order)":   ("kpis", k["customers"]),
        "Repeat customers (%)":             ("kpis", k["repeat_customer_pct"]),
        "Average review score":             ("kpis", k["avg_review_score"]),
        "Late (%) - all delivered orders":  ("kpis", k["late_delivery_pct"]),
        "Late (%) - reviewed orders only":  ("late_vs_ontime", lv.loc["Late", "pct_of_orders"]),
        "Low-review (%) - late orders":     ("late_vs_ontime", lv.loc["Late", "pct_low_review"]),
        "Low-review (%) - on-time orders":  ("late_vs_ontime", lv.loc["On time or early", "pct_low_review"]),
        "Late (%) - RJ":                    ("state_ops", so.loc["RJ", "late_pct"]),
        "Late (%) - SP":                    ("state_ops", so.loc["SP", "late_pct"]),
        "Champions - share of revenue (%)": ("rfm_segments", rfm.loc["Champions", "pct_of_revenue"]),
    }
    sql = recon.set_index("metric")["sql_value"]
    for metric, (source, value) in dashboard.items():
        check("A", f"{metric}  [{source}]", float(sql[metric]), float(value), 0.0, "VERIFIED")


def section_b_core_measures(dax: Measures, recon: pd.DataFrame) -> None:
    """Each core measure in the empty filter context of the Reconciliation page."""
    c = Ctx()
    mirrors = {
        "Total orders (all statuses)":      lambda: dax.total_orders(c),
        "Delivered orders":                 lambda: dax.delivered_orders(c),
        "Revenue (R$)":                     lambda: dax.revenue(c),
        "Average order value (R$)":         lambda: dax.aov(c),
        "Customers (1+ delivered order)":   lambda: dax.customers(c),
        "Repeat customers (%)":             lambda: dax.repeat_customer_pct(c) * 100,
        "Average review score":             lambda: dax.avg_review(c),
        "Late (%) - all delivered orders":  lambda: dax.late_pct(c) * 100,
        "Late (%) - reviewed orders only":  lambda: dax.late_pct_reviewed(c) * 100,
        "Low-review (%) - late orders":     lambda: dax.low_review_pct_late(c) * 100,
        "Low-review (%) - on-time orders":  lambda: dax.low_review_pct_on_time(c) * 100,
        # CALCULATE ( [Late %], dim_state[state_code] = "RJ" ): dim_state -> fact_orders
        "Late (%) - RJ":                    lambda: dax.late_pct(c.calc(eq("dim_state", "state_code", "RJ"))) * 100,
        "Late (%) - SP":                    lambda: dax.late_pct(c.calc(eq("dim_state", "state_code", "SP"))) * 100,
        # DIVIDE ( CALCULATE ( [Revenue], dim_customer[segment] = "Champions" ),
        #          CALCULATE ( [Revenue], ALL ( dim_customer ) ) ): dim_customer -> fact_orders -> items
        "Champions - share of revenue (%)": lambda: divide(
            dax.revenue(c.calc(eq("dim_customer", "segment", "Champions"))),
            dax.revenue(c.calc(All("dim_customer")))) * 100,
    }
    assert list(mirrors) == recon["metric"].tolist(), "recon_sql metrics changed; update section B"
    for row in recon.itertuples():
        check("B", row.metric, mirrors[row.metric](), row.sql_value, row.tolerance, "LOGIC-CHECKED")


def section_c_propagation(dax: Measures) -> None:
    """Measures sliced by dim_state, vs sql/05 (delivered orders by customer state).
    Revenue exercises the two-hop path dim_state -> fact_orders -> fact_order_items."""
    by_state = pd.read_parquet(DASH / "revenue_by_state.parquet")
    for row in by_state.itertuples():
        c = Ctx().calc(eq("dim_state", "state_code", row.customer_state))
        st = row.customer_state
        check("C", f"Revenue, {st}  [sql/05]", dax.revenue(c), row.revenue, 0.005 + 1e-6, "LOGIC-CHECKED")
        check("C", f"Delivered Orders, {st}  [sql/05]", dax.delivered_orders(c), row.orders, 0, "LOGIC-CHECKED")
        check("C", f"Customers, {st}  [sql/05]", dax.customers(c), row.customers, 0, "LOGIC-CHECKED")


HALF_2DP = 0.005 + 1e-6    # SQL values rounded to 2 dp can differ from the exact value by 0.005
HALF_3DP = 0.0005 + 1e-6


def section_d_report_pages(dax: Measures) -> None:
    """Stage 3 measures, each sliced the way its report visual slices it, vs the SQL
    file it mirrors (dashboard/data parquet, or recon_seller_state for sql/21)."""
    L = "LOGIC-CHECKED"

    # D1 Pareto by category (sql/03 -> pareto_category). Visual: axis dim_product[category].
    for r in pd.read_parquet(DASH / "pareto_category.parquet").itertuples():
        c = Ctx().calc(eq("dim_product", "category", r.category))
        check("D1", f"{r.category}: Revenue", dax.revenue(c), r.revenue, HALF_2DP, L)
        check("D1", f"{r.category}: Revenue Share", 100 * dax.revenue_share(c), r.pct_of_revenue, HALF_2DP, L)
        check("D1", f"{r.category}: Category Rank", dax.category_rank(c), r.rank, 0, L)
        check("D1", f"{r.category}: Cumulative Revenue %", 100 * dax.cumulative_revenue_pct(c), r.cumulative_pct, HALF_2DP, L)
        check("D1", f"{r.category}: Cumulative % of Categories", 100 * dax.cumulative_pct_of_categories(c),
              r.cumulative_pct_of_categories, HALF_2DP, L)

    # D2 Monthly revenue and MoM growth (sql/06 -> monthly_trend). Axis dim_date[month_start].
    for r in pd.read_parquet(DASH / "monthly_trend.parquet").itertuples():
        m = pd.Timestamp(r.month)
        c = Ctx().calc(eq("dim_date", "month_start", m.date()))
        label = f"{m:%Y-%m}"
        check("D2", f"{label}: Delivered Orders", dax.delivered_orders(c), r.orders, 0, L)
        check("D2", f"{label}: Revenue", dax.revenue(c), r.revenue, HALF_2DP, L)
        check("D2", f"{label}: AOV", dax.aov(c), r.avg_order_value, HALF_2DP, L)
        check("D2", f"{label}: Revenue MoM %", 100 * dax.revenue_mom_pct(m), r.revenue_mom_pct, HALF_2DP, L)

    # D3 Delay buckets (sql/11 -> delay_vs_review). Axis fact_orders[delay_bucket], which is
    # sorted by delay_bucket_order, so Power BI filters both columns for each bar.
    for r in pd.read_parquet(DASH / "delay_vs_review.parquet").itertuples():
        c = Ctx().calc(eq("fact_orders", "delay_bucket", r.delay_bucket),
                       eq("fact_orders", "delay_bucket_order", r.bucket_order))
        b = r.delay_bucket
        check("D3", f"{b}: Orders (review scope)", dax.orders_review_scope(c), r.orders, 0, L)
        check("D3", f"{b}: % of Orders (delay bucket)", 100 * dax.pct_of_orders_delay_bucket(c), r.pct_of_orders, HALF_2DP, L)
        check("D3", f"{b}: Low Review %", 100 * dax.low_review_pct(c), r.pct_low_review, HALF_2DP, L)
        check("D3", f"{b}: Avg Review", dax.avg_review(c), r.avg_review, HALF_3DP, L)
        check("D3", f"{b}: Late % (0 or 100 by construction)", 100 * dax.late_pct(c),
              100.0 if r.bucket_order >= 5 else 0.0, 1e-9, L)

    # D4 Customer state (sql/14 -> state_ops). Axis dim_state[state_code].
    for r in pd.read_parquet(DASH / "state_ops.parquet").itertuples():
        c = Ctx().calc(eq("dim_state", "state_code", r.customer_state))
        s = r.customer_state
        check("D4", f"{s}: Orders (delay scope)", dax.orders_delay_scope(c), r.orders, 0, L)
        check("D4", f"{s}: Late %", 100 * dax.late_pct(c), r.late_pct, HALF_2DP, L)
        check("D4", f"{s}: Low Review %", 100 * dax.low_review_pct(c), r.pct_low_review, HALF_2DP, L)

    # D5 Seller state (sql/21 -> recon_seller_state). Axis dim_seller[seller_state]: the filter
    # reaches fact_orders only through CROSSFILTER(..., BOTH) inside the measure.
    for r in pd.read_parquet(PBI / "recon_seller_state.parquet").itertuples():
        c = Ctx().calc(eq("dim_seller", "seller_state", r.seller_state))
        s = r.seller_state
        check("D5", f"{s}: Orders (seller/category)", dax.orders_items_filter(c), r.orders, 0, L)
        check("D5", f"{s}: Reviewed Orders (seller/category)", dax.reviewed_orders_items_filter(c), r.reviewed_orders, 0, L)
        check("D5", f"{s}: Late % (seller/category)", 100 * dax.late_pct_items_filter(c), r.late_pct, HALF_2DP, L)
        check("D5", f"{s}: Low Review % (seller/category)", 100 * dax.low_review_pct_items_filter(c),
              r.pct_low_review, HALF_2DP, L)

    # D6 Category scorecard (sql/13 -> category_ops), the same CROSSFILTER pattern by category.
    # Only columns whose scope matches the measures exactly: late % (delivered with a delivery
    # date) and freight % of price (item level). sql/13's low-review % also counts the 8
    # delivered orders without a delivery date, so it is not compared.
    for r in pd.read_parquet(DASH / "category_ops.parquet").itertuples():
        c = Ctx().calc(eq("dim_product", "category", r.category))
        check("D6", f"{r.category}: Late % (seller/category)", 100 * dax.late_pct_items_filter(c), r.late_pct, HALF_2DP, L)
        check("D6", f"{r.category}: Freight % of Price", 100 * dax.freight_pct_of_price(c),
              r.freight_pct_of_price, HALF_2DP, L)

    # D7 Freight share of price and the on-time-only test (sql/15 -> freight_vs_review).
    # Axis fact_orders[freight_share_bucket], sorted by freight_bucket_order.
    fr = pd.read_parquet(DASH / "freight_vs_review.parquet")
    for r in fr.itertuples():
        c = Ctx().calc(eq("fact_orders", "freight_share_bucket", r.freight_share_of_price),
                       eq("fact_orders", "freight_bucket_order", r.bucket_order))
        b = r.freight_share_of_price
        check("D7", f"{b}: Orders (review scope)", dax.orders_review_scope(c), r.orders, 0, L)
        check("D7", f"{b}: Low Review %", 100 * dax.low_review_pct(c), r.pct_low_review, HALF_2DP, L)
        check("D7", f"{b}: Late % (reviewed)", 100 * dax.late_pct_reviewed(c), r.late_pct, HALF_2DP, L)
        check("D7", f"{b}: Low Review % (On time)", 100 * dax.low_review_pct_on_time(c),
              r.pct_low_review_on_time, HALF_2DP, L)
    fr = fr.set_index("bucket_order")
    lv = pd.read_parquet(DASH / "late_vs_ontime.parquet").set_index("delivery")
    # Differences of two 2-dp values: each side can be off by 0.005.
    check("D7", "Freight Gap On Time (pp)  [sql/15: 50%+ minus <10%]", dax.freight_gap_on_time_pp(Ctx()),
          fr.loc[5, "pct_low_review_on_time"] - fr.loc[1, "pct_low_review_on_time"], 2 * HALF_2DP, L)
    check("D7", "Lateness Gap (pp)  [sql/12: late minus on time]", dax.lateness_gap_pp(Ctx()),
          lv.loc["Late", "pct_low_review"] - lv.loc["On time or early", "pct_low_review"], 2 * HALF_2DP, L)

    # D8 What-if: cut late deliveries (Streamlit simulator, dashboard/app.py). Rates come
    # from the Low Review % (Late) / (On time) measures, never typed. 3,190 and 1,696 are
    # the expected values at 50% supplied for this check; the simulator's own formula is
    # also recomputed from late_vs_ontime.parquet (it uses rates rounded to 2 dp).
    late, ontime = lv.loc["Late"], lv.loc["On time or early"]
    check("D8", "Late Orders (review scope)  [sql/12]", dax.late_orders_review_scope(Ctx()), late["orders"], 0, L)
    for cut in (0.5, 1.0):
        moved = late["orders"] * cut
        low_now = (late["orders"] * late["pct_low_review"] + ontime["orders"] * ontime["pct_low_review"]) / 100
        avoided = moved * (late["pct_low_review"] - ontime["pct_low_review"]) / 100
        pct = f"{cut:.0%}"
        rescued_dax, avoided_dax = dax.orders_rescued(Ctx(), cut), dax.low_reviews_avoided(Ctx(), cut)
        check("D8", f"cut {pct}: Orders Rescued vs simulator formula", rescued_dax, moved, 1e-9, L)
        check("D8", f"cut {pct}: Low Reviews Avoided vs simulator formula", avoided_dax, avoided, 1.0, L)
        check("D8", f"cut {pct}: Low Reviews Avoided % vs simulator formula",
              100 * dax.low_reviews_avoided_pct(Ctx(), cut), 100 * avoided / low_now, 0.05, L)
        if cut == 0.5:
            check("D8", "cut 50%: Orders Rescued vs expected 3,190 (+/-1)", rescued_dax, 3190, 1.0, L)
            check("D8", "cut 50%: Low Reviews Avoided vs expected 1,696 (+/-1)", avoided_dax, 1696, 1.0, L)
        NOTES.setdefault("D8", []).append(
            f"cut {pct}: Power BI '#,0' would show {round_half_up(rescued_dax):,} rescued / "
            f"{round_half_up(avoided_dax):,} fewer low reviews; Streamlit shows {moved:,.0f} / {avoided:,.0f} "
            f"(exact DAX logic: {rescued_dax:,.2f} / {avoided_dax:,.2f})")

    # D11 Seller tiers (sql/17 -> seller_tiers). Axis dim_seller[seller_tier]. Revenue reaches
    # the items directly; late % needs the CROSSFILTER measure. sql/17's low-review % and
    # order count include delivered orders without a delivery date, so they are not compared.
    for r in pd.read_parquet(DASH / "seller_tiers.parquet").itertuples():
        c = Ctx().calc(eq("dim_seller", "seller_tier", r.seller_tier))
        t = r.seller_tier
        check("D11", f"{t}: Revenue", dax.revenue(c), r.revenue, HALF_2DP, L)
        check("D11", f"{t}: % of Revenue (seller)", 100 * dax.pct_of_revenue_seller(c), r.pct_of_revenue, HALF_2DP, L)
        check("D11", f"{t}: Late % (seller/category)", 100 * dax.late_pct_items_filter(c), r.late_pct, HALF_2DP, L)

    # D9 RFM segments (sql/09 -> rfm_segments). Axis dim_customer[segment].
    for r in pd.read_parquet(DASH / "rfm_segments.parquet").itertuples():
        c = Ctx().calc(eq("dim_customer", "segment", r.segment))
        s = r.segment
        check("D9", f"{s}: Customers", dax.customers(c), r.customers, 0, L)
        check("D9", f"{s}: % of Customers (segment)", 100 * dax.pct_of_customers(c), r.pct_of_customers, HALF_2DP, L)
        check("D9", f"{s}: Revenue", dax.revenue(c), r.revenue, HALF_2DP, L)
        check("D9", f"{s}: % of Revenue (segment)", 100 * dax.pct_of_revenue_segment(c), r.pct_of_revenue, HALF_2DP, L)


def section_d10_model_page() -> None:
    """Model page lookups on the copied tables. Recall/Precision/Lift at Flag % read
    model_capture_curve with ROUND ( top_frac * 100, 0 ) = Flag %; compared with the
    separate model_capture.parquet written by the same capture_at_top() call."""
    curve = pd.read_parquet(PBI / "model_capture_curve.parquet")
    for r in pd.read_parquet(DASH / "model_capture.parquet").itertuples():
        flag = int(round(r.top_frac * 100))
        row = curve[np.round(curve["top_frac"] * 100) == flag]
        for col, measure in [("recall_at_top", "Recall"), ("precision_at_top", "Precision"),
                             ("lift_vs_random", "Lift")]:
            check("D10", f"Flag {flag}%: {measure} at Flag %", row[col].max(), getattr(r, col), 1e-12, "LOGIC-CHECKED")
    m = pd.read_parquet(PBI / "model_metrics.parquet")
    lgbm = m[m["model"] == "LightGBM"]
    test = lgbm[lgbm["evaluation"] == "Stratified random split"]
    oot = lgbm[lgbm["evaluation"].str[:11] == "Out-of-time"]
    check("D10", "rows matched by the out-of-time filter", len(oot), 1, 0, "LOGIC-CHECKED")
    check("D10", "rows matched by the stratified-test filter", len(test), 1, 0, "LOGIC-CHECKED")


def section_e_lane_lead_time(model: Model) -> None:
    """Stage 6: re-derive lane_lead_time (sql/22) in pandas from the star schema, without
    reusing any SQL logic: lane from fact_order_items + dim_seller, percentiles as the
    smallest d with share(delivery_days <= d) >= q. Both are run here, so VERIFIED."""
    fo = model.t["fact_orders"]
    items = model.t["fact_order_items"].merge(model.t["dim_seller"][["seller_id", "seller_state"]], on="seller_id")
    states = items.groupby("order_id")["seller_state"].agg(["nunique", "first"])
    lane_of = states.loc[states["nunique"] == 1, "first"]
    o = fo[fo["in_delay_scope"] == 1].copy()
    o["seller_state"] = o["order_id"].map(lane_of)
    o = o.dropna(subset=["seller_state"])
    o["promised_days"] = (pd.to_datetime(o["estimated_delivery_date"]) - pd.to_datetime(o["purchase_date"])).dt.days

    def shortest_promise(days: pd.Series, q: float) -> float:
        s = np.sort(days.to_numpy())
        share = np.searchsorted(s, s, side="right") / len(s)      # share(delivery_days <= d)
        return float(s[share >= q].min())

    sql = pd.read_parquet(PBI / "lane_lead_time.parquet").set_index(["seller_state", "customer_state"])
    lanes = o.groupby(["seller_state", "customer_state"])
    sizes = lanes.size()
    check("E", "lanes with 30+ orders", int((sizes >= 30).sum()), len(sql), 0, "VERIFIED")
    for key, g in lanes:
        if len(g) < 30:
            continue
        lane = f"{key[0]} -> {key[1]}"
        r = sql.loc[key]
        p90, p95 = shortest_promise(g["delivery_days"], 0.90), shortest_promise(g["delivery_days"], 0.95)
        values = {
            "orders": (len(g), r["orders"], 0),
            "p50_delivery_days": (shortest_promise(g["delivery_days"], 0.50), r["p50_delivery_days"], 0),
            "p90_delivery_days": (p90, r["p90_delivery_days"], 0),
            "p95_delivery_days": (p95, r["p95_delivery_days"], 0),
            "avg_promised_days": (g["promised_days"].mean(), r["avg_promised_days"], 0.05 + 1e-6),
            "on_time_pct_today": (100 * (g["delay_days"] <= 0).mean(), r["on_time_pct_today"], HALF_2DP),
            "on_time_pct_at_p95": (100 * (g["delivery_days"] <= p95).mean(), r["on_time_pct_at_p95"], HALF_2DP),
            "gap_p95_vs_avg_promise_days": (p95 - g["promised_days"].mean(), r["gap_p95_vs_avg_promise_days"], 0.05 + 1e-6),
        }
        for col, (value, expected, tol) in values.items():
            check("E", f"{lane}: {col}", value, expected, tol, "VERIFIED")


def round_half_up(x: float) -> int:
    """Power BI's '#,0' format rounds halves away from zero; Python's format rounds to even."""
    return int(math.floor(x + 0.5))


def pitfall_demos(dax: Measures) -> None:
    """What the measures would return if written the naive way (informational)."""
    fo = dax.m.t["fact_orders"]
    delivered = fo[fo["is_delivered"] == 1]
    print("\nDAX pitfall demonstrations (what a naive measure would return; not checks)")
    # 1. BLANK = 0 is TRUE in DAX. A filter is_low_review = 0 keeps unreviewed orders.
    naive = int(((delivered["is_low_review"] == 0) | delivered["is_low_review"].isna()).sum())
    right = int((delivered["is_low_review"] == 0).sum())
    print(f"  BLANK = 0       CALCULATE(COUNTROWS(fact_orders), is_delivered = 1, is_low_review = 0) "
          f"counts {naive:,} orders; {naive - right:,} of them have no review (correct: {right:,})")
    naive = int(((delivered["delay_days"] <= 0) | delivered["delay_days"].isna()).sum())
    right = int((delivered["delay_days"] <= 0).sum())
    print(f"  BLANK <= 0      a filter delay_days <= 0 counts {naive:,} delivered orders as on time; "
          f"{naive - right:,} have no delivery date (correct: {right:,})")
    # 2. Context transition. Without CALCULATE inside ADDCOLUMNS, COUNTROWS ignores the
    #    current customer and returns the whole table for every row.
    n_all = len(fo)
    print(f"  No transition   ADDCOLUMNS(..., \"@orders\", COUNTROWS(fact_orders)) gives every customer "
          f"{n_all:,} orders -> Repeat Customer % = 100%")
    per_cust_all = fo[fo["customer_unique_id"].isin(delivered["customer_unique_id"])] \
        .groupby("customer_unique_id").size()
    print(f"  Lost filter     CALCULATE(COUNTROWS(fact_orders)) without is_delivered = 1 inside ADDCOLUMNS "
          f"-> {100 * (per_cust_all >= 2).mean():.4f}% (correct: {100 * dax.repeat_customer_pct(Ctx()):.4f}%)")
    # 3. Filter direction. dim_product filters fact_order_items only; order-level
    #    measures ignore it unless CROSSFILTER(..., BOTH) is applied.
    cat = eq("dim_product", "category", "office_furniture")
    print(f"  Direction       [Late %] for category office_furniture = {100 * dax.late_pct(Ctx().calc(cat)):.2f}% "
          f"(= national) vs {100 * dax.late_pct(Ctx().calc(cat, BOTH)):.2f}% with CROSSFILTER BOTH")
    # 4. Sort-by-column. delay_bucket is sorted by delay_bucket_order, so each bar filters
    #    both columns; ALL ( delay_bucket ) alone leaves the sort column filtered.
    bar = Ctx().calc(eq("fact_orders", "delay_bucket", "1-3 days late"), eq("fact_orders", "delay_bucket_order", 5))
    naive = divide(dax.orders_review_scope(bar),
                   dax.orders_review_scope(bar.calc(All("fact_orders", ("delay_bucket",)))))
    print(f"  Sort-by column  % of Orders for '1-3 days late' with ALL(delay_bucket) only = {100 * naive:.2f}% "
          f"vs {100 * dax.pct_of_orders_delay_bucket(bar):.2f}% with ALL(delay_bucket, delay_bucket_order)")


SECTION_TITLES = {
    "A":  "A  SQL export (recon_sql) vs Streamlit build (dashboard/data)",
    "B":  "B  Core DAX measures (pandas mirror) vs recon_sql",
    "C":  "C  Relationship propagation: dim_state -> fact_orders -> fact_order_items  [sql/05]",
    "D1": "D1 Revenue share and Pareto by category  [sql/03 -> pareto_category]",
    "D2": "D2 Monthly revenue and MoM growth  [sql/06 -> monthly_trend]",
    "D3": "D3 Delay buckets  [sql/11 -> delay_vs_review]",
    "D4": "D4 Customer state  [sql/14 -> state_ops]",
    "D5": "D5 Seller state via CROSSFILTER  [sql/21 -> recon_seller_state]",
    "D6": "D6 Category via CROSSFILTER, freight % of price  [sql/13 -> category_ops]",
    "D7": "D7 Freight share of price, on-time-only test  [sql/15 -> freight_vs_review]",
    "D8": "D8 What-if: cut late deliveries  [dashboard/app.py simulator, sql/12]",
    "D9": "D9 RFM segments  [sql/09 -> rfm_segments]",
    "D10": "D10 Model page lookups  [copied model_* tables vs dashboard/data/model_capture]",
    "D11": "D11 Seller tiers  [sql/17 -> seller_tiers]",
    "E":  "E  Stage 6 lane lead time: pandas re-derivation vs sql/22 (lane_lead_time)",
}
SHOW_ALL_ROWS = {"A", "B", "D8"}       # other sections print a one-line summary when all match


def report() -> bool:
    df = pd.DataFrame(RESULTS)
    with pd.option_context("display.width", 220, "display.max_colwidth", 70, "display.float_format", "{:,.6f}".format):
        for sec, title in SECTION_TITLES.items():
            part = df[df["section"] == sec]
            if part.empty:
                continue
            n_ok = int((part["status"] == "Match").sum())
            print(f"\n{title}  ({n_ok}/{len(part)} match)")
            if sec in SHOW_ALL_ROWS or n_ok < len(part):
                rows = part if sec in SHOW_ALL_ROWS else part[part["status"] != "Match"]
                print(rows[["check", "value", "expected", "diff", "tol", "status", "label"]].to_string(index=False))
            else:
                print(f"  all {len(part)} checks match; largest difference {part['diff'].max():.6f} "
                      f"(label: {part['label'].iloc[0]})")
            for note in NOTES.get(sec, []):
                print(f"  {note}")
    bad = df[df["status"] != "Match"]
    print(f"\n{len(df) - len(bad)}/{len(df)} checks match.")
    if len(bad):
        print(bad[["section", "check", "value", "expected", "diff"]].to_string(index=False))
    return bad.empty


def main() -> int:
    if not (PBI / "recon_sql.parquet").exists():
        print("powerbi/data/ is missing. Run: python scripts/build_powerbi_data.py")
        return 1
    recon = pd.read_parquet(PBI / "recon_sql.parquet").sort_values("sort_order")
    dax = Measures(Model(PBI))
    section_a_sql_vs_dashboard(recon)
    section_b_core_measures(dax, recon)
    section_c_propagation(dax)
    section_d_report_pages(dax)
    section_d10_model_page()
    section_e_lane_lead_time(dax.m)
    ok = report()
    pitfall_demos(dax)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
