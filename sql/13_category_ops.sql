-- Operational scorecard per product category (delivered orders):
-- revenue, freight as % of item price, late-delivery rate and satisfaction.
-- An order's review/delay is attributed to every category in that order
-- (multi-category orders are rare). Categories with < 300 orders are excluded
-- so rates are not driven by small samples.
WITH cat_orders AS (
    SELECT DISTINCT order_id, category
    FROM order_items_enriched
    WHERE order_status = 'delivered'
),
cat_items AS (
    SELECT
        category,
        SUM(price)         AS revenue,
        SUM(freight_value) AS freight,
        COUNT(*)           AS items
    FROM order_items_enriched
    WHERE order_status = 'delivered'
    GROUP BY category
),
cat_experience AS (
    SELECT
        co.category,
        COUNT(*)                                                       AS orders,
        AVG(CAST(o.delay_days > 0 AS INT))                             AS late_rate,
        AVG(o.delivery_days)                                           AS avg_delivery_days,
        AVG(o.review_score)                                            AS avg_review,
        AVG(CAST(o.review_score <= 2 AS INT))                          AS low_review_rate
    FROM cat_orders co
    JOIN orders_enriched o ON o.order_id = co.order_id
    GROUP BY co.category
)
SELECT
    ci.category,
    ce.orders,
    ROUND(ci.revenue, 2)                                          AS revenue,
    ROUND(100.0 * ci.revenue / SUM(ci.revenue) OVER (), 2)        AS pct_of_revenue,
    ROUND(ci.revenue / ci.items, 2)                               AS avg_item_price,
    ROUND(100.0 * ci.freight / ci.revenue, 2)                     AS freight_pct_of_price,
    ROUND(100.0 * ce.late_rate, 2)                                AS late_pct,
    ROUND(ce.avg_delivery_days, 1)                                AS avg_delivery_days,
    ROUND(ce.avg_review, 3)                                       AS avg_review,
    ROUND(100.0 * ce.low_review_rate, 2)                          AS pct_low_review
FROM cat_items ci
JOIN cat_experience ce ON ce.category = ci.category
WHERE ce.orders >= 300
ORDER BY revenue DESC;
