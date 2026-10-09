-- Model features, one row per delivered order, using ONLY information that is
-- known at the moment the order is placed (prediction time = purchase).
--
-- Deliberately EXCLUDED to avoid target leakage: actual delivery / carrier dates,
-- delay_days, order_approved_at, and anything from the review itself.
-- The review score is carried only as the target (low_review).
-- Seller and customer history features count strictly EARLIER orders only.
CREATE OR REPLACE VIEW order_features AS
WITH zip_geo AS (
    -- Average coordinates per zip prefix; drop points outside Brazil's bounding box.
    SELECT
        geolocation_zip_code_prefix AS zip,
        AVG(geolocation_lat)        AS lat,
        AVG(geolocation_lng)        AS lng
    FROM geolocation
    WHERE geolocation_lat BETWEEN -34 AND 6
      AND geolocation_lng BETWEEN -74 AND -34
    GROUP BY 1
),
items AS (
    SELECT
        oi.order_id,
        oi.order_item_id,
        oi.product_id,
        oi.seller_id,
        oi.price,
        COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS category,
        p.product_weight_g,
        p.product_length_cm * p.product_height_cm * p.product_width_cm AS volume_cm3,
        p.product_photos_qty,
        p.product_description_lenght AS description_length
    FROM order_items oi
    LEFT JOIN products p             ON p.product_id = oi.product_id
    LEFT JOIN category_translation t ON t.product_category_name = p.product_category_name
),
main_item AS (
    -- The most expensive item defines the order's main category and seller.
    SELECT order_id, category AS main_category, seller_id AS main_seller_id
    FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY price DESC, order_item_id) AS rn
        FROM items
    )
    WHERE rn = 1
),
item_agg AS (
    SELECT
        order_id,
        COUNT(DISTINCT product_id)  AS n_products,
        SUM(product_weight_g)       AS total_weight_g,
        MAX(volume_cm3)             AS max_volume_cm3,
        AVG(product_photos_qty)     AS avg_photos,
        AVG(description_length)     AS avg_description_length
    FROM items
    GROUP BY order_id
),
pay AS (
    SELECT
        order_id,
        ARG_MAX(payment_type, payment_value) AS payment_type,
        MAX(payment_installments)            AS installments,
        COUNT(DISTINCT payment_type)         AS n_payment_types
    FROM payments
    GROUP BY order_id
),
seller_orders AS (
    SELECT DISTINCT oi.seller_id, o.order_id, o.order_purchase_timestamp
    FROM order_items oi
    JOIN orders o ON o.order_id = oi.order_id
),
seller_history AS (
    -- Orders the seller had received before this one (any status).
    SELECT
        seller_id,
        order_id,
        COUNT(*) OVER (
            PARTITION BY seller_id ORDER BY order_purchase_timestamp, order_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS seller_prior_orders
    FROM seller_orders
),
customer_history AS (
    -- Orders this person (customer_unique_id) had placed before this one.
    SELECT
        order_id,
        COUNT(*) OVER (
            PARTITION BY customer_unique_id ORDER BY order_purchase_timestamp, order_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS customer_prior_orders
    FROM orders_enriched
)
SELECT
    o.order_id,
    o.customer_unique_id,
    o.order_purchase_timestamp,
    -- Order value and freight
    o.items_value,
    o.freight_value,
    o.freight_value / NULLIF(o.items_value, 0)                      AS freight_ratio,
    o.n_items,
    ia.n_products,
    o.n_sellers,
    -- Promise made at checkout
    DATE_DIFF('day', CAST(o.order_purchase_timestamp AS DATE),
                     CAST(o.order_estimated_delivery_date AS DATE)) AS promised_days,
    -- Timing
    MONTH(o.order_purchase_timestamp)                               AS purchase_month,
    DAYOFWEEK(o.order_purchase_timestamp)                           AS purchase_dow,
    HOUR(o.order_purchase_timestamp)                                AS purchase_hour,
    -- Product
    mi.main_category,
    ia.total_weight_g,
    ia.max_volume_cm3,
    ia.avg_photos,
    ia.avg_description_length,
    -- Payment
    py.payment_type,
    py.installments,
    py.n_payment_types,
    -- Geography
    o.customer_state,
    s.seller_state,
    CAST(o.customer_state = s.seller_state AS INT)                  AS same_state,
    -- Haversine distance seller -> customer (km)
    2 * 6371 * ASIN(SQRT(
        POWER(SIN(RADIANS(cg.lat - sg.lat) / 2), 2)
        + COS(RADIANS(sg.lat)) * COS(RADIANS(cg.lat))
        * POWER(SIN(RADIANS(cg.lng - sg.lng) / 2), 2)
    ))                                                              AS distance_km,
    -- History known at purchase time
    sh.seller_prior_orders,
    ch.customer_prior_orders,
    -- Target (NOT a feature)
    o.review_score,
    CAST(o.review_score <= 2 AS INT)                                AS low_review
FROM orders_enriched o
JOIN orders ro                ON ro.order_id = o.order_id
JOIN customers c              ON c.customer_id = ro.customer_id
LEFT JOIN main_item mi        ON mi.order_id = o.order_id
LEFT JOIN item_agg ia         ON ia.order_id = o.order_id
LEFT JOIN pay py              ON py.order_id = o.order_id
LEFT JOIN sellers s           ON s.seller_id = mi.main_seller_id
LEFT JOIN zip_geo cg          ON cg.zip = c.customer_zip_code_prefix
LEFT JOIN zip_geo sg          ON sg.zip = s.seller_zip_code_prefix
LEFT JOIN seller_history sh   ON sh.seller_id = mi.main_seller_id AND sh.order_id = o.order_id
LEFT JOIN customer_history ch ON ch.order_id = o.order_id
WHERE o.order_status = 'delivered';
