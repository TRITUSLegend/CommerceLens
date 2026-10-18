# Power BI data dictionary

Every table and column in `powerbi/data/`, written by `scripts/build_powerbi_data.py`.
The SQL layer owns the definitions: the fact and dimension tables are selected from the DuckDB
views in `sql/00_base_views.sql` (and `sql/08` for RFM), so Power BI inherits the same revenue,
customer, late and latest-review rules as the notebooks and the Streamlit dashboard.

Types are the parquet types Power BI imports (text, whole number, decimal number, date,
true/false). "Blank" means NULL in parquet and BLANK in DAX.

## Relationships (all one-to-many, single direction)

| From (many side) | To (one side) |
|---|---|
| `fact_order_items[order_id]` | `fact_orders[order_id]` |
| `fact_order_items[product_id]` | `dim_product[product_id]` |
| `fact_order_items[seller_id]` | `dim_seller[seller_id]` |
| `fact_orders[customer_unique_id]` | `dim_customer[customer_unique_id]` |
| `fact_orders[customer_state]` | `dim_state[state_code]` |
| `fact_orders[purchase_date]` | `dim_date[date]` (date table) |

`recon_sql`, `recon_seller_state` and the six Model page tables have no relationships.

## fact_orders: one row per order, all statuses (99,441 rows)

Mirrors `orders_enriched` in `sql/00_base_views.sql`. Scope flags reproduce the `WHERE` clauses of
the SQL files so DAX filters on 0/1 values and never compares a column with BLANK.

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `order_id` | text | Order key | `orders.order_id` |
| `customer_unique_id` | text | The real person (Olist issues a new `customer_id` per order) | `customers.customer_unique_id` via `customer_id` |
| `customer_state` | text | Customer state **for this order** (39 people have orders in more than one state, so state is not on `dim_customer`) | `sql/00` `orders_enriched.customer_state` |
| `order_status` | text | Olist status (delivered, shipped, canceled, ...) | `orders.order_status` |
| `purchase_date` | date | Purchase timestamp cast to a date; joins to `dim_date` | `CAST(order_purchase_timestamp AS DATE)` |
| `estimated_delivery_date` | date | Promised delivery date | `order_estimated_delivery_date` |
| `delivered_date` | date | Date the customer received the order; blank if never delivered | `order_delivered_customer_date` |
| `items_value` | decimal | Sum of item prices (revenue definition, freight excluded); blank for the 775 orders without items | `sql/00` `item_totals.items_value` |
| `freight_value` | decimal | Sum of item freight | `sql/00` `item_totals.freight_value` |
| `n_items` | whole number | Items in the order | `sql/00` |
| `n_sellers` | whole number | Distinct sellers in the order | `sql/00` |
| `review_score` | whole number | Latest review per order (most recent answer, then creation date); blank without a review | `sql/00` `order_reviews_latest` |
| `delay_days` | whole number | Delivered date minus promised date, in days (positive = late); blank without a delivered date | `sql/00` `delay_days` |
| `delivery_days` | whole number | Delivered date minus purchase date, in days | `sql/00` `delivery_days` |
| `is_delivered` | whole number | 1 if `order_status = 'delivered'` | every `WHERE order_status = 'delivered'` |
| `in_delay_scope` | whole number | 1 if delivered **and** `delay_days` is not blank (96,470 orders) | `sql/10` late %, `sql/14`, `sql/21` |
| `in_review_scope` | whole number | 1 if in delay scope **and** reviewed (95,824 orders) | `sql/11`, `sql/12`, `sql/15` |
| `is_late` | whole number | 1 if `delay_days > 0`; 0 otherwise, including when `delay_days` is blank | "Late" everywhere |
| `is_low_review` | whole number | 1 if `review_score <= 2`, 0 if reviewed and higher; blank without a review | "Low review" everywhere |
| `delay_bucket` | text | 8 bands of `delay_days` (15+ days early ... 15+ days late); blank without `delay_days`. Six canceled orders also have a delivered date and a bucket, so always pair it with a scope flag | `sql/11` CASE |
| `delay_bucket_order` | whole number | Sort order 1-8 for `delay_bucket` (hidden) | `sql/11` `bucket_order` |
| `freight_share_bucket` | text | Order freight / item value in 5 bands (<10% ... 50%+); blank for orders without items | `sql/15` CASE |
| `freight_bucket_order` | whole number | Sort order 1-5 for `freight_share_bucket` (hidden) | `sql/15` `bucket_order` |

## fact_order_items: one row per order item (112,650 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `order_id` | text | Order key (hidden; filtered through `fact_orders`) | `order_items.order_id` |
| `order_item_id` | whole number | Item sequence within the order | `order_items.order_item_id` |
| `product_id` | text | Product key (hidden) | `order_items.product_id` |
| `seller_id` | text | Seller key (hidden) | `order_items.seller_id` |
| `price` | decimal | Item price. `Revenue` = sum of `price` on delivered orders | `order_items.price` |
| `freight_value` | decimal | Item freight | `order_items.freight_value` |

## dim_customer: one row per real person (96,096 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `customer_unique_id` | text | Person key | `customers.customer_unique_id` |
| `segment` | text | RFM segment; "No delivered order" for the 2,738 people without a delivered order | `sql/08_rfm_customers.sql` |
| `segment_order` | whole number | Sort order for `segment` (hidden) | build script |
| `r_score` | whole number | Recency quintile, 5 = most recent; blank without a delivered order | `sql/08` `NTILE(5)` |
| `m_score` | whole number | Monetary quintile, 5 = highest spend | `sql/08` `NTILE(5)` |
| `recency_days` | whole number | Days from last purchase to the day after the dataset's last purchase | `sql/08` |
| `is_repeat_buyer` | whole number | 1 if 2+ delivered orders | `sql/08` |

## dim_product: one row per product (32,951 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `product_id` | text | Product key | `products.product_id` |
| `category` | text | English category, else the Portuguese name (2 untranslated categories), else "unknown" (74 values) | `sql/00` `COALESCE(...)` |
| `product_weight_g` | whole number | Product weight in grams | `products.product_weight_g` |

## dim_seller: one row per seller (3,095 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `seller_id` | text | Seller key | `sellers.seller_id` |
| `seller_state` | text | Seller state (where orders ship from) | `sellers.seller_state` |
| `seller_city` | text | Seller city | `sellers.seller_city` |
| `seller_tier` | text | "Top 20% sellers" / "Other 80% sellers" by delivered revenue; "No delivered sales" for 125 sellers | `sql/17` `PERCENT_RANK` |

## dim_state: one row per Brazilian state (27 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `state_code` | text | Two-letter code; joins to `fact_orders[customer_state]` | reference data |
| `state_name` | text | State name (data category: State or Province) | reference data |
| `region` | text | Macro-region (North, Northeast, Central-West, Southeast, South) | reference data |

## dim_date: one row per day, 2016-09-01 to 2018-10-31 (791 rows; marked as the date table)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `date` | date | Calendar day (key) | build script |
| `year` | whole number | Year | build script |
| `quarter` | text | Q1-Q4 | build script |
| `month_number` | whole number | 1-12 (hidden; sort column for `month_name`) | build script |
| `month_name` | text | Jan-Dec | build script |
| `year_month` | text | YYYY-MM | build script |
| `month_start` | date | First day of the month; axis for monthly visuals | `sql/06` `DATE_TRUNC('month', ...)` |
| `is_partial_edge` | true/false | TRUE for months with fewer than 500 delivered orders, or none (2016-09 to 2016-12, 2018-09, 2018-10) | `sql/06` `is_partial_edge` |

## recon_sql: SQL reference values for the Reconciliation page (14 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `sort_order` | whole number | Row order 1-14 (hidden; sort column for `metric`) | build script |
| `metric` | text | Metric name; `DAX Value` switches on it | build script |
| `sql_value` | decimal | Value computed by the SQL file in `sql_source` | `sql/10`, `sql/12`, `sql/14`, `sql/09` |
| `tolerance` | decimal | Largest allowed `Diff` (0 for counts; at least half the SQL rounding step otherwise) | build script |
| `unit` | text | count, R$, %, score | build script |
| `sql_source` | text | SQL file the value comes from | build script |

## recon_seller_state: SQL reference for the seller-state measures (22 rows)

| Column | Type | Definition | Mirrors |
|---|---|---|---|
| `seller_state` | text | Seller state | `sql/21_seller_state_ops.sql` |
| `orders` | whole number | Delivered orders with a delivery date that include a seller from this state | `sql/21` |
| `late_pct` | decimal | Late % of those orders | `sql/21` |
| `reviewed_orders` | whole number | Those orders that have a review | `sql/21` |
| `pct_low_review` | decimal | Low-review % of the reviewed orders | `sql/21` |

## Model page tables (copied byte for byte from `dashboard/data/`, built by `scripts/build_dashboard_data.py`)

| Table | Column | Type | Definition |
|---|---|---|---|
| `model_metrics` | `model` | text | LightGBM, Logistic regression, No-skill baseline |
| | `evaluation` | text | "Stratified random split" or "Out-of-time (train < 2018-05-01)" |
| | `positive_rate` | decimal | Share of low reviews in the evaluated set |
| | `roc_auc` | decimal | ROC-AUC |
| | `pr_auc` | decimal | PR-AUC (average precision) |
| | `pr_auc_lift` | decimal | `pr_auc / positive_rate` |
| `model_capture_curve` | `top_frac` | decimal | Share of orders flagged, 0.01 to 1.00 |
| | `precision_at_top` | decimal | Share of flagged orders that got a low review |
| | `recall_at_top` | decimal | Share of all low reviews among the flagged orders |
| | `lift_vs_random` | decimal | `precision_at_top / positive_rate` |
| `shap_importance` | `feature` | text | Model feature |
| | `mean_abs_shap` | decimal | Mean absolute SHAP value on the test set |
| `shap_state_effect` | `customer_state` | text | Customer state (states with 50+ test orders) |
| | `mean_shap` | decimal | Mean SHAP value of `customer_state` for that state |
| | `orders` | whole number | Test orders from that state |
| `model_curves` | `model` | text | LightGBM or Logistic regression |
| | `curve` | text | ROC or PR |
| | `x` | decimal | False-positive rate (ROC) or recall (PR) |
| | `y` | decimal | True-positive rate (ROC) or precision (PR) |
| `model_target_comparison` | `target` | text | "Repeat purchase (180d)" or "Low review (1-2 stars)" |
| | `rows` | whole number | Orders or customers in the dataset |
| | `positive_rate` | decimal | Share of positives |
| | `roc_auc` | decimal | ROC-AUC on the stratified test split |
| | `pr_auc` | decimal | PR-AUC |
| | `pr_auc_lift` | decimal | `pr_auc / positive_rate` |
| | `precision_top10` | decimal | Precision among the riskiest 10% |
| | `recall_top10` | decimal | Recall among the riskiest 10% |

## Tables defined in the model only (not in `powerbi/data/`)

| Table | Definition |
|---|---|
| `_Measures` | Home table for every measure; one hidden placeholder column |
| `Late Cut` | `GENERATESERIES(0, 100, 5)`: the what-if slicer for the late-delivery cut |
| `Flag %` | `GENERATESERIES(1, 100, 1)`: the triage slicer on the Model page |
