-- How many delivered orders does each customer (customer_unique_id) place?
-- Evidence for the one-time-buyer skew that shapes RFM and the Layer 3 model choice.
WITH per_customer AS (
    SELECT customer_unique_id, COUNT(*) AS n_orders
    FROM orders_enriched
    WHERE order_status = 'delivered'
    GROUP BY customer_unique_id
)
SELECT
    CASE WHEN n_orders >= 4 THEN '4+' ELSE CAST(n_orders AS VARCHAR) END AS orders_per_customer,
    COUNT(*)                                                             AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)                   AS pct_of_customers
FROM per_customer
GROUP BY 1
ORDER BY 1;
