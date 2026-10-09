-- Monthly revenue, orders and AOV with month-over-month growth (LAG).
-- Grouped by purchase month of delivered orders. The first months (late 2016)
-- and the final months (late 2018) are sparse dataset edges; is_partial_edge
-- flags months with < 500 orders so trend reads can exclude them.
WITH monthly AS (
    SELECT
        DATE_TRUNC('month', order_purchase_timestamp) AS month,
        COUNT(*)                                      AS orders,
        SUM(items_value)                              AS revenue
    FROM orders_enriched
    WHERE order_status = 'delivered'
    GROUP BY 1
)
SELECT
    CAST(month AS DATE)                                                  AS month,
    orders,
    ROUND(revenue, 2)                                                    AS revenue,
    ROUND(revenue / orders, 2)                                           AS avg_order_value,
    -- MoM growth is meaningless when the previous month is a sparse edge month.
    CASE WHEN LAG(orders) OVER (ORDER BY month) >= 500
         THEN ROUND(100.0 * (revenue / LAG(revenue) OVER (ORDER BY month) - 1), 2)
    END                                                                  AS revenue_mom_pct,
    orders < 500                                                         AS is_partial_edge
FROM monthly
ORDER BY month;
