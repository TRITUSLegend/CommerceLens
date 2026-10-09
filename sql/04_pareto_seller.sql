-- Revenue concentration by seller (delivered orders, item price).
WITH seller_revenue AS (
    SELECT
        seller_id,
        ANY_VALUE(seller_state)  AS seller_state,
        SUM(price)               AS revenue,
        COUNT(DISTINCT order_id) AS orders
    FROM order_items_enriched
    WHERE order_status = 'delivered'
    GROUP BY seller_id
)
SELECT
    ROW_NUMBER() OVER (ORDER BY revenue DESC)                  AS rank,
    seller_id,
    seller_state,
    ROUND(revenue, 2)                                          AS revenue,
    orders,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 4)           AS pct_of_revenue,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC ROWS UNBOUNDED PRECEDING)
                / SUM(revenue) OVER (), 2)                     AS cumulative_pct,
    ROUND(100.0 * ROW_NUMBER() OVER (ORDER BY revenue DESC)
                / COUNT(*) OVER (), 2)                         AS cumulative_pct_of_sellers
FROM seller_revenue
ORDER BY rank;
