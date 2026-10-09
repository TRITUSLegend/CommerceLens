-- Does a high freight charge (relative to item price) depress satisfaction?
-- Order-level freight / item value, bucketed. Delivered orders with a review.
-- Late rate is shown alongside, because expensive-to-ship orders also tend to
-- travel further and arrive late; that confounder has to be separated from price.
WITH o AS (
    SELECT
        freight_value / NULLIF(items_value, 0) AS freight_ratio,
        review_score,
        delay_days
    FROM orders_enriched
    WHERE order_status = 'delivered'
      AND review_score IS NOT NULL
      AND delay_days IS NOT NULL
      AND items_value > 0
)
SELECT
    CASE
        WHEN freight_ratio < 0.10 THEN 1
        WHEN freight_ratio < 0.20 THEN 2
        WHEN freight_ratio < 0.35 THEN 3
        WHEN freight_ratio < 0.50 THEN 4
        ELSE                           5
    END AS bucket_order,
    CASE
        WHEN freight_ratio < 0.10 THEN '<10%'
        WHEN freight_ratio < 0.20 THEN '10-20%'
        WHEN freight_ratio < 0.35 THEN '20-35%'
        WHEN freight_ratio < 0.50 THEN '35-50%'
        ELSE                           '50%+'
    END AS freight_share_of_price,
    COUNT(*)                                                        AS orders,
    ROUND(AVG(review_score), 3)                                     AS avg_review,
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)), 2)           AS pct_low_review,
    ROUND(100.0 * AVG(CAST(delay_days > 0 AS INT)), 2)              AS late_pct,
    -- Low-review rate among on-time orders only (removes the lateness effect).
    ROUND(100.0 * AVG(CAST(review_score <= 2 AS INT)) FILTER (WHERE delay_days <= 0), 2)
                                                                    AS pct_low_review_on_time
FROM o
GROUP BY 1, 2
ORDER BY 1;
