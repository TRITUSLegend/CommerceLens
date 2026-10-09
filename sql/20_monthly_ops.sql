-- Monthly operations health: delivery speed, lateness and satisfaction by
-- purchase month (delivered orders). Same < 500-order edge flag as 06_monthly_trend.sql.
SELECT
    CAST(DATE_TRUNC('month', order_purchase_timestamp) AS DATE)  AS month,
    COUNT(*)                                                     AS orders,
    ROUND(AVG(delivery_days), 2)                                 AS avg_delivery_days,
    ROUND(100.0 * AVG(CAST(delay_days > 0 AS INT)), 2)           AS late_pct,
    ROUND(AVG(review_score), 3)                                  AS avg_review,
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)), 2)        AS pct_low_review,
    COUNT(*) < 500                                               AS is_partial_edge
FROM orders_enriched
WHERE order_status = 'delivered'
GROUP BY 1
ORDER BY 1;
