# Agent Evaluation Report

- Generated: 2026-06-05T16:19:00.947491Z
- Pairs evaluated: **30**
- Threshold: 60%
- Verdict: **pass**

## Aggregate metrics

| Metric | Value |
| --- | --- |
| pass_rate | 76.7% |
| tool_accuracy | 70.0% |
| avg_kw_recall | 86.7% |
| avg_latency_s | 19.16 |
| failure_rate | 0.0% |

## Per-question results

| # | Pass | Tool | Tool match | KW recall | Latency | Question |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FAIL | sql_query | False | 100% | 9.3s | How many anomalies are in 路氹城區? |
| 2 | FAIL | sql_query | False | 50% | 12.0s | What are the top 5 highest-scoring anomalies? |
| 3 | PASS | query_anomalies | True | 100% | 13.5s | Show me anomalies in 路氹城區 |
| 4 | FAIL | get_anomaly_stats | False | 100% | 9.6s | What are the anomaly statistics for 澳門低區? |
| 5 | PASS | get_data_overview | True | 100% | 8.1s | Give me an overview of the data |
| 6 | PASS | query_meters | True | 100% | 9.6s | How many residential meters do we have? |
| 7 | PASS | get_predictions | True | 100% | 6.5s | Predict next week consumption for meter 753832 |
| 8 | PASS | get_predictions | True | 100% | 14.1s | Show predictions for a building |
| 9 | PASS | query_consumption | True | 100% | 23.0s | What is the weekly trend? |
| 10 | PASS | query_rank_changes | True | 100% | 16.8s | Which meters have been in the top 20 the longest? |
| 11 | PASS | query_monthly_diff | True | 100% | 24.6s | Show me the non-revenue water situation |
| 12 | FAIL | query_consumption | True | 0% | 20.0s | Compare January and February consumption |
| 13 | PASS | generate_chart | True | 100% | 22.2s | Draw a trend chart for 路氹城區 |
| 14 | FAIL | analyze_anomaly | False | 100% | 88.7s | Investigate meter 753832 anomalies |
| 15 | FAIL | generate_report | False | 0% | 19.0s | Generate a 路氹城區 monthly report |
| 16 | PASS | sql_query | True | 100% | 18.7s | What is the total daily consumption by DMA? |
| 17 | PASS | sql_query | True | 50% | 25.6s | Top 5 meters by total consumption |
| 18 | PASS | sql_query | True | 100% | 14.9s | What is the average anomaly score by DMA? |
| 19 | PASS | list_tables_tool | True | 100% | 8.4s | What tables are available? |
| 20 | PASS | get_table_schema_tool | True | 100% | 8.2s | What columns does the anomalies table have? |
| 21 | PASS | query_consumption | True | 100% | 20.8s | Show me daily consumption data |
| 22 | PASS | query_meters | True | 100% | 14.3s | List all meters in 路氹城區 |
| 23 | PASS | query_anomalies | True | 100% | 13.4s | Show me watch anomalies |
| 24 | PASS | query_consumption | True | 100% | 40.7s | Compare 澳門低區 and 路氹城區 consumption |
| 25 | FAIL | generate_report | False | 0% | 6.2s | Generate a comprehensive report |
| 26 | PASS |  | False | 100% | 8.6s | 氹仔漏水 |
| 27 | PASS |  | False | 100% | 6.9s | 上周水损情况 |
| 28 | PASS |  | False | 100% | 62.4s | 氹仔的 NRW |
| 29 | PASS | query_data_quality | True | 100% | 12.7s | Is the data accurate? Any dropped records? |
| 30 | PASS | query_data_quality | True | 100% | 15.9s | 数据准不准？有没有数据问题？ |
