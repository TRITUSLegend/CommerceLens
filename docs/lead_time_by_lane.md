# Lead time by lane (service-level planning)

> **Status: exploratory extension (Stage 6).** Not yet part of the README findings and not yet on
> the author's resume. The numbers below are printed by the code; the interpretation has not been
> reviewed.

**Question:** for each delivery lane (seller state → customer state), how long does delivery
actually take, and what promised delivery time would have been met for 90% or 95% of orders,
compared with what Olist promises today?

This is lead-time and promise (service-level) planning. The dataset has no inventory, stock or
warehouse data, so it says nothing about safety stock or replenishment.

## Method (`sql/22_lane_lead_time.sql`, exported as `powerbi/data/lane_lead_time.parquet`)

- **Orders:** delivered, with a delivery date (the 96,470 orders behind the 6.77% late rate), whose
  items all ship from one seller state. The 509 orders with sellers in two or more states have no
  single lane and are left out.
- **Lane:** seller state → customer state. Lanes with fewer than 30 orders are excluded, leaving
  124 lanes and 93,796 orders.
- **Delivery days:** purchase date to delivered date. **Promised days:** purchase date to the
  estimated delivery date.
- **P50 / P90 / P95:** the smallest number of days `d` such that at least 50% / 90% / 95% of the
  lane's orders arrived within `d` days. A fixed promise of P90 days would therefore have been met
  for at least 90% of the lane's orders (the table's `on_time_pct_at_p90` column shows the exact
  rate, which is at least 90.0% in every lane).
- **Gap:** P95 minus today's average promise. Positive means a 95% service level needs a longer
  promise than the lane gets today; negative means today's average promise already covers it.

`scripts/verify_powerbi_measures.py` (section E) re-derives every lane in pandas from the star
schema without reusing the SQL, and all 993 values match.

## Results

Highest-volume lanes:

| lane | orders | p50_delivery_days | p90_delivery_days | p95_delivery_days | avg_promised_days | on_time_pct_today | gap_p95_vs_avg_promise_days |
|---|---|---|---|---|---|---|---|
| SP -> SP | 30,646 | 7 | 14 | 18 | 17.9 | 95.34 | 0.1 |
| SP -> RJ | 8,128 | 13 | 31 | 40 | 27 | 85.83 | 13 |
| SP -> MG | 7,413 | 11 | 21 | 25 | 25 | 94.71 | 0 |
| SP -> RS | 3,579 | 14 | 27 | 34 | 30.3 | 93.35 | 3.7 |
| SP -> PR | 3,110 | 11 | 21 | 26 | 25.8 | 95.56 | 0.2 |
| PR -> SP | 2,888 | 10 | 19 | 22 | 26.2 | 96.88 | -4.2 |
| MG -> SP | 2,509 | 9 | 18 | 23 | 24.4 | 96.37 | -1.4 |
| SP -> SC | 2,323 | 14 | 27 | 33 | 26.7 | 90.44 | 6.3 |
| SP -> BA | 2,303 | 18 | 32 | 37 | 30.5 | 87.1 | 6.5 |
| MG -> MG | 1,510 | 7 | 15 | 19 | 21.1 | 97.48 | -2.1 |

Lanes with 200+ orders and the largest P95 gap:

| lane | orders | p50_delivery_days | p90_delivery_days | p95_delivery_days | avg_promised_days | on_time_pct_today | gap_p95_vs_avg_promise_days |
|---|---|---|---|---|---|---|---|
| SP -> SE | 207 | 18 | 37 | 46 | 30.7 | 83.57 | 15.3 |
| SP -> AL | 255 | 23 | 41 | 46 | 32.9 | 76.08 | 13.1 |
| SP -> RJ | 8,128 | 13 | 31 | 40 | 27 | 85.83 | 13 |
| PR -> RJ | 956 | 14 | 34 | 43 | 30.3 | 87.76 | 12.7 |
| SP -> CE | 967 | 18 | 34 | 44 | 32.1 | 86.25 | 11.9 |
| SP -> MA | 490 | 20 | 35 | 43 | 31.3 | 81.02 | 11.7 |
| SP -> PI | 329 | 17 | 33 | 41 | 30.8 | 83.59 | 10.2 |
| SP -> RN | 331 | 18 | 34 | 42 | 33.3 | 90.03 | 8.7 |

Across all 124 lanes, 68 (68,994 orders) need a longer promise than today's average to reach
95%, and 30 (19,795 orders) to reach 90%.

## Reading it

- **SP → RJ** is the lane where the most volume sits behind a short promise: 8,128 orders, 85.83%
  on time today, and a 95% service level would need a 40-day promise against a 27-day average.
  This matches the regional finding (RJ late 12.11% vs SP 4.49%).
- The North-East lanes from SP (SE, AL, CE, MA, PI) have both the longest lead times and the
  largest gaps, the same states the README flags as running at 2x+ the national late rate.
- Lanes with a negative gap (for example PR → SP, MG → SP) already promise more time than 95% of
  orders need.

What this does **not** show: whether a longer promise would cost sales (there is no traffic or
conversion data), or why a lane is slow (carrier, distance, seller handling time are not separated).
A widened promise is one option next to fixing the lane itself, which README finding 2 recommends
first.

## Power BI

Optional page "Lead time (exploratory)": table of `lane_lead_time` (all columns), a bar chart of
`gap_p95_vs_avg_promise_days` by `lane` with a visual filter `orders >= 200`, and slicers on
`seller_state` and `customer_state`. The table is standalone (no relationships).
