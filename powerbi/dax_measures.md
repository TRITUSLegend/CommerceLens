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

Status = IF ( [Diff] <= [Tolerance], "Match", "Mismatch" )

Checks Passed = COUNTROWS ( FILTER ( recon_sql, [Status] = "Match" ) )

Checks Total = COUNTROWS ( recon_sql )
```

## Values the SQL layer produced on the real dataset (from the committed `dashboard/data/*.parquet`)

After you run the export on the real CSVs, `recon_sql` must show these. Power BI's `DAX Value`
column should reproduce every one.

| Metric | SQL value |
|---|---|
| Total orders (all statuses) | 99,441 |
| Delivered orders | 96,478 |
| Revenue (R$) | 13,221,498.11 |
| Average order value (R$) | 137.04 |
| Customers (1+ delivered order) | 93,358 |
| Repeat customers (%) | 3.00 |
| Average review score | 4.156 |
| Late (%) - all delivered orders | 6.77 |
| Late (%) - reviewed orders only | 6.66 |
| Low-review (%) - late orders | 62.42 |
| Low-review (%) - on-time orders | 9.27 |
| Late (%) - RJ | 12.11 |
| Late (%) - SP | 4.49 |
| Champions - share of revenue (%) | 31.57 |
