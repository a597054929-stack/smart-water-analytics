# Agent Evaluation Report

- Generated: 2026-06-05T14:27:39.160453Z
- Pairs evaluated: **25**
- Threshold: 80%
- Verdict: **fail**

## Aggregate metrics

| Metric | Value |
| --- | --- |
| pass_rate | 72.0% |
| tool_accuracy | 80.0% |
| avg_kw_recall | 80.0% |
| avg_latency_s | 17.02 |
| failure_rate | 0.0% |

## Per-question results

| # | Pass | Tool | Tool match | KW recall | Latency | Question |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | FAIL | sql_query | False | 100% | 6.9s | How many anomalies are in Zone-3? |
| 2 | FAIL | sql_query | False | 0% | 13.2s | What are the top 5 highest-scoring anomalies? |
| 3 | PASS | query_anomalies | True | 100% | 21.6s | Show me anomalies in Zone-3 |
| 4 | FAIL | get_anomaly_stats | False | 50% | 9.8s | What are the anomaly statistics for Zone-1? |
| 5 | PASS | get_data_overview | True | 100% | 8.0s | Give me an overview of the data |
| 6 | PASS | query_meters | True | 100% | 9.9s | How many residential meters do we have? |
| 7 | PASS | get_predictions | True | 100% | 14.6s | Predict next week consumption for meter 3586950 |
| 8 | PASS | get_predictions | True | 100% | 17.5s | Show predictions for a building |
| 9 | FAIL | query_consumption | True | 0% | 14.7s | What is the weekly trend? |
| 10 | PASS | query_rank_changes | True | 100% | 15.3s | Which meters have been in the top 20 the longest? |
| 11 | PASS | query_monthly_diff | True | 100% | 18.6s | Show me the non-revenue water situation |
| 12 | PASS | query_consumption | True | 100% | 17.0s | Compare January and February consumption |
| 13 | PASS | generate_chart | True | 100% | 17.7s | Draw a trend chart for Zone-2 |
| 14 | FAIL | analyze_anomaly | False | 100% | 20.1s | Investigate meter 3586950 anomalies |
| 15 | PASS | generate_report | True | 100% | 9.9s | Generate a Zone-3 monthly report |
| 16 | PASS | sql_query | True | 100% | 18.5s | What is the total daily consumption by DMA? |
| 17 | FAIL | sql_query | True | 0% | 13.0s | Top 5 meters by total consumption |
| 18 | PASS | sql_query | True | 50% | 13.6s | What is the average anomaly score by DMA? |
| 19 | PASS | list_tables_tool | True | 100% | 7.3s | What tables are available? |
| 20 | PASS | get_table_schema_tool | True | 100% | 9.6s | What columns does the anomalies table have? |
| 21 | PASS | query_consumption | True | 100% | 17.0s | Show me daily consumption data |
| 22 | PASS | query_meters | True | 100% | 9.3s | List all meters in Zone-2 |
| 23 | PASS | query_anomalies | True | 100% | 11.6s | Show me watch anomalies |
| 24 | PASS | query_consumption | True | 100% | 13.3s | Compare Zone-1 and Zone-3 consumption |
| 25 | FAIL | generate_report | False | 0% | 97.5s | Generate a comprehensive report |
