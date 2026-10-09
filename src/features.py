"""Model datasets built from sql/18_order_features.sql and sql/19_repeat_target.sql.

All features are known at purchase time; see the SQL file for what is excluded
(delivery dates, delay, review content) to prevent target leakage.
"""

import duckdb
import pandas as pd

from src import db

NUMERIC_FEATURES = [
    "items_value", "freight_value", "freight_ratio", "n_items", "n_products", "n_sellers",
    "promised_days", "purchase_month", "purchase_dow", "purchase_hour",
    "total_weight_g", "max_volume_cm3", "avg_photos", "avg_description_length",
    "installments", "n_payment_types", "same_state", "distance_km",
    "seller_prior_orders", "customer_prior_orders",
]
CATEGORICAL_FEATURES = ["main_category", "payment_type", "customer_state", "seller_state"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def order_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return one row per delivered order with purchase-time features and targets."""
    db.run_script(con, "18_order_features.sql")
    # ORDER BY makes row order (and therefore the train/test split) reproducible.
    df = con.sql("SELECT * FROM order_features ORDER BY order_id").df()
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].fillna("unknown").astype("category")
    return df


def low_review_dataset(con: duckdb.DuckDBPyConnection):
    """X, y, purchase timestamps for predicting a 1-2 star review (orders with a review)."""
    df = order_features(con)
    df = df[df["review_score"].notna()].reset_index(drop=True)
    return df[FEATURES], df["low_review"].astype(int), df["order_purchase_timestamp"]


def repeat_dataset(con: duckdb.DuckDBPyConnection):
    """X, y, purchase timestamps for predicting a repeat purchase within 180 days.

    Features describe the customer's first delivered order. customer_prior_orders
    is dropped because it is always 0 for a first order.
    """
    df = order_features(con)
    target = db.query(con, "19_repeat_target.sql").sort_values("customer_unique_id", ignore_index=True)
    df = target.merge(df, left_on="first_order_id", right_on="order_id", how="inner")
    cols = [c for c in FEATURES if c != "customer_prior_orders"]
    return df[cols], df["returned_180d"].astype(int), df["order_purchase_timestamp"]
