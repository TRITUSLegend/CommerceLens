-- Customer-level RFM on delivered orders, keyed on customer_unique_id.
--
-- Frequency is heavily skewed: the vast majority of customers buy exactly once
-- (see 07_order_frequency.sql), so a 1-5 frequency quintile would be meaningless.
-- Segments are therefore built on Recency x Monetary quintiles, and Frequency is
-- kept only as a repeat-buyer flag.
--
-- Recency is measured from the day after the last purchase in the data, not
-- from today, because the dataset ends in 2018.
CREATE OR REPLACE VIEW rfm_customers AS
WITH base AS (
    SELECT
        customer_unique_id,
        MAX(order_purchase_timestamp) AS last_purchase,
        COUNT(*)                      AS frequency,
        SUM(items_value)              AS monetary
    FROM orders_enriched
    WHERE order_status = 'delivered'
    GROUP BY customer_unique_id
),
snapshot AS (
    SELECT MAX(last_purchase) + INTERVAL 1 DAY AS snapshot_date FROM base
),
scored AS (
    SELECT
        b.customer_unique_id,
        DATE_DIFF('day', b.last_purchase, s.snapshot_date) AS recency_days,
        b.frequency,
        b.monetary,
        -- Most recent customers get r_score 5; highest spenders get m_score 5.
        -- customer_unique_id breaks ties so quintile boundaries are reproducible.
        NTILE(5) OVER (ORDER BY b.last_purchase ASC, b.customer_unique_id) AS r_score,
        NTILE(5) OVER (ORDER BY b.monetary ASC, b.customer_unique_id)      AS m_score
    FROM base b
    CROSS JOIN snapshot s
)
SELECT
    *,
    frequency >= 2 AS is_repeat_buyer,
    CASE
        WHEN r_score >= 4 AND m_score >= 4 THEN 'Champions'
        WHEN r_score >= 4                  THEN 'Recent, low spend'
        WHEN r_score = 3  AND m_score >= 4 THEN 'Potential loyalists'
        WHEN r_score = 3                   THEN 'Needs attention'
        WHEN m_score >= 4                  THEN 'At risk, high value'
        ELSE                                    'Hibernating'
    END AS segment
FROM scored;
