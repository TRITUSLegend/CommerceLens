"""Build the star-schema tables that the Power BI report loads.

Usage (from the repo root, venv active, the 9 Olist CSVs in place):
    python scripts/build_powerbi_data.py

Every table is derived from the same DuckDB views the notebooks and the Streamlit
build use (sql/00_base_views.sql, sql/08_rfm_customers.sql), so Power BI inherits
the project's definitions (revenue, customer, late, latest review) instead of
re-implementing them. Output: powerbi/data/*.parquet

Tables
    fact_orders       one row per order (all statuses)
    fact_order_items  one row per order item
    dim_customer      one row per real person (customer_unique_id) + RFM segment
    dim_product       one row per product (English category)
    dim_seller        one row per seller
    dim_state         one row per Brazilian state (name + macro-region)
    dim_date          one row per calendar day
    recon_sql         headline numbers computed by the SQL layer, for the
                      Power BI reconciliation page (DAX vs SQL)
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src import db  # noqa: E402

OUT_DIR = ROOT / "powerbi" / "data"

# Brazilian states: code -> (name, macro-region). Static reference data.
STATES = {
    "AC": ("Acre", "North"), "AL": ("Alagoas", "Northeast"), "AP": ("Amapa", "North"),
    "AM": ("Amazonas", "North"), "BA": ("Bahia", "Northeast"), "CE": ("Ceara", "Northeast"),
    "DF": ("Distrito Federal", "Central-West"), "ES": ("Espirito Santo", "Southeast"),
    "GO": ("Goias", "Central-West"), "MA": ("Maranhao", "Northeast"),
    "MT": ("Mato Grosso", "Central-West"), "MS": ("Mato Grosso do Sul", "Central-West"),
    "MG": ("Minas Gerais", "Southeast"), "PA": ("Para", "North"), "PB": ("Paraiba", "Northeast"),
    "PR": ("Parana", "South"), "PE": ("Pernambuco", "Northeast"), "PI": ("Piaui", "Northeast"),
    "RJ": ("Rio de Janeiro", "Southeast"), "RN": ("Rio Grande do Norte", "Northeast"),
    "RS": ("Rio Grande do Sul", "South"), "RO": ("Rondonia", "North"), "RR": ("Roraima", "North"),
    "SC": ("Santa Catarina", "South"), "SP": ("Sao Paulo", "Southeast"),
    "SE": ("Sergipe", "Northeast"), "TO": ("Tocantins", "North"),
}

# One row per order. Flags are precomputed (0/1) so DAX never has to compare
# against BLANK(). Scope flags mirror the WHERE clauses of the SQL files:
#   in_delay_scope  = delivered AND has a delay_days   (sql/10 late %, sql/14)
#   in_review_scope = in_delay_scope AND has a review  (sql/11, sql/12)
# The delay bucket CASE is copied from sql/11_delay_vs_review.sql.
FACT_ORDERS_SQL = """
SELECT
    order_id,
    customer_unique_id,
    customer_state,
    order_status,
    CAST(order_purchase_timestamp AS DATE)       AS purchase_date,
    CAST(order_estimated_delivery_date AS DATE)  AS estimated_delivery_date,
    CAST(order_delivered_customer_date AS DATE)  AS delivered_date,
    items_value,
    freight_value,
    n_items,
    n_sellers,
    review_score,
    delay_days,
    delivery_days,
    CAST(order_status = 'delivered' AS INTEGER)                                    AS is_delivered,
    CASE WHEN order_status = 'delivered' AND delay_days IS NOT NULL THEN 1 ELSE 0 END AS in_delay_scope,
    CASE WHEN order_status = 'delivered' AND delay_days IS NOT NULL
              AND review_score IS NOT NULL THEN 1 ELSE 0 END                       AS in_review_scope,
    CASE WHEN delay_days IS NULL THEN 0 ELSE CAST(delay_days > 0 AS INTEGER) END   AS is_late,
    CASE WHEN review_score IS NULL THEN NULL
         ELSE CAST(review_score <= 2 AS INTEGER) END                               AS is_low_review,
    CASE
        WHEN delay_days IS NULL  THEN NULL
        WHEN delay_days <= -15 THEN '15+ days early'
        WHEN delay_days <= -8  THEN '8-14 days early'
        WHEN delay_days <= -1  THEN '1-7 days early'
        WHEN delay_days = 0    THEN 'On estimated day'
        WHEN delay_days <= 3   THEN '1-3 days late'
        WHEN delay_days <= 7   THEN '4-7 days late'
        WHEN delay_days <= 14  THEN '8-14 days late'
        ELSE                        '15+ days late'
    END AS delay_bucket,
    CASE
        WHEN delay_days IS NULL  THEN NULL
        WHEN delay_days <= -15 THEN 1
        WHEN delay_days <= -8  THEN 2
        WHEN delay_days <= -1  THEN 3
        WHEN delay_days = 0    THEN 4
        WHEN delay_days <= 3   THEN 5
        WHEN delay_days <= 7   THEN 6
        WHEN delay_days <= 14  THEN 7
        ELSE                        8
    END AS delay_bucket_order
FROM orders_enriched
ORDER BY order_id
"""

FACT_ORDER_ITEMS_SQL = """
SELECT order_id, order_item_id, product_id, seller_id, price, freight_value
FROM order_items
ORDER BY order_id, order_item_id
"""

# Same category rule as order_items_enriched in sql/00 (English, else Portuguese, else 'unknown').
DIM_PRODUCT_SQL = """
SELECT
    p.product_id,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
    p.product_weight_g
FROM products p
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
ORDER BY p.product_id
"""

DIM_SELLER_SQL = """
SELECT seller_id, seller_state, seller_city
FROM sellers
ORDER BY seller_id
"""

# Every real person, scored or not. Segment logic lives in sql/08_rfm_customers.sql.
DIM_CUSTOMER_SQL = """
SELECT
    c.customer_unique_id,
    COALESCE(r.segment, 'No delivered order') AS segment,
    CASE COALESCE(r.segment, 'No delivered order')
        WHEN 'Champions'            THEN 1
        WHEN 'Potential loyalists'  THEN 2
        WHEN 'Needs attention'      THEN 3
        WHEN 'Recent, low spend'    THEN 4
        WHEN 'At risk, high value'  THEN 5
        WHEN 'Hibernating'          THEN 6
        ELSE 7
    END AS segment_order,
    r.r_score,
    r.m_score,
    r.recency_days,
    CASE WHEN r.customer_unique_id IS NULL THEN NULL
         ELSE CAST(r.is_repeat_buyer AS INTEGER) END AS is_repeat_buyer
FROM (SELECT DISTINCT customer_unique_id FROM customers) c
LEFT JOIN rfm_customers r ON r.customer_unique_id = c.customer_unique_id
ORDER BY c.customer_unique_id
"""


def save(table, name: str) -> pd.DataFrame:
    """Write one parquet file (DuckDB relation or DataFrame) and return it as a DataFrame."""
    if isinstance(table, pd.DataFrame):
        arrow = pa.Table.from_pandas(table, preserve_index=False)
    else:
        arrow = table.arrow()
        if isinstance(arrow, pa.RecordBatchReader):
            arrow = arrow.read_all()
    path = OUT_DIR / f"{name}.parquet"
    pq.write_table(arrow, path, compression="snappy")
    print(f"  {path.name:<26} {arrow.num_rows:>8,} rows  {path.stat().st_size / 1024:8.1f} KB")
    return arrow.to_pandas()


def build_dim_state() -> pd.DataFrame:
    rows = [(code, name, region) for code, (name, region) in STATES.items()]
    return pd.DataFrame(rows, columns=["state_code", "state_name", "region"]).sort_values("state_code")


def build_dim_date(purchase_dates: pd.Series, monthly: pd.DataFrame) -> pd.DataFrame:
    """Full calendar covering whole months from the first to the last purchase."""
    start = purchase_dates.min().to_period("M").start_time
    end = purchase_dates.max().to_period("M").end_time.normalize()
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    d["year"] = d["date"].dt.year
    d["quarter"] = "Q" + d["date"].dt.quarter.astype(str)
    d["month_number"] = d["date"].dt.month
    d["month_name"] = d["date"].dt.strftime("%b")
    d["year_month"] = d["date"].dt.strftime("%Y-%m")
    d["month_start"] = d["date"].dt.to_period("M").dt.start_time
    # Same rule as sql/06: months with < 500 delivered orders are sparse dataset edges.
    edge = monthly.assign(month_start=pd.to_datetime(monthly["month"]))[["month_start", "is_partial_edge"]]
    d = d.merge(edge, on="month_start", how="left")
    # Months with no delivered orders are missing from sql/06 and are edges too.
    d["is_partial_edge"] = d["is_partial_edge"].astype("boolean").fillna(True).astype(bool)
    for col in ("date", "month_start"):
        d[col] = d[col].dt.date  # store as DATE, not TIMESTAMP
    return d


def build_recon(con) -> pd.DataFrame:
    """Headline numbers straight from the SQL layer (nothing typed by hand)."""
    k = db.query(con, "10_kpis.sql").iloc[0]
    lvo = db.query(con, "12_late_vs_ontime.sql").set_index("delivery")
    st = db.query(con, "14_state_ops.sql").set_index("customer_state")
    seg = db.query(con, "09_rfm_segments.sql").set_index("segment")
    rows = [
        # metric, sql value, tolerance, unit, source
        ("Total orders (all statuses)",        k["total_orders_all_statuses"],     0,     "count", "sql/10_kpis.sql"),
        ("Delivered orders",                   k["delivered_orders"],              0,     "count", "sql/10_kpis.sql"),
        ("Revenue (R$)",                       k["revenue"],                       0.01,  "R$",    "sql/10_kpis.sql"),
        ("Average order value (R$)",           k["avg_order_value"],               0.01,  "R$",    "sql/10_kpis.sql"),
        ("Customers (1+ delivered order)",     k["customers"],                     0,     "count", "sql/10_kpis.sql"),
        ("Repeat customers (%)",               k["repeat_customer_pct"],           0.01,  "%",     "sql/10_kpis.sql"),
        ("Average review score",               k["avg_review_score"],              0.001, "score", "sql/10_kpis.sql"),
        ("Late (%) - all delivered orders",    k["late_delivery_pct"],             0.01,  "%",     "sql/10_kpis.sql"),
        ("Late (%) - reviewed orders only",    lvo.loc["Late", "pct_of_orders"],   0.01,  "%",     "sql/12_late_vs_ontime.sql"),
        ("Low-review (%) - late orders",       lvo.loc["Late", "pct_low_review"],  0.01,  "%",     "sql/12_late_vs_ontime.sql"),
        ("Low-review (%) - on-time orders",    lvo.loc["On time or early", "pct_low_review"], 0.01, "%", "sql/12_late_vs_ontime.sql"),
        ("Late (%) - RJ",                      st.loc["RJ", "late_pct"],           0.01,  "%",     "sql/14_state_ops.sql"),
        ("Late (%) - SP",                      st.loc["SP", "late_pct"],           0.01,  "%",     "sql/14_state_ops.sql"),
        ("Champions - share of revenue (%)",   seg.loc["Champions", "pct_of_revenue"], 0.01, "%",    "sql/09_rfm_segments.sql"),
    ]
    df = pd.DataFrame(rows, columns=["metric", "sql_value", "tolerance", "unit", "sql_source"])
    df["sql_value"] = df["sql_value"].astype(float)
    df["tolerance"] = df["tolerance"].astype(float)
    df.insert(0, "sort_order", range(1, len(df) + 1))
    return df


def run_checks(con, t: dict, kpi_revenue: float) -> bool:
    """Integrity checks Power BI relationships depend on. Returns True if all pass."""
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= bool(passed)
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")

    fo, fi = t["fact_orders"], t["fact_order_items"]
    n_orders = con.sql("SELECT COUNT(*) FROM orders").fetchone()[0]
    check("fact_orders has one row per raw order", len(fo) == n_orders, f"{len(fo):,} vs {n_orders:,}")
    for table, key in [("fact_orders", "order_id"), ("dim_customer", "customer_unique_id"),
                       ("dim_product", "product_id"), ("dim_seller", "seller_id"),
                       ("dim_state", "state_code"), ("dim_date", "date")]:
        dup = int(t[table][key].duplicated().sum())
        check(f"{table}.{key} is unique", dup == 0, f"{dup} duplicates" if dup else "")
    for label, col, ref in [
        ("every item's order_id exists in fact_orders", fi["order_id"], fo["order_id"]),
        ("every item's product_id exists in dim_product", fi["product_id"], t["dim_product"]["product_id"]),
        ("every item's seller_id exists in dim_seller", fi["seller_id"], t["dim_seller"]["seller_id"]),
        ("every order's customer exists in dim_customer", fo["customer_unique_id"], t["dim_customer"]["customer_unique_id"]),
        ("every order's state exists in dim_state", fo["customer_state"], t["dim_state"]["state_code"]),
        ("every order's purchase_date exists in dim_date", fo["purchase_date"], t["dim_date"]["date"]),
    ]:
        missing = int((~col.isin(ref)).sum())
        check(label, missing == 0, f"{missing} orphan rows" if missing else "")
    delivered_ids = set(fo.loc[fo["is_delivered"] == 1, "order_id"])
    rev = float(fi.loc[fi["order_id"].isin(delivered_ids), "price"].sum())
    check("item prices on delivered orders = sql/10 revenue", abs(rev - kpi_revenue) < 0.01,
          f"{rev:,.2f} vs {kpi_revenue:,.2f}")
    return ok


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = db.connect()                       # CSVs -> views, runs sql/00_base_views.sql
    db.run_script(con, "08_rfm_customers.sql")
    print(f"Writing parquet files to {OUT_DIR}")

    t = {}
    t["fact_orders"] = save(con.sql(FACT_ORDERS_SQL), "fact_orders")
    t["fact_order_items"] = save(con.sql(FACT_ORDER_ITEMS_SQL), "fact_order_items")
    t["dim_customer"] = save(con.sql(DIM_CUSTOMER_SQL), "dim_customer")
    t["dim_product"] = save(con.sql(DIM_PRODUCT_SQL), "dim_product")
    t["dim_seller"] = save(con.sql(DIM_SELLER_SQL), "dim_seller")
    t["dim_state"] = save(build_dim_state(), "dim_state")
    monthly = db.query(con, "06_monthly_trend.sql")
    purchase_dates = pd.to_datetime(t["fact_orders"]["purchase_date"])
    t["dim_date"] = save(build_dim_date(purchase_dates, monthly), "dim_date")
    recon = save(build_recon(con), "recon_sql")

    print("\nIntegrity checks")
    kpi_revenue = float(recon.loc[recon["metric"] == "Revenue (R$)", "sql_value"].iloc[0])
    ok = run_checks(con, t, kpi_revenue)

    print("\nSQL-side reference values (Power BI's DAX measures must reproduce these)")
    print(recon[["metric", "sql_value"]].to_string(index=False))
    print("\nAll checks passed." if ok else "\nSome checks FAILED - fix before loading into Power BI.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
