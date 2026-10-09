-- Segment summary: size, value and repeat rate per RFM segment.
-- Requires 08_rfm_customers.sql to have been run on the connection.
SELECT
    segment,
    COUNT(*)                                                      AS customers,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)            AS pct_of_customers,
    ROUND(SUM(monetary), 2)                                       AS revenue,
    ROUND(100.0 * SUM(monetary) / SUM(SUM(monetary)) OVER (), 2)  AS pct_of_revenue,
    ROUND(AVG(monetary), 2)                                       AS avg_monetary,
    ROUND(MEDIAN(recency_days), 0)                                AS median_recency_days,
    ROUND(100.0 * AVG(CAST(is_repeat_buyer AS INT)), 2)           AS pct_repeat_buyers
FROM rfm_customers
GROUP BY segment
ORDER BY revenue DESC;
