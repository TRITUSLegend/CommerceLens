# CommerceLens in Power BI — rebuild notes

These notes describe how to rebuild the Streamlit dashboard (`dashboard/app.py`) in Power BI Desktop by hand. There are two routes:

- **Route A: pre-aggregated (fastest).** Load the parquet files in `dashboard/data/`. Every number matches the Streamlit app exactly, because both read the same files.
- **Route B: star schema from the raw CSVs.** Build a proper model with DAX measures. This takes longer, but it shows Power BI modelling skills, and slicers work across every visual.

Definitions used everywhere, and they must stay the same in Power BI:

| Term | Definition |
|---|---|
| Revenue | `SUM(order_items.price)` on orders with `order_status = "delivered"` (freight excluded) |
| Customer | `customers.customer_unique_id` (Olist creates a new `customer_id` per order) |
| Late | `order_delivered_customer_date` later than `order_estimated_delivery_date` (compared as dates) |
| Low review | `review_score <= 2`, using the latest review per order |
| Repeat customer | 2+ delivered orders |

---

## Route A: parquet tables

**Get Data → Parquet** (or Folder → `dashboard/data` and expand). Each file is a standalone table, and none of them need relationships.

| Table | Source query | Used on page |
|---|---|---|
| `kpis` | `sql/10_kpis.sql` | Overview |
| `funnel`, `order_status` | `sql/02`, `sql/01` | Overview |
| `pareto_category`, `pareto_seller`, `revenue_by_state` | `sql/03`, `04`, `05` | Revenue |
| `monthly_trend` | `sql/06` | Revenue |
| `monthly_ops` | `sql/20` | Overview (operations health) |
| `order_frequency`, `rfm_segments` | `sql/07`, `sql/09` | Customers |
| `delay_vs_review`, `late_vs_ontime`, `state_ops`, `category_ops`, `freight_vs_review`, `first_order_vs_repeat`, `seller_tiers` | `sql/11`–`17` | Satisfaction drivers |
| `model_target_comparison`, `model_metrics`, `model_capture`, `shap_importance`, `shap_beeswarm`, `shap_state_effect`, `model_capture_curve`, `model_curves` | `scripts/build_dashboard_data.py` | Model |

On Route A, measures are simple aggregations of already-computed columns (for example `Revenue = SUM(revenue_by_state[revenue])`). Filter `monthly_trend` with `is_partial_edge = FALSE`.

---

## Route B: star schema from the CSVs

### Tables (Power Query)
| Table | CSV | Power Query steps |
|---|---|---|
| `FactOrderItems` | `olist_order_items_dataset.csv` | Types: price and freight_value as Decimal |
| `FactOrders` | `olist_orders_dataset.csv` | Merge `customers` to add `customer_unique_id` and `customer_state`. Add `DelayDays = Duration.Days(Date.From([order_delivered_customer_date]) - Date.From([order_estimated_delivery_date]))` and `DeliveryDays` the same way from purchase to delivered |
| `Reviews` | `olist_order_reviews_dataset.csv` | Group by `order_id` and keep the row with the max `review_answer_timestamp` (latest review per order) |
| `DimProduct` | `olist_products_dataset.csv` | Merge `product_category_name_translation` to get the English category; replace nulls with "unknown" |
| `DimSeller` | `olist_sellers_dataset.csv` | Keep zip prefix as **Text** |
| `DimCustomer` | `olist_customers_dataset.csv` | Keep zip prefix as **Text**; distinct on `customer_unique_id` for a person-level dimension |
| `DimDate` | DAX `CALENDAR(DATE(2016,9,1), DATE(2018,10,31))` | Add Year, Month, YearMonth |

### Relationships (single direction, one-to-many)
- `FactOrders[order_id]` 1 → * `FactOrderItems[order_id]`
- `FactOrders[order_id]` 1 → 1 `Reviews[order_id]`
- `DimProduct[product_id]` 1 → * `FactOrderItems[product_id]`
- `DimSeller[seller_id]` 1 → * `FactOrderItems[seller_id]`
- `DimCustomer[customer_unique_id]` 1 → * `FactOrders[customer_unique_id]`
- `DimDate[Date]` 1 → * `FactOrders[PurchaseDate]` (add `PurchaseDate = DATEVALUE(order_purchase_timestamp)`)

### DAX measures
```DAX
Delivered Orders = CALCULATE(DISTINCTCOUNT(FactOrders[order_id]), FactOrders[order_status] = "delivered")

Revenue = CALCULATE(SUM(FactOrderItems[price]), FactOrders[order_status] = "delivered")

Avg Order Value = DIVIDE([Revenue], [Delivered Orders])

Customers = CALCULATE(DISTINCTCOUNT(FactOrders[customer_unique_id]), FactOrders[order_status] = "delivered")

Repeat Customer % =
VAR PerCustomer =
    CALCULATETABLE(
        ADDCOLUMNS(VALUES(FactOrders[customer_unique_id]), "n", CALCULATE(DISTINCTCOUNT(FactOrders[order_id]))),
        FactOrders[order_status] = "delivered")
RETURN DIVIDE(COUNTROWS(FILTER(PerCustomer, [n] >= 2)), COUNTROWS(PerCustomer))

Late Orders = CALCULATE([Delivered Orders], FactOrders[DelayDays] > 0)
Late % = DIVIDE([Late Orders], CALCULATE([Delivered Orders], NOT ISBLANK(FactOrders[DelayDays])))

Avg Review = CALCULATE(AVERAGE(Reviews[review_score]), FactOrders[order_status] = "delivered")
Low Review % = DIVIDE(
    CALCULATE(COUNTROWS(Reviews), Reviews[review_score] <= 2, FactOrders[order_status] = "delivered"),
    CALCULATE(COUNTROWS(Reviews), FactOrders[order_status] = "delivered"))

Freight % of Price = DIVIDE(
    CALCULATE(SUM(FactOrderItems[freight_value]), FactOrders[order_status] = "delivered"), [Revenue])

Revenue Share = DIVIDE([Revenue], CALCULATE([Revenue], ALL(DimProduct)))

Cumulative Revenue % (category) =
VAR CurRev = [Revenue]
VAR Ranked = ADDCOLUMNS(ALL(DimProduct[category_english]), "rev", [Revenue])
RETURN DIVIDE(SUMX(FILTER(Ranked, [rev] >= CurRev), [rev]), SUMX(Ranked, [rev]))
```
Add a calculated column `DelayBucket` on `FactOrders` using the same cut-offs as `sql/11_delay_vs_review.sql` (15+ early, 8–14 early, 1–7 early, on the day, 1–3 late, 4–7 late, 8–14 late, 15+ late), plus a numeric `DelayBucketOrder` column to sort it by.

RFM: segmentation relies on NTILE quintiles, which are awkward in DAX. Compute the segment in Power Query, or import `rfm_segments.parquet` from Route A.

---

## Report pages and visuals

Use one accent colour (blue `#2a78d6`), orange `#eb6834` only for "late / above average" highlights, and grey for reference lines. Never use a dual-axis chart. Put the Pareto bars and the cumulative curve in two separate visuals.

**1. Overview**
- Cards: Revenue, Delivered Orders, Avg Order Value, Customers, Repeat Customer %, Avg Review, Late %.
- Funnel visual: stages from `funnel` (Purchased → Payment approved → Handed to carrier → Delivered).
- Line: monthly operations health from `monthly_ops`. A field parameter switches between late %, 1-2★ %, delivery days and average review.
- Slicers: YearMonth and customer state (Route B).

**2. Revenue**
- Bar: top 15 categories by Revenue Share (Top N filter = 15).
- Line: cumulative revenue % against cumulative % of categories or sellers (from `pareto_*`), with a constant line at 80%.
- Line: monthly Revenue (toggle to orders or AOV with a field parameter), excluding edge months.
- Filled map or bar: Revenue by customer state.

**3. Customers & RFM**
- Column: orders per customer (share of customers), which shows the one-time-buyer skew.
- Clustered bar: RFM segment, % of customers vs % of revenue.
- Table: `rfm_segments`.

**4. Satisfaction drivers**
- Late-delivery what-if: a numeric-range parameter `Cut %` (0–100). The measure `Low reviews avoided = late_orders × Cut% × (late low-review rate − on-time low-review rate)` uses the values in `late_vs_ontime`. Label it as an upper bound.
- Column: Low Review % by DelayBucket (conditional formatting: late buckets orange).
- Cards: Late %, Low Review % for late vs on-time orders.
- Scatter: customer state, x = Late %, y = Low Review %, size = Delivered Orders.
- Bar: Low Review % for the top 15 categories by revenue, with an average line.
- Column: on-time Low Review % by freight-share bucket (`freight_vs_review`).
- Bar with error bars: 180-day repeat rate by first-order experience (`first_order_vs_repeat`).

**5. Model** (Route A tables)
- Cards: ROC-AUC and PR-AUC (test and out-of-time), plus recall and precision in the top 10% of scores.
- Bar: `shap_importance` (top 15 features by mean |SHAP|).
- Scatter: `shap_beeswarm`, x = shap_value, y = feature, colour = feature_scaled (low → high).
- Bar: `shap_state_effect`.
- Triage what-if: a numeric-range parameter `Flag %` (1–50) filters `model_capture_curve` on `top_frac = Flag % / 100`. Cards show `recall_at_top`, `precision_at_top` and `lift_vs_random`, and a line chart of `recall_at_top` vs `top_frac` is the gain curve.
- Line: `model_curves` (filter `curve` = ROC or PR), with one series per `model`.

**6. Findings**: a text box per finding (problem → finding → so what → action). Use dynamic text from measures so each number matches the data, not typed values.
