-- Base views shared by every analysis layer.
--
-- Customer identity: Olist issues a NEW customer_id for every order, so the same
-- person appears under many customer_ids. customer_unique_id is the stable
-- per-person key, so all customer-level work (RFM, repeat purchase) uses it.
--
-- Revenue definition: item price (GMV excluding freight) from order_items.
-- Freight is kept as a separate column so Layer 2 can analyse it on its own.

-- One row per order item, with category (English), seller + customer geography.
CREATE OR REPLACE VIEW order_items_enriched AS
SELECT
    oi.order_id,
    oi.order_item_id,
    oi.product_id,
    oi.seller_id,
    oi.price,
    oi.freight_value,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
    p.product_weight_g,
    s.seller_state,
    c.customer_unique_id,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp
FROM order_items oi
JOIN orders o                    ON o.order_id = oi.order_id
JOIN customers c                 ON c.customer_id = o.customer_id
LEFT JOIN products p             ON p.product_id = oi.product_id
LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
LEFT JOIN sellers s              ON s.seller_id = oi.seller_id;

-- Some orders carry more than one review; keep the most recently answered one.
CREATE OR REPLACE VIEW order_reviews_latest AS
SELECT order_id, review_score, review_creation_date
FROM (
    SELECT
        order_id,
        review_score,
        review_creation_date,
        ROW_NUMBER() OVER (
            PARTITION BY order_id
            ORDER BY review_answer_timestamp DESC, review_creation_date DESC
        ) AS rn
    FROM reviews
)
WHERE rn = 1;

-- One row per order: value, freight, delivery timing and review.
CREATE OR REPLACE VIEW orders_enriched AS
WITH item_totals AS (
    SELECT
        order_id,
        SUM(price)                AS items_value,
        SUM(freight_value)        AS freight_value,
        COUNT(*)                  AS n_items,
        COUNT(DISTINCT seller_id) AS n_sellers
    FROM order_items
    GROUP BY order_id
)
SELECT
    o.order_id,
    c.customer_unique_id,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,
    it.items_value,
    it.freight_value,
    it.n_items,
    it.n_sellers,
    r.review_score,
    -- Positive = delivered after the promised date (days late); negative = early.
    DATE_DIFF('day', CAST(o.order_estimated_delivery_date AS DATE),
                     CAST(o.order_delivered_customer_date AS DATE)) AS delay_days,
    DATE_DIFF('day', CAST(o.order_purchase_timestamp AS DATE),
                     CAST(o.order_delivered_customer_date AS DATE)) AS delivery_days
FROM orders o
JOIN customers c                 ON c.customer_id = o.customer_id
LEFT JOIN item_totals it         ON it.order_id = o.order_id
LEFT JOIN order_reviews_latest r ON r.order_id = o.order_id;
