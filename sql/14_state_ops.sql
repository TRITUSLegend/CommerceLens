-- Operational scorecard per customer state (delivered orders):
-- delivery speed, late rate, freight burden and satisfaction by region.
SELECT
    customer_state,
    COUNT(*)                                                   AS orders,
    ROUND(SUM(items_value), 2)                                 AS revenue,
    ROUND(AVG(delivery_days), 1)                               AS avg_delivery_days,
    ROUND(100.0 * AVG(CAST(delay_days > 0 AS INT)), 2)         AS late_pct,
    ROUND(100.0 * SUM(freight_value) / SUM(items_value), 2)    AS freight_pct_of_price,
    ROUND(AVG(review_score), 3)                                AS avg_review,
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)), 2)      AS pct_low_review
FROM orders_enriched
WHERE order_status = 'delivered'
  AND delay_days IS NOT NULL
GROUP BY customer_state
ORDER BY revenue DESC;
