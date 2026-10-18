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
