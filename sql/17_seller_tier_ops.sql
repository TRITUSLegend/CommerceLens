-- Do the sellers that carry the revenue also deliver the experience?
-- Top 20% of sellers by revenue vs the rest: revenue share, lateness, reviews.
-- Order-level metrics are attributed to every seller in the order.
WITH seller_rev AS (
    SELECT seller_id, SUM(price) AS revenue
    FROM order_items_enriched
    WHERE order_status = 'delivered'
    GROUP BY seller_id
),
tiers AS (
    SELECT
        seller_id,
        revenue,
        CASE WHEN PERCENT_RANK() OVER (ORDER BY revenue DESC) < 0.20
             THEN 'Top 20% sellers' ELSE 'Other 80% sellers' END AS seller_tier
    FROM seller_rev
),
seller_orders AS (
    SELECT DISTINCT oi.order_id, t.seller_tier
    FROM order_items_enriched oi
    JOIN tiers t ON t.seller_id = oi.seller_id
    WHERE oi.order_status = 'delivered'
)
SELECT
    t.seller_tier,
    t.sellers,
    t.revenue,
    ROUND(100.0 * t.revenue / SUM(t.revenue) OVER (), 2)       AS pct_of_revenue,
    x.orders,
    x.late_pct,
    x.avg_review,
    x.pct_low_review
FROM (
    SELECT seller_tier, COUNT(*) AS sellers, ROUND(SUM(revenue), 2) AS revenue
    FROM tiers GROUP BY seller_tier
) t
JOIN (
    SELECT
        so.seller_tier,
        COUNT(*)                                                AS orders,
        ROUND(100.0 * AVG(CAST(o.delay_days > 0 AS INT)), 2)    AS late_pct,
        ROUND(AVG(o.review_score), 3)                           AS avg_review,
        ROUND(100.0 * AVG(CAST(o.review_score <= 2 AS INT)), 2) AS pct_low_review
    FROM seller_orders so
    JOIN orders_enriched o ON o.order_id = so.order_id
    GROUP BY so.seller_tier
) x ON x.seller_tier = t.seller_tier
ORDER BY t.revenue DESC;
