-- Lead time by lane (seller state -> customer state), for promise and service-level
-- planning. There is no inventory data, so this is about delivery lead time and the
-- promised date, not safety stock.
--
-- Scope: delivered orders with a delivery date whose items all ship from ONE seller
-- state (an order spanning two seller states has no single lane and is left out).
-- delivery_days = purchase date to delivered date; promised_days = purchase date to the
-- estimated (promised) date. A fixed promise of P days is met when delivery_days <= P,
-- so pXX_delivery_days is the shortest promise that at least XX% of the lane's orders
-- met: the smallest d with share(delivery_days <= d) >= XX% (inverse CDF, via CUME_DIST).
-- Lanes with fewer than 30 orders are excluded.
WITH order_lane AS (
    SELECT order_id, MIN(seller_state) AS seller_state
    FROM order_items_enriched
    GROUP BY order_id
    HAVING COUNT(DISTINCT seller_state) = 1
),
o AS (
    SELECT
        l.seller_state,
        e.customer_state,
        e.delivery_days,
        DATE_DIFF('day', CAST(e.order_purchase_timestamp AS DATE),
                         CAST(e.order_estimated_delivery_date AS DATE)) AS promised_days,
        e.delay_days
    FROM orders_enriched e
    JOIN order_lane l ON l.order_id = e.order_id
    WHERE e.order_status = 'delivered'
      AND e.delay_days IS NOT NULL
),
ranked AS (
    SELECT
        *,
        CUME_DIST() OVER (PARTITION BY seller_state, customer_state ORDER BY delivery_days) AS cum_share
    FROM o
),
lanes AS (
    SELECT
        seller_state,
        customer_state,
        COUNT(*)                                                AS orders,
        MIN(delivery_days) FILTER (WHERE cum_share >= 0.50)     AS p50_delivery_days,
        MIN(delivery_days) FILTER (WHERE cum_share >= 0.90)     AS p90_delivery_days,
        MIN(delivery_days) FILTER (WHERE cum_share >= 0.95)     AS p95_delivery_days,
        AVG(promised_days)                                      AS avg_promised_days,
        AVG(CAST(delay_days <= 0 AS INT))                       AS on_time_today
    FROM ranked
    GROUP BY seller_state, customer_state
    HAVING COUNT(*) >= 30
)
SELECT
    l.seller_state,
    l.customer_state,
    l.seller_state || ' -> ' || l.customer_state                       AS lane,
    l.orders,
    l.p50_delivery_days,
    l.p90_delivery_days,
    l.p95_delivery_days,
    ROUND(l.avg_promised_days, 1)                                      AS avg_promised_days,
    ROUND(100.0 * l.on_time_today, 2)                                  AS on_time_pct_today,
    -- On-time rate if every order in the lane had been promised p90 / p95 days.
    ROUND(100.0 * AVG(CAST(o.delivery_days <= l.p90_delivery_days AS INT)), 2) AS on_time_pct_at_p90,
    ROUND(100.0 * AVG(CAST(o.delivery_days <= l.p95_delivery_days AS INT)), 2) AS on_time_pct_at_p95,
    -- Positive: the lane needs a longer promise than today's average to reach 90% / 95%.
    ROUND(l.p90_delivery_days - l.avg_promised_days, 1)                AS gap_p90_vs_avg_promise_days,
    ROUND(l.p95_delivery_days - l.avg_promised_days, 1)                AS gap_p95_vs_avg_promise_days
FROM lanes l
JOIN o ON o.seller_state = l.seller_state AND o.customer_state = l.customer_state
GROUP BY ALL
ORDER BY l.orders DESC;
