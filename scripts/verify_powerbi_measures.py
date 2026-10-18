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

A pass in B or C means the measure's LOGIC (filters, scope flags, relationships)
reproduces SQL. The DAX itself is not executed, so those measures are
LOGIC-CHECKED, not VERIFIED. Section A compares two SQL outputs directly, so it is
VERIFIED. Exit code 0 when every check matches, 1 otherwise.

Reconciliation scope: this tests the DAX layer against SQL. It does not
re-derive delay_days, latest review or category, which come from sql/00.
"""

import math
import sys
from dataclasses import dataclass
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
            """Filter flows from the one side to the many side (single direction)."""
            key, many, fk = RELATIONSHIPS[one]
            if filtered[one]:
                keep = self.t[one].loc[mask[one], key]
                mask[many] &= self.t[many][fk].isin(keep).to_numpy()
                filtered[many] = True

        for one in ("dim_state", "dim_customer", "dim_date"):
            push(one)                                    # dims -> fact_orders
        for one in ("dim_product", "dim_seller"):
            push(one)                                    # dims -> fact_order_items
        if ctx.items_filter_orders and filtered["fact_order_items"]:
            # BOTH: the filtered items filter fact_orders back to orders that contain
            # at least one visible item. An unfiltered table does not filter the
            # other side, so this only applies when something filters the items.
            keep = self.t["fact_order_items"].loc[mask["fact_order_items"], "order_id"]
            mask["fact_orders"] &= self.t["fact_orders"]["order_id"].isin(keep).to_numpy()
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

    # Total Orders = COUNTROWS ( fact_orders )
    def total_orders(self, c: Ctx) -> float:
        return float(len(self.fo(c)))

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


# ---------------------------------------------------------------- checks
RESULTS: list[dict] = []


def check(section: str, name: str, value: float, expected: float, tol: float, label: str) -> None:
    """Record one comparison. tol is the largest allowed absolute difference."""
    diff = abs(value - expected) if not (math.isnan(value) or math.isnan(expected)) else math.inf
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


def report() -> bool:
    df = pd.DataFrame(RESULTS)
    titles = {"A": "A  SQL export (recon_sql) vs Streamlit build (dashboard/data)",
              "B": "B  Core DAX measures (pandas mirror) vs recon_sql",
              "C": "C  Relationship propagation: dim_state -> fact_orders -> fact_order_items"}
    with pd.option_context("display.width", 200, "display.max_colwidth", 60, "display.float_format", "{:,.6f}".format):
        for sec, title in titles.items():
            part = df[df["section"] == sec]
            if part.empty:
                continue
            print(f"\n{title}  ({(part['status'] == 'Match').sum()}/{len(part)} match)")
            if sec == "C" and (part["status"] == "Match").all():
                print(f"  all {len(part)} state-level checks match (max diff {part['diff'].max():.6f})")
            else:
                print(part[["check", "value", "expected", "diff", "tol", "status", "label"]].to_string(index=False))
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
    ok = report()
    pitfall_demos(dax)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
