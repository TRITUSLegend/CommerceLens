# CommerceLens: DAX measures

All measures live in one table called `_Measures` (Home > Enter data > create a table
named `_Measures` with one dummy column, load it, then add measures with Home > New measure).

Design rule: the SQL layer owns the definitions (revenue, customer, late, latest review).
`scripts/build_powerbi_data.py` exports them as precomputed 0/1 flags and scope columns, so
no measure ever compares a column against `BLANK()` (in DAX, `BLANK()` compares equal to 0,
which silently changes counts).

| Flag in `fact_orders` | Meaning | Mirrors |
|---|---|---|
| `is_delivered` | `order_status = 'delivered'` | every `WHERE order_status = 'delivered'` |
| `in_delay_scope` | delivered AND has `delay_days` | `sql/10` late %, `sql/14` |
| `in_review_scope` | `in_delay_scope` AND has a review | `sql/11`, `sql/12` |
| `is_late` | `delay_days > 0` (0 when no delay_days) | "Late" everywhere |
| `is_low_review` | `review_score <= 2` (blank when no review) | "Low review" everywhere |

## Core measures (each one is reconciled against SQL on the Reconciliation page)

```dax
Total Orders = COUNTROWS ( fact_orders )

Delivered Orders =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[is_delivered] = 1 )

Revenue =
CALCULATE ( SUM ( fact_order_items[price] ), fact_orders[is_delivered] = 1 )

AOV =
CALCULATE ( AVERAGE ( fact_orders[items_value] ), fact_orders[is_delivered] = 1 )

Customers =
CALCULATE ( DISTINCTCOUNT ( fact_orders[customer_unique_id] ), fact_orders[is_delivered] = 1 )

Repeat Customer % =
VAR _cust =
    CALCULATETABLE ( VALUES ( fact_orders[customer_unique_id] ), fact_orders[is_delivered] = 1 )
VAR _n =
    ADDCOLUMNS (
        _cust,
        "@orders", CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[is_delivered] = 1 )
    )
RETURN
    DIVIDE ( COUNTROWS ( FILTER ( _n, [@orders] >= 2 ) ), COUNTROWS ( _n ) )

Avg Review =
CALCULATE ( AVERAGE ( fact_orders[review_score] ), fact_orders[is_delivered] = 1 )

Late % =
CALCULATE ( AVERAGE ( fact_orders[is_late] ), fact_orders[in_delay_scope] = 1 )

Late % (reviewed) =
CALCULATE ( AVERAGE ( fact_orders[is_late] ), fact_orders[in_review_scope] = 1 )

Low Review % =
CALCULATE ( AVERAGE ( fact_orders[is_low_review] ), fact_orders[in_review_scope] = 1 )

Low Review % (Late) =
CALCULATE ( [Low Review %], fact_orders[is_late] = 1 )

Low Review % (On time) =
CALCULATE ( [Low Review %], fact_orders[is_late] = 0 )
```

Suggested formats: counts `#,0`; Revenue and AOV `"R$"#,0.00`; the `%` measures
Percentage with 2 decimals; Avg Review 3 decimals.

**Filter direction.** Every relationship filters one way, from the one side to the many side,
so `fact_orders` is filtered by `dim_state`, `dim_customer` and `dim_date`, and passes its filter
on to `fact_order_items`. Filters on `dim_product` and `dim_seller` stop at `fact_order_items`.
Revenue therefore works by category and seller, but the order-level measures above (Delivered
Orders, AOV, Customers, Late %, Low Review %) return the overall value when a visual is sliced
by category or seller. For those visuals use the `(seller/category)` measures in the report-page
section below, which add `CROSSFILTER(..., BOTH)` inside the measure only.

### Pitfall review (read measure by measure)

| Measure | BLANK compared with 0 | Context transition | Filter direction |
|---|---|---|---|
| Total Orders, Delivered Orders | none: `is_delivered` is never blank | n/a | by state, customer, date only |
| Revenue | none | n/a | correct: filter on `fact_orders` reaches `fact_order_items`; category/seller filter the items directly |
| AOV, Avg Review | `AVERAGE` skips blanks, same as SQL `AVG` skips NULLs | n/a | order level (see note above) |
| Customers | `DISTINCTCOUNT` would count a blank id as a value; none exist (integrity check) | n/a | order level |
| Repeat Customer % | none | correct: the `CALCULATE` inside `ADDCOLUMNS` turns each customer row into a filter, and it re-applies `is_delivered = 1` because `_n` is evaluated outside the `CALCULATETABLE` | order level |
| Late %, Late % (reviewed) | none: `is_late` is 0, never blank, when there is no delay | n/a | order level |
| Low Review % (+ Late / On time) | `is_low_review` is blank without a review, but it is only averaged, never compared; `is_late = 0` is safe because `is_late` is never blank | n/a | order level |
| Status (reconciliation) | **fixed**: `BLANK <= BLANK` is TRUE, so the total row read "Match"; now guarded with `HASONEVALUE` and `ISBLANK` | `Checks Passed` iterates `recon_sql`; `[Status]` is a measure, so each row becomes a filter | `recon_sql` is disconnected on purpose |

`scripts/verify_powerbi_measures.py` prints what naive versions return: a filter
`is_low_review = 0` keeps every unreviewed order, a missing context transition gives every customer
the full order count (Repeat Customer % = 100%), and `[Late %]` sliced by category without
`CROSSFILTER` repeats the national rate.

## Reconciliation measures (`recon_sql` is a disconnected table, no relationships)

```dax
SQL Value = SELECTEDVALUE ( recon_sql[sql_value] )

Tolerance = SELECTEDVALUE ( recon_sql[tolerance] )

DAX Value =
VAR _m = SELECTEDVALUE ( recon_sql[metric] )
RETURN
    SWITCH (
        _m,
        "Total orders (all statuses)",       [Total Orders],
        "Delivered orders",                  [Delivered Orders],
        "Revenue (R$)",                      [Revenue],
        "Average order value (R$)",          [AOV],
        "Customers (1+ delivered order)",    [Customers],
        "Repeat customers (%)",              [Repeat Customer %] * 100,
        "Average review score",              [Avg Review],
        "Late (%) - all delivered orders",   [Late %] * 100,
        "Late (%) - reviewed orders only",   [Late % (reviewed)] * 100,
        "Low-review (%) - late orders",      [Low Review % (Late)] * 100,
        "Low-review (%) - on-time orders",   [Low Review % (On time)] * 100,
        "Late (%) - RJ",                     CALCULATE ( [Late %], dim_state[state_code] = "RJ" ) * 100,
        "Late (%) - SP",                     CALCULATE ( [Late %], dim_state[state_code] = "SP" ) * 100,
        "Champions - share of revenue (%)",
            DIVIDE (
                CALCULATE ( [Revenue], dim_customer[segment] = "Champions" ),
                CALCULATE ( [Revenue], ALL ( dim_customer ) )
            ) * 100,
        BLANK ()
    )

Diff = ABS ( [DAX Value] - [SQL Value] )

-- Only for a single metric row. Without HASONEVALUE the total row compares
-- BLANK <= BLANK, which is TRUE in DAX, and shows "Match". A blank DAX Value
-- is a failure, not a pass.
Status =
IF (
    HASONEVALUE ( recon_sql[metric] ),
    IF ( NOT ISBLANK ( [DAX Value] ) && [Diff] <= [Tolerance], "Match", "Mismatch" )
)

Checks Passed = COUNTROWS ( FILTER ( recon_sql, [Status] = "Match" ) )

Checks Total = COUNTROWS ( recon_sql )
```

## Values the SQL layer produced on the real dataset

Pasted verbatim from the output of `python scripts/build_powerbi_data.py` on the 9 Olist CSVs
(Python 3.13.5, duckdb 1.1.3). They are also in `powerbi/data/recon_sql.parquet`, which the
Reconciliation page reads, so the page never depends on this copy. Every `DAX Value` must
match its row within `tolerance`; `scripts/verify_powerbi_measures.py` checks the same logic
in pandas.

```text
SQL-side reference values (Power BI's DAX measures must reproduce these)
                          metric    sql_value
     Total orders (all statuses)    99441.000
                Delivered orders    96478.000
                    Revenue (R$) 13221498.110
        Average order value (R$)      137.040
  Customers (1+ delivered order)    93358.000
            Repeat customers (%)        3.000
            Average review score        4.156
 Late (%) - all delivered orders        6.770
 Late (%) - reviewed orders only        6.660
    Low-review (%) - late orders       62.420
 Low-review (%) - on-time orders        9.270
                   Late (%) - RJ       12.110
                   Late (%) - SP        4.490
Champions - share of revenue (%)       31.570

All checks passed.
```

---

# Report-page measures (Stage 3)

Added for the report pages. Every measure below is mirrored in pandas by
`scripts/verify_powerbi_measures.py` (sections D1-D9), sliced the way its visual slices it, and
compared with the SQL file named in its heading. Status: **LOGIC-CHECKED** (the pandas mirror
matches SQL; the DAX has not been executed in Power BI Desktop).

## Revenue page: category Pareto (mirrors `sql/03_pareto_category.sql`) and monthly trend (`sql/06_monthly_trend.sql`)

```dax
Revenue Share =
DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_product ) ) )

Category Rank =
IF (
    HASONEVALUE ( dim_product[category] ) && NOT ISBLANK ( [Revenue] ),
    RANKX ( ALL ( dim_product[category] ), [Revenue], , DESC, SKIP )
)

-- Pareto curve. ALL (not ALLSELECTED) keeps the curve over all categories, as in
-- sql/03, even when the visual shows only the top 15. [Revenue] inside ADDCOLUMNS
-- is a measure, so each category row becomes a filter (context transition); a bare
-- SUM ( fact_order_items[price] ) there would give every row the grand total.
-- A category with BLANK @rev fails ">= _cur" and SUMX skips it.
Cumulative Revenue % =
VAR _cur = [Revenue]
VAR _cats =
    ADDCOLUMNS ( ALL ( dim_product[category] ), "@rev", [Revenue] )
RETURN
    IF (
        HASONEVALUE ( dim_product[category] ) && NOT ISBLANK ( _cur ),
        DIVIDE ( SUMX ( FILTER ( _cats, [@rev] >= _cur ), [@rev] ), SUMX ( _cats, [@rev] ) )
    )

Cumulative % of Categories =
DIVIDE (
    [Category Rank],
    COUNTROWS ( FILTER ( ALL ( dim_product[category] ), NOT ISBLANK ( [Revenue] ) ) )
)

-- sql/06 rule: blank when the previous month has fewer than 500 delivered orders.
-- BLANK >= 500 is FALSE, so a month with no orders before it is blank too. dim_date
-- is marked as the date table, so the DATEADD filter on dim_date[date] also clears a
-- page filter on dim_date[is_partial_edge] while the previous month is evaluated.
Revenue MoM % =
VAR _prevOrders = CALCULATE ( [Delivered Orders], DATEADD ( dim_date[date], -1, MONTH ) )
VAR _prevRevenue = CALCULATE ( [Revenue], DATEADD ( dim_date[date], -1, MONTH ) )
RETURN
    IF (
        HASONEVALUE ( dim_date[month_start] ) && _prevOrders >= 500,
        DIVIDE ( [Revenue], _prevRevenue ) - 1
    )
```

Monthly visuals: axis `dim_date[month_start]`, page filter `dim_date[is_partial_edge] = False`
(the same edge months the Streamlit toggle hides). `[Revenue]`, `[Delivered Orders]` and `[AOV]`
by month match `sql/06` as they are.

## Satisfaction page: delay buckets (`sql/11`), customer state (`sql/14`), seller state (`sql/21`), category (`sql/13`)

```dax
Orders (delay scope) =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[in_delay_scope] = 1 )

Orders (review scope) =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[in_review_scope] = 1 )

-- delay_bucket is sorted by delay_bucket_order, so Power BI filters both columns for
-- each bar. ALL ( fact_orders[delay_bucket] ) alone would leave the sort column
-- filtered and every bar would show 100%.
% of Orders (delay bucket) =
DIVIDE (
    [Orders (review scope)],
    CALCULATE (
        [Orders (review scope)],
        ALL ( fact_orders[delay_bucket], fact_orders[delay_bucket_order] )
    )
)

-- Seller or product slicing: dim_seller / dim_product filter fact_order_items only.
-- CROSSFILTER makes the filtered items filter fact_orders for this measure only, so
-- an order counts for every seller state (or category) among its items, which is the
-- attribution rule of sql/17, sql/13 and sql/21. Rows do not add up to the total.
Orders (seller/category) =
CALCULATE ( [Orders (delay scope)], CROSSFILTER ( fact_order_items[order_id], fact_orders[order_id], BOTH ) )

Reviewed Orders (seller/category) =
CALCULATE ( [Orders (review scope)], CROSSFILTER ( fact_order_items[order_id], fact_orders[order_id], BOTH ) )

Late % (seller/category) =
CALCULATE ( [Late %], CROSSFILTER ( fact_order_items[order_id], fact_orders[order_id], BOTH ) )

Low Review % (seller/category) =
CALCULATE ( [Low Review %], CROSSFILTER ( fact_order_items[order_id], fact_orders[order_id], BOTH ) )
```

| Visual | Axis | Measures | Matches |
|---|---|---|---|
| Delay vs review | `fact_orders[delay_bucket]` (sort by `delay_bucket_order`) | `[Orders (review scope)]`, `[% of Orders (delay bucket)]`, `[Low Review %]`, `[Avg Review]` | `sql/11` (all 8 buckets) |
| Customer state | `dim_state[state_code]` | `[Orders (delay scope)]`, `[Late %]`, `[Low Review %]` | `sql/14` (27 states) |
| Seller state | `dim_seller[seller_state]` | `[Orders (seller/category)]`, `[Late % (seller/category)]`, `[Low Review % (seller/category)]` | `sql/21` (22 states) |
| Category | `dim_product[category]` | `[Late % (seller/category)]`, `[Freight % of Price]` | `sql/13` (32 categories with 300+ orders) |

`[Late %]` by delay bucket is 0% or 100% by construction (the buckets are cut on the same
`delay_days`), so the bucket chart shows the low-review rate, not lateness. Several seller states
have fewer than 30 orders (see `recon_seller_state`); add a visual-level filter
`[Orders (seller/category)] >= 30` so tiny samples are not ranked.

## Seller concentration (`sql/17_seller_tier_ops.sql`)

`dim_seller[seller_tier]` is exported with the `sql/17` rule (top 20% of sellers by delivered
revenue; "No delivered sales" for sellers without one).

```dax
% of Revenue (seller) =
DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_seller ) ) )
```

Visual: axis `dim_seller[seller_tier]`, measures `[Revenue]`, `[% of Revenue (seller)]` and
`[Late % (seller/category)]` (an order counts for every tier among its sellers, as in `sql/17`).

## Freight test (`sql/15_freight_ratio_vs_review.sql`)

```dax
Freight % of Price =
DIVIDE (
    CALCULATE ( SUM ( fact_order_items[freight_value] ), fact_orders[is_delivered] = 1 ),
    [Revenue]
)

-- Low-review rate on on-time orders: highest minus lowest freight-share bucket.
Freight Gap On Time (pp) =
(
    CALCULATE ( [Low Review % (On time)], fact_orders[freight_bucket_order] = 5 )
        - CALCULATE ( [Low Review % (On time)], fact_orders[freight_bucket_order] = 1 )
) * 100

Lateness Gap (pp) =
( [Low Review % (Late)] - [Low Review % (On time)] ) * 100
```

Freight visual: axis `fact_orders[freight_share_bucket]` (sort by `freight_bucket_order`),
measures `[Orders (review scope)]`, `[Low Review %]`, `[Late % (reviewed)]` and
`[Low Review % (On time)]`. Use `Late % (reviewed)` here because `sql/15` measures lateness on
reviewed orders. Show the two gap measures as cards side by side, formatted `0.00 "pp"`.

## What-if: cut late deliveries (matches the Streamlit simulator in `dashboard/app.py`)

```dax
-- New table (or Modeling > New parameter > Numeric range, 0 to 100, step 5, default 50)
Late Cut = SELECTCOLUMNS ( GENERATESERIES ( 0, 100, 5 ), "Late Cut %", [Value] )

Late Cut % Value =
SELECTEDVALUE ( 'Late Cut'[Late Cut %], 50 ) / 100

Late Orders (review scope) =
CALCULATE ( [Orders (review scope)], fact_orders[is_late] = 1 )

Orders Rescued (what-if) =
[Late Orders (review scope)] * [Late Cut % Value]

-- UPPER BOUND: assumes a rescued order is reviewed like today's on-time orders.
-- The rates come from the measures; none are typed.
Low Reviews Avoided (upper bound) =
[Orders Rescued (what-if)] * ( [Low Review % (Late)] - [Low Review % (On time)] )

Low Reviews Avoided % (upper bound) =
DIVIDE (
    [Low Reviews Avoided (upper bound)],
    CALCULATE ( [Orders (review scope)], fact_orders[is_low_review] = 1 )
)
```

`Late Cut` is a disconnected table driven by a single-select slicer. At 50% the verification script
computes 3,190.50 orders rescued and 1,695.83 fewer low reviews; Streamlit shows 3,190 / 1,696.
Power BI's `#,0` format is expected to round the half order up and show 3,191. That is
**unconfirmed** until the card is seen in Desktop. Label both cards "upper bound".

## Customers & RFM page (`sql/09_rfm_segments.sql`)

```dax
% of Customers (segment) =
DIVIDE ( [Customers], CALCULATE ( [Customers], ALL ( dim_customer ) ) )

% of Revenue (segment) =
DIVIDE ( [Revenue], CALCULATE ( [Revenue], ALL ( dim_customer ) ) )
```

Axis `dim_customer[segment]` (sort by `segment_order`). `[Customers]` and `[Revenue]` by segment
match `sql/09` as they are. Customers with no delivered order (segment "No delivered order")
return blank and drop out of the visual.

## Model page tables (copied, not recomputed)

`scripts/build_powerbi_data.py` copies these from `dashboard/data/` byte for byte (an integrity
check confirms it). They are built by `scripts/build_dashboard_data.py`; nothing is retrained.
Load them as standalone tables with no relationships.

| Table | Feeds |
|---|---|
| `model_metrics` | Cards: ROC-AUC and PR-AUC for LightGBM (stratified test and out-of-time), logistic regression and the no-skill baseline |
| `model_capture_curve` | Triage what-if: a `Flag %` parameter (1-100) selects the row where `top_frac = Flag % / 100`; cards show `recall_at_top`, `precision_at_top`, `lift_vs_random`; a line of `recall_at_top` vs `top_frac` is the gain curve |
| `shap_importance` | Bar: features ranked by `mean_abs_shap` |
| `shap_state_effect` | Bar: mean SHAP by customer state (states with 50+ test orders) |
| `model_curves` | Lines: ROC and PR curves (filter on `curve`), one series per `model` |
| `model_target_comparison` | Table: why low review was chosen over repeat purchase (positive rate, ROC-AUC, PR-AUC, precision in top 10%) |

```dax
-- New table (or Modeling > New parameter > Numeric range, 1 to 100, step 1, default 10)
Flag % = SELECTCOLUMNS ( GENERATESERIES ( 1, 100, 1 ), "Flag %", [Value] )

Flag % Value =
SELECTEDVALUE ( 'Flag %'[Flag %], 10 )

-- top_frac is stored as a fraction (0.01 ... 1.00). Compare whole percents, not
-- floating-point fractions. The VAR is evaluated once, outside the FILTER iteration.
Recall at Flag % =
VAR _f = [Flag % Value]
RETURN
    CALCULATE (
        MAX ( model_capture_curve[recall_at_top] ),
        FILTER ( ALL ( model_capture_curve[top_frac] ), ROUND ( model_capture_curve[top_frac] * 100, 0 ) = _f )
    )

Precision at Flag % =
VAR _f = [Flag % Value]
RETURN
    CALCULATE (
        MAX ( model_capture_curve[precision_at_top] ),
        FILTER ( ALL ( model_capture_curve[top_frac] ), ROUND ( model_capture_curve[top_frac] * 100, 0 ) = _f )
    )

Lift at Flag % =
VAR _f = [Flag % Value]
RETURN
    CALCULATE (
        MAX ( model_capture_curve[lift_vs_random] ),
        FILTER ( ALL ( model_capture_curve[top_frac] ), ROUND ( model_capture_curve[top_frac] * 100, 0 ) = _f )
    )

ROC-AUC (LightGBM, test) =
CALCULATE ( MAX ( model_metrics[roc_auc] ),
    model_metrics[model] = "LightGBM", model_metrics[evaluation] = "Stratified random split" )

PR-AUC (LightGBM, test) =
CALCULATE ( MAX ( model_metrics[pr_auc] ),
    model_metrics[model] = "LightGBM", model_metrics[evaluation] = "Stratified random split" )

-- The evaluation label embeds the cutoff date ("Out-of-time (train < 2018-05-01)").
ROC-AUC (LightGBM, out-of-time) =
CALCULATE ( MAX ( model_metrics[roc_auc] ),
    model_metrics[model] = "LightGBM", LEFT ( model_metrics[evaluation], 11 ) = "Out-of-time" )

PR-AUC (LightGBM, out-of-time) =
CALCULATE ( MAX ( model_metrics[pr_auc] ),
    model_metrics[model] = "LightGBM", LEFT ( model_metrics[evaluation], 11 ) = "Out-of-time" )
```
