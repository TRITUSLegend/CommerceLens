-- Does the FIRST order experience predict whether a customer comes back?
--
-- For each customer_unique_id, take their first delivered order and flag whether
-- they placed another delivered order within 180 days of it (LEAD gives the
-- next order's timestamp).
-- Right-censoring guard: only customers whose first order is at least 180 days
-- before the last purchase in the data are included, so everyone has had the
-- same full window to return.
WITH delivered AS (
    SELECT
        customer_unique_id,
        order_purchase_timestamp,
        delay_days,
        review_score,
        ROW_NUMBER() OVER w                     AS order_seq,
        LEAD(order_purchase_timestamp) OVER w   AS next_purchase
    FROM orders_enriched
    WHERE order_status = 'delivered'
    WINDOW w AS (PARTITION BY customer_unique_id ORDER BY order_purchase_timestamp, order_id)
),
eligible AS (
    SELECT
        delay_days,
        review_score,
        COALESCE(next_purchase <= order_purchase_timestamp + INTERVAL 180 DAY, FALSE) AS returned_180d
    FROM delivered
    WHERE order_seq = 1
      AND order_purchase_timestamp
          <= (SELECT MAX(order_purchase_timestamp) FROM delivered) - INTERVAL 180 DAY
)
SELECT 'First order delivery' AS dimension,
       CASE WHEN delay_days > 0 THEN 'Late' ELSE 'On time or early' END AS value,
       COUNT(*)                                          AS customers,
       SUM(CAST(returned_180d AS INT))                   AS returned,
       ROUND(100.0 * AVG(CAST(returned_180d AS INT)), 3) AS repeat_rate_180d_pct
FROM eligible
WHERE delay_days IS NOT NULL
GROUP BY 1, 2
UNION ALL
SELECT 'First order review',
       CASE WHEN review_score <= 2 THEN '1-2 (low)'
            WHEN review_score = 3  THEN '3'
            ELSE '4-5 (high)' END,
       COUNT(*),
       SUM(CAST(returned_180d AS INT)),
       ROUND(100.0 * AVG(CAST(returned_180d AS INT)), 3)
FROM eligible
WHERE review_score IS NOT NULL
GROUP BY 1, 2
UNION ALL
SELECT 'All eligible customers', 'All',
       COUNT(*),
       SUM(CAST(returned_180d AS INT)),
       ROUND(100.0 * AVG(CAST(returned_180d AS INT)), 3)
FROM eligible
ORDER BY 1, 2;
