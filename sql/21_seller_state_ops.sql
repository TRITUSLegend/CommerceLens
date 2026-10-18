-- Late and low-review rates by SELLER state (where the order shipped from).
-- Same attribution rule as 17_seller_tier_ops.sql: an order counts once for every
-- seller state that shipped at least one of its items, so an order with sellers in
-- two states appears under both and the rows do not sum to the national total.
-- Scope matches 14_state_ops.sql: delivered orders with a delivery date; the
-- low-review rate uses the orders in that scope that have a review.
WITH seller_state_orders AS (
    SELECT DISTINCT order_id, seller_state
    FROM order_items_enriched
    WHERE order_status = 'delivered'
)
SELECT
    so.seller_state,
    COUNT(*)                                                   AS orders,
    ROUND(100.0 * AVG(CAST(o.delay_days > 0 AS INT)), 2)       AS late_pct,
    COUNT(o.review_score)                                      AS reviewed_orders,
    ROUND(100.0 * AVG(CAST(o.review_score <= 2 AS INT)), 2)    AS pct_low_review
FROM seller_state_orders so
JOIN orders_enriched o ON o.order_id = so.order_id
WHERE o.delay_days IS NOT NULL
GROUP BY so.seller_state
ORDER BY orders DESC;
