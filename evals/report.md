# Eval scorecard

- **execution-match rate**: 61.1%
- behaviour (clarify/abort) rate: 0.0%
- valid-SQL rate: 100.0%
- avg retries: 0.15
- latency p50/p95: 9.9 / 27.4 ms
- avg cost: $0.011748

| id | category | passed | retries | valid_sql | $ |
|---|---|---|---|---|---|
| simple_count_orders | simple | ✅ | 0 | True | 0.0100 |
| simple_filter_status | simple | ✅ | 0 | True | 0.0101 |
| simple_distinct_categories | simple | ✅ | 0 | True | 0.0108 |
| agg_avg_order_value | aggregate | ✅ | 0 | True | 0.0106 |
| agg_sum_revenue | aggregate | ✅ | 0 | True | 0.0107 |
| group_orders_by_status | aggregate | ✅ | 0 | True | 0.0105 |
| join_revenue_by_category | join | ✅ | 0 | True | 0.0119 |
| join_top_sellers | multi_join | ❌ | 0 | True | 0.0131 |
| join_payment_methods | join | ✅ | 0 | True | 0.0120 |
| join_refunds_by_category | multi_join | ❌ | 3 | True | 0.0278 |
| time_orders_last_30d | time_window | ❌ | 0 | True | 0.0109 |
| time_monthly_revenue | time_window | ❌ | 0 | True | 0.0137 |
| ship_avg_delivery_by_courier | multi_join | ❌ | 0 | True | 0.0125 |
| ship_sla_breaches | time_window | ❌ | 0 | True | 0.0123 |
| cust_top_by_orders | join | ❌ | 0 | True | 0.0120 |
| prod_most_expensive | simple | ✅ | 0 | True | 0.0102 |
| agg_returned_rate | aggregate | ✅ | 0 | True | 0.0104 |
| join_revenue_by_state | multi_join | ✅ | 0 | True | 0.0127 |
| ambiguous_best_sellers | ambiguous | ❌ | 0 | False | 0.0128 |
| abort_unanswerable | failure | ❌ | 0 | False | 0.0000 |
