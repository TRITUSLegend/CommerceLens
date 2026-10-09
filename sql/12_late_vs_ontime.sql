-- Late (delivered after the estimated date) vs on-time/early: satisfaction gap.
SELECT
    CASE WHEN delay_days > 0 THEN 'Late' ELSE 'On time or early' END AS delivery,
    COUNT(*)                                                  AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)        AS pct_of_orders,
    ROUND(AVG(review_score), 3)                               AS avg_review,
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)), 2)     AS pct_low_review,
    ROUND(100.0 * AVG(CAST(review_score = 5 AS INT)), 2)      AS pct_five_star,
    ROUND(AVG(delivery_days), 1)                              AS avg_delivery_days
FROM orders_enriched
WHERE order_status = 'delivered'
  AND delay_days IS NOT NULL
  AND review_score IS NOT NULL
GROUP BY 1
ORDER BY 1;
