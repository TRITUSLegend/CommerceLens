# CommerceLens in Power BI — rebuild notes

These notes describe how to rebuild the Streamlit dashboard (`dashboard/app.py`) in Power BI Desktop. There are three routes:

- **Route C: SQL export plus scope flags (recommended).** `scripts/build_powerbi_data.py` exports a star schema from the same DuckDB views the notebooks use, with the SQL scope rules precomputed as 0/1 flags. The measures in [`powerbi/dax_measures.md`](../powerbi/dax_measures.md) are reconciled against SQL. See [Route C](#route-c-sql-export-plus-scope-flags-recommended).
- **Route A: pre-aggregated (fastest).** Load the parquet files in `dashboard/data/`. Every number matches the Streamlit app exactly, because both read the same files.
- **Route B: star schema from the raw CSVs.** Build the model in Power Query from the CSVs. This re-implements the SQL definitions by hand, so each one has to be copied exactly (the notes below were corrected where they did not match the SQL).

Definitions used everywhere, and they must stay the same in Power BI:

| Term | Definition |
|---|---|
| Revenue | `SUM(order_items.price)` on orders with `order_status = "delivered"` (freight excluded) |
| Customer | `customers.customer_unique_id` (Olist creates a new `customer_id` per order) |
| Late | `order_delivered_customer_date` later than `order_estimated_delivery_date` (compared as dates) |
| Low review | `review_score <= 2`, using the latest review per order (latest `review_answer_timestamp`, then latest `review_creation_date`) |
| Repeat customer | 2+ delivered orders |
| Category | English name, else the Portuguese name (2 categories have no translation), else "unknown" |
| Customer state | The state on the **order** (via `customer_id`), not a per-person attribute: 39 people have orders in more than one state |

### Late rate: three numbers, two denominators

The project quotes three late rates. They are all correct; they answer different questions.

| Figure | Numerator / denominator | Population | Where it appears |
|---|---|---|---|
| 6.66% | 6,381 / 95,824 | Delivered, with a delivery date, **with a review** (`sql/12`) | README "6.7% of orders" (key finding, finding 1); `Late % (reviewed)`; the denominator of every late-vs-review comparison |
| 6.77% | 6,534 / 96,470 | Delivered, with a delivery date (`sql/10`) | KPI card, `Late %`, Reconciliation page |
| 6.8% | order-weighted mean of the 27 state rates in `sql/14` = 6.7714% | The same 96,470 orders as 6.77% | README finding 2 ("national late rate"), computed in `02_insights.ipynb` |

So 6.66% and 6.77% differ in denominator: the 646 delivered orders with a delivery date but no review
are in 6.77% only. 6.8% has the same denominator as 6.77%; it is 6.7714% (the average of state rates
already rounded to 2 decimals) printed to one decimal. In Power BI, use `Late % (reviewed)` next to
any review metric and `Late %` for the operational KPI, and label which one a visual shows.

---

## Route C: SQL export plus scope flags (recommended)

```powershell
.venv-powerbi\Scripts\python scripts/build_powerbi_data.py       # powerbi/data/*.parquet + integrity checks
.venv-powerbi\Scripts\python scripts/verify_powerbi_measures.py  # pandas mirror of every DAX measure vs SQL
.venv-powerbi\Scripts\python scripts/build_powerbi_tmdl.py       # TMDL semantic model (opens in Desktop; see powerbi/README.md)
```

- **Tables:** `fact_orders`, `fact_order_items`, `dim_customer`, `dim_product`, `dim_seller`,
  `dim_state`, `dim_date`, plus `recon_sql` / `recon_seller_state` (SQL reference values) and the six
  Model page tables. Every column is described in
  [`powerbi_data_dictionary.md`](powerbi_data_dictionary.md).
- **Scope flags** reproduce the SQL `WHERE` clauses: `is_delivered`, `in_delay_scope` (delivered with
  a delivery date: `sql/10` late %, `sql/14`), `in_review_scope` (also reviewed: `sql/11`, `sql/12`,
  `sql/15`), `is_late`, `is_low_review`. Measures filter on these 0/1 values, so none compares a
  column with BLANK (which DAX treats as equal to 0).
- **Integrity checks** run on every export: one row per order, unique dimension keys, no orphan
  foreign keys for the six relationships, scope flags nest, item revenue equals `sql/10` revenue,
  and the Model page files are byte-identical copies.
- **Measures** live in [`powerbi/dax_measures.md`](../powerbi/dax_measures.md), with the SQL file
  each one mirrors. The build guide is [`powerbi_build_checklist.md`](powerbi_build_checklist.md).

### Reconciliation scope: what the checks prove and what they do not

`scripts/verify_powerbi_measures.py` and the Reconciliation page test the **DAX layer against the
SQL layer**: measure logic, scope filters, the six relationships and filter propagation (for example
`dim_state` → `fact_orders` → `fact_order_items`, and `CROSSFILTER` from sellers or products back to
orders). A match means Power BI reproduces what SQL computes.

They do **not** re-derive the SQL inputs independently. `delay_days`, `delivery_days`, the latest
review per order, the English category and the RFM segments are computed in `sql/00` and `sql/08`
and exported as columns, so an error there would appear identically in both layers. The SQL itself
is checked separately: section A of the script confirms the export equals the committed Streamlit
outputs, and the notebooks print every figure in the README.

The pandas mirror reproduces DAX semantics (CALCULATE filter replacement, context transition,
BLANK handling, single-direction relationships) but is not the DAX engine, so measures are labelled
LOGIC-CHECKED until the Reconciliation page shows "Match" in Power BI Desktop.

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
| `FactOrders` | `olist_orders_dataset.csv` | Merge `customers` on `customer_id` to add `customer_unique_id` and `customer_state` (the order's state). Add `DelayDays = Duration.Days(Date.From([order_delivered_customer_date]) - Date.From([order_estimated_delivery_date]))` and `DeliveryDays` the same way from purchase to delivered. Merge `FactOrderItems` grouped by `order_id` to add `ItemsValue` = sum of `price` (null when the order has no items). Merge the latest review (next row) to add `review_score` |
| `Reviews` (staging, not loaded) | `olist_order_reviews_dataset.csv` | Sort by `review_answer_timestamp` descending, then `review_creation_date` descending, and keep the first row per `order_id` (547 orders have more than one review). Merge `review_score` into `FactOrders` instead of loading a separate table: a 1:1 relationship in Power BI always filters in both directions |
| `DimProduct` | `olist_products_dataset.csv` | Merge `product_category_name_translation`. Category = English name if present, **else the Portuguese name**, else "unknown" (as `sql/00`). Replacing every missing translation with "unknown" would fold `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos` into "unknown" (72 categories instead of 74) |
| `DimSeller` | `olist_sellers_dataset.csv` | Keep zip prefix as **Text** |
| `DimCustomer` | `olist_customers_dataset.csv` | Keep zip prefix as **Text**; distinct on `customer_unique_id` for a person-level dimension. Do not take state from here: use `FactOrders[customer_state]` |
| `DimDate` | DAX `CALENDAR(DATE(2016,9,1), DATE(2018,10,31))` | Add Year, Month, YearMonth |

### Relationships (single direction, one-to-many)
- `FactOrders[order_id]` 1 → * `FactOrderItems[order_id]`
- `DimProduct[product_id]` 1 → * `FactOrderItems[product_id]`
- `DimSeller[seller_id]` 1 → * `FactOrderItems[seller_id]`
- `DimCustomer[customer_unique_id]` 1 → * `FactOrders[customer_unique_id]`
- `DimDate[Date]` 1 → * `FactOrders[PurchaseDate]` (add `PurchaseDate = DATEVALUE(order_purchase_timestamp)`)

### DAX measures
```DAX
Delivered Orders = CALCULATE(DISTINCTCOUNT(FactOrders[order_id]), FactOrders[order_status] = "delivered")

Revenue = CALCULATE(SUM(FactOrderItems[price]), FactOrders[order_status] = "delivered")

// SQL (sql/10): AVG(items_value) over delivered orders, NULLs skipped. AVERAGE skips BLANKs
// the same way. DIVIDE([Revenue], [Delivered Orders]) gives the same 137.04 on this data only
// because every delivered order has items; it would count an order without items.
Avg Order Value = CALCULATE(AVERAGE(FactOrders[ItemsValue]), FactOrders[order_status] = "delivered")

Customers = CALCULATE(DISTINCTCOUNT(FactOrders[customer_unique_id]), FactOrders[order_status] = "delivered")

Repeat Customer % =
VAR PerCustomer =
    CALCULATETABLE(
        ADDCOLUMNS(VALUES(FactOrders[customer_unique_id]), "n", CALCULATE(DISTINCTCOUNT(FactOrders[order_id]))),
        FactOrders[order_status] = "delivered")
RETURN DIVIDE(COUNTROWS(FILTER(PerCustomer, [n] >= 2)), COUNTROWS(PerCustomer))

Late Orders = CALCULATE([Delivered Orders], FactOrders[DelayDays] > 0)
Late % = DIVIDE([Late Orders], CALCULATE([Delivered Orders], NOT ISBLANK(FactOrders[DelayDays])))

Avg Review = CALCULATE(AVERAGE(FactOrders[review_score]), FactOrders[order_status] = "delivered")

// SQL scope (sql/11, sql/12, sql/14): delivered, WITH a delivery date, with a review. Leaving out
// the delivery-date condition adds 8 orders to the denominator. Keep NOT ISBLANK on review_score:
// BLANK <= 2 is TRUE in DAX, so unreviewed orders would otherwise count as low reviews.
Low Review % =
CALCULATE(
    DIVIDE(COUNTROWS(FILTER(FactOrders, FactOrders[review_score] <= 2)), COUNTROWS(FactOrders)),
    FactOrders[order_status] = "delivered",
    NOT ISBLANK(FactOrders[DelayDays]),
    NOT ISBLANK(FactOrders[review_score]))

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
- Late-delivery what-if: a numeric-range parameter `Cut %` (0–100). The measure `Low reviews avoided = late_orders × Cut% × (late low-review rate − on-time low-review rate)` uses the values in `late_vs_ontime` (Route A) or the `Low Review % (Late)` / `Low Review % (On time)` measures (Route C, see `powerbi/dax_measures.md`). Label it as an upper bound.
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
