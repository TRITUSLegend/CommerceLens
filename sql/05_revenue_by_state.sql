-- Revenue, customers and average order value by customer state (delivered orders).
WITH state_orders AS (
    SELECT
        customer_state,
        COUNT(*)                           AS orders,
        COUNT(DISTINCT customer_unique_id) AS customers,
        SUM(items_value)                   AS revenue
    FROM orders_enriched
    WHERE order_status = 'delivered'
    GROUP BY customer_state
)
SELECT
    ROW_NUMBER() OVER (ORDER BY revenue DESC)                  AS rank,
    customer_state,
    orders,
    customers,
    ROUND(revenue, 2)                                          AS revenue,
    ROUND(revenue / orders, 2)                                 AS avg_order_value,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)           AS pct_of_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
                / SUM(revenue) OVER (), 2)                     AS cumulative_pct
FROM state_orders
ORDER BY rank;
