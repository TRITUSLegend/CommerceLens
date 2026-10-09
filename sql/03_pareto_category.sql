-- Revenue concentration by product category (delivered orders, item price).
-- Running window SUM gives the cumulative share -> Pareto curve.
WITH category_revenue AS (
    SELECT
        category,
        SUM(price)               AS revenue,
        COUNT(DISTINCT order_id) AS orders
    FROM order_items_enriched
    WHERE order_status = 'delivered'
    GROUP BY category
)
SELECT
    ROW_NUMBER() OVER (ORDER BY revenue DESC)                  AS rank,
    category,
    ROUND(revenue, 2)                                          AS revenue,
    orders,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)           AS pct_of_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
                / SUM(revenue) OVER (), 2)                     AS cumulative_pct,
    ROUND(100.0 * ROW_NUMBER() OVER (ORDER BY revenue DESC)
                / COUNT(*) OVER (), 2)                         AS cumulative_pct_of_categories
FROM category_revenue
ORDER BY rank;
