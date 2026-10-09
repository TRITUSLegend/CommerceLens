"""Project configuration.

DATA_DIR is the single setting that controls where the raw Olist CSVs are read
from. It defaults to the repository root (where the CSVs live in this repo) and
can be overridden with the COMMERCELENS_DATA_DIR environment variable.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.environ.get("COMMERCELENS_DATA_DIR", REPO_ROOT)).expanduser().resolve()

KAGGLE_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"

# The 9 files that make up the Olist public dataset.
REQUIRED_FILES = [
    "olist_customers_dataset.csv",
    "olist_geolocation_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv",
    "product_category_name_translation.csv",
]
