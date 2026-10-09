-- Review score by delivery delay (actual minus estimated delivery date).
-- Delivered orders that have both a delivery date and a review.
WITH d AS (
    SELECT
        delay_days,
        review_score,
        CASE
            WHEN delay_days <= -15 THEN '15+ days early'
            WHEN delay_days <= -8  THEN '8-14 days early'
            WHEN delay_days <= -1  THEN '1-7 days early'
            WHEN delay_days = 0    THEN 'On estimated day'
            WHEN delay_days <= 3   THEN '1-3 days late'
            WHEN delay_days <= 7   THEN '4-7 days late'
            WHEN delay_days <= 14  THEN '8-14 days late'
            ELSE                        '15+ days late'
        END AS delay_bucket,
        CASE
            WHEN delay_days <= -15 THEN 1
            WHEN delay_days <= -8  THEN 2
            WHEN delay_days <= -1  THEN 3
            WHEN delay_days = 0    THEN 4
            WHEN delay_days <= 3   THEN 5
            WHEN delay_days <= 7   THEN 6
            WHEN delay_days <= 14  THEN 7
            ELSE                        8
        END AS bucket_order
    FROM orders_enriched
    WHERE order_status = 'delivered'
      AND delay_days IS NOT NULL
      AND review_score IS NOT NULL
)
SELECT
    bucket_order,
    delay_bucket,
    COUNT(*)                                                  AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)        AS pct_of_orders,
    ROUND(AVG(review_score), 3)                               AS avg_review,
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)), 2)     AS pct_low_review,
    ROUND(100.0 * AVG(CAST(review_score = 5 AS INT)), 2)      AS pct_five_star
FROM d
GROUP BY bucket_order, delay_bucket
ORDER BY bucket_order;
