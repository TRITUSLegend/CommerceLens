-- Repeat-purchase target: one row per customer_unique_id, keyed to their FIRST
-- delivered order. returned_180d = placed another delivered order within 180
-- days. Same right-censoring guard as 16_first_order_vs_repeat.sql: only
-- customers with a full 180-day window before the data ends are included.
WITH delivered AS (
    SELECT
        customer_unique_id,
        order_id,
        order_purchase_timestamp,
        ROW_NUMBER() OVER w                   AS order_seq,
        LEAD(order_purchase_timestamp) OVER w AS next_purchase
    FROM orders_enriched
    WHERE order_status = 'delivered'
    WINDOW w AS (PARTITION BY customer_unique_id ORDER BY order_purchase_timestamp, order_id)
)
SELECT
    customer_unique_id,
    order_id AS first_order_id,
    CAST(COALESCE(next_purchase <= order_purchase_timestamp + INTERVAL 180 DAY, FALSE) AS INT) AS returned_180d
FROM delivered
WHERE order_seq = 1
  AND order_purchase_timestamp
      <= (SELECT MAX(order_purchase_timestamp) FROM delivered) - INTERVAL 180 DAY;
