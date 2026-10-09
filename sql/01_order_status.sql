-- Order count and share by final order_status.
SELECT
    order_status,
    COUNT(*)                                           AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_orders
FROM orders
GROUP BY order_status
ORDER BY orders DESC;
