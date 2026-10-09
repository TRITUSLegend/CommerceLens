"""DuckDB helpers: register the raw Olist CSVs as views and run .sql files.

Nothing is copied or materialised - DuckDB queries the CSVs in DATA_DIR directly.
"""

from pathlib import Path

import duckdb
import pandas as pd

from src.config import DATA_DIR, REPO_ROOT

SQL_DIR = REPO_ROOT / "sql"

# view name -> CSV file name
TABLES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def connect(data_dir: Path = DATA_DIR, base_views: bool = True) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB connection with one view per raw CSV.

    If base_views is True, also runs sql/00_base_views.sql, which defines the
    cleaned, joined views (order_items_enriched, orders_enriched) that every
    downstream query builds on.
    """
    con = duckdb.connect()
    for view, file_name in TABLES.items():
        path = (Path(data_dir) / file_name).as_posix()
        # Zip-code prefixes must stay text: they have meaningful leading zeros.
        zip_cols = [c for c in _columns(path) if c.endswith("zip_code_prefix")]
        types = ", ".join(f"'{c}': 'VARCHAR'" for c in zip_cols)
        type_arg = f", types = {{{types}}}" if zip_cols else ""
        con.execute(
            f"CREATE OR REPLACE VIEW {view} AS "
            f"SELECT * FROM read_csv('{path}', header = true{type_arg})"
        )
    if base_views:
        run_script(con, "00_base_views.sql")
    return con


def _columns(path: str) -> list[str]:
    """Return the header column names of a CSV."""
    with open(path, encoding="utf-8-sig") as f:
        return [c.strip().strip('"') for c in f.readline().split(",")]


def load_sql(name: str) -> str:
    """Read a query file from the sql/ directory."""
    return (SQL_DIR / name).read_text(encoding="utf-8")


def run_script(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """Execute a .sql file that only defines views/tables (no result needed)."""
    con.execute(load_sql(name))


def query(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    """Run a single-SELECT .sql file and return the result as a DataFrame."""
    return con.sql(load_sql(name)).df()
