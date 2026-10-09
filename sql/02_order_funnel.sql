-- Fulfilment funnel built from lifecycle timestamps (not just final status):
-- how many orders reach each stage, and conversion from the previous stage.
WITH stages AS (
    SELECT 1 AS stage_order, 'Purchased' AS stage, COUNT(*) AS orders
    FROM orders
    UNION ALL
    SELECT 2, 'Payment approved', COUNT(*)
    FROM orders WHERE order_approved_at IS NOT NULL
    UNION ALL
    SELECT 3, 'Handed to carrier', COUNT(*)
    FROM orders WHERE order_delivered_carrier_date IS NOT NULL
    UNION ALL
    SELECT 4, 'Delivered to customer', COUNT(*)
    FROM orders
    WHERE order_status = 'delivered' AND order_delivered_customer_date IS NOT NULL
)
SELECT
    stage_order,
    stage,
    orders,
    ROUND(100.0 * orders / FIRST_VALUE(orders) OVER (ORDER BY stage_order), 2) AS pct_of_purchased,
    ROUND(100.0 * orders / LAG(orders) OVER (ORDER BY stage_order), 2)         AS pct_of_previous_stage
FROM stages
ORDER BY stage_order;
