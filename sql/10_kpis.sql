-- Headline KPIs (delivered orders unless the column name says otherwise).
WITH delivered AS (
    SELECT * FROM orders_enriched WHERE order_status = 'delivered'
),
per_customer AS (
    SELECT customer_unique_id, COUNT(*) AS n_orders FROM delivered GROUP BY 1
)
SELECT
    (SELECT COUNT(*) FROM orders)                                        AS total_orders_all_statuses,
    (SELECT COUNT(*) FROM delivered)                                     AS delivered_orders,
    (SELECT ROUND(SUM(items_value), 2) FROM delivered)                   AS revenue,
    (SELECT ROUND(AVG(items_value), 2) FROM delivered)                   AS avg_order_value,
    (SELECT COUNT(*) FROM per_customer)                                  AS customers,
    (SELECT ROUND(100.0 * AVG(CAST(n_orders >= 2 AS INT)), 2)
       FROM per_customer)                                                AS repeat_customer_pct,
    (SELECT ROUND(AVG(review_score), 3) FROM delivered)                  AS avg_review_score,
    (SELECT ROUND(100.0 * AVG(CAST(delay_days > 0 AS INT)), 2)
       FROM delivered WHERE delay_days IS NOT NULL)                      AS late_delivery_pct,
    (SELECT CAST(MIN(order_purchase_timestamp) AS DATE) FROM orders)     AS first_order_date,
    (SELECT CAST(MAX(order_purchase_timestamp) AS DATE) FROM orders)     AS last_order_date;
