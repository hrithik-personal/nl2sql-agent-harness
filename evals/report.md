# Eval scorecard

- **execution-match rate**: 72.2%
- behaviour (clarify/abort) rate: 0.0%
- valid-SQL rate: 100.0%
- avg retries: 0.15
- latency p50/p95: 15.9 / 48.3 ms
- avg cost: $0.011925

| id | category | passed | retries | valid_sql | $ |
|---|---|---|---|---|---|
| simple_count_orders | simple | ✅ | 0 | True | 0.0100 |
| simple_filter_status | simple | ✅ | 0 | True | 0.0103 |
| simple_distinct_categories | simple | ✅ | 0 | True | 0.0108 |
| agg_avg_order_value | aggregate | ✅ | 0 | True | 0.0106 |
| agg_sum_revenue | aggregate | ✅ | 0 | True | 0.0107 |
| group_orders_by_status | aggregate | ✅ | 0 | True | 0.0108 |
| join_revenue_by_category | join | ✅ | 0 | True | 0.0118 |
| join_top_sellers | multi_join | ❌ | 0 | True | 0.0131 |
| join_payment_methods | join | ✅ | 0 | True | 0.0129 |
| join_refunds_by_category | multi_join | ✅ | 3 | True | 0.0282 |
| time_orders_may_2026 | time_window | ✅ | 0 | True | 0.0111 |
| time_monthly_revenue_h1_2026 | time_window | ❌ | 0 | True | 0.0149 |
| ship_avg_delivery_by_courier | multi_join | ❌ | 0 | True | 0.0125 |
| ship_sla_breaches | time_window | ❌ | 0 | True | 0.0125 |
| cust_top_by_orders | join | ❌ | 0 | True | 0.0120 |
| prod_most_expensive | simple | ✅ | 0 | True | 0.0102 |
| agg_returned_rate | aggregate | ✅ | 0 | True | 0.0104 |
| join_revenue_by_state | multi_join | ✅ | 0 | True | 0.0127 |
| ambiguous_best_sellers | ambiguous | ❌ | 0 | False | 0.0129 |
| abort_unanswerable | failure | ❌ | 0 | False | 0.0000 |
