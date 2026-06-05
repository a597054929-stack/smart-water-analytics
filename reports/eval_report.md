# Agent Evaluation Report

- Generated: 2026-06-05T15:10:54.209720Z
- Pairs evaluated: **28**
- Threshold: 80%
- Verdict: **fail**

## Aggregate metrics

| Metric | Value |
| --- | --- |
| pass_rate | 64.3% |
| tool_accuracy | 71.4% |
| avg_kw_recall | 67.9% |
| avg_latency_s | 17.76 |
| failure_rate | 7.1% |

## Per-question results

| # | Pass | Tool | Tool match | KW recall | Latency | Question |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PASS | sql_query | True | 100% | 8.9s | How many anomalies are in Zone-3? |
| 2 | FAIL | sql_query | False | 0% | 12.3s | What are the top 5 highest-scoring anomalies? |
| 3 | PASS | query_anomalies | True | 100% | 19.0s | Show me anomalies in Zone-3 |
| 4 | FAIL | get_anomaly_stats | False | 50% | 9.6s | What are the anomaly statistics for Zone-1? |
| 5 | PASS | get_data_overview | True | 100% | 10.3s | Give me an overview of the data |
| 6 | FAIL | query_meters | True | 0% | 8.2s | How many residential meters do we have? |
| 7 | PASS | get_predictions | True | 100% | 15.8s | Predict next week consumption for meter 3586950 |
| 8 | FAIL | get_predictions | False | 100% | 6.2s | Show predictions for a building |
| 9 | PASS | query_consumption | True | 100% | 21.5s | What is the weekly trend? |
| 10 | PASS | query_rank_changes | True | 100% | 16.6s | Which meters have been in the top 20 the longest? |
| 11 | FAIL | query_monthly_diff | True | 0% | 105.7s | Show me the non-revenue water situation |
| 12 | PASS | query_consumption | True | 100% | 21.4s | Compare January and February consumption |
| 13 | PASS | generate_chart | True | 100% | 16.9s | Draw a trend chart for Zone-2 |
| 14 | FAIL | analyze_anomaly | False | 100% | 22.4s | Investigate meter 3586950 anomalies |
| 15 | PASS | generate_report | True | 100% | 11.9s | Generate a Zone-3 monthly report |
| 16 | PASS | sql_query | True | 100% | 14.7s | What is the total daily consumption by DMA? |
| 17 | FAIL | sql_query | True | 0% | 13.6s | Top 5 meters by total consumption |
| 18 | PASS | sql_query | True | 50% | 16.2s | What is the average anomaly score by DMA? |
| 19 | PASS | list_tables_tool | True | 100% | 7.9s | What tables are available? |
| 20 | PASS | get_table_schema_tool | True | 100% | 6.9s | What columns does the anomalies table have? |
| 21 | FAIL | query_consumption | True | 0% | 13.9s | Show me daily consumption data |
| 22 | PASS | query_meters | True | 100% | 11.3s | List all meters in Zone-2 |
| 23 | PASS | query_anomalies | True | 100% | 13.3s | Show me watch anomalies |
| 24 | FAIL | query_consumption | True | 0% | 25.5s | Compare Zone-1 and Zone-3 consumption |
| 25 | FAIL | generate_report | False | 0% | 23.0s | Generate a comprehensive report |
| 26 | PASS |  | False | 50% | 7.5s | 凼仔漏水 |
| 27 | PASS |  | False | 50% | 8.6s | 上周水损情况 |
| 28 | PASS |  | False | 100% | 28.3s | 凼仔的 NRW |
