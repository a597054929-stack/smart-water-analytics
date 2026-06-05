# Agent Evaluation Report

- Generated: 2026-06-05T15:49:30.750737Z
- Pairs evaluated: **28**
- Threshold: 60%
- Verdict: **pass**

## Aggregate metrics

| Metric | Value |
| --- | --- |
| pass_rate | 60.7% |
| tool_accuracy | 71.4% |
| avg_kw_recall | 62.5% |
| avg_latency_s | 20.49 |
| failure_rate | 0.0% |

## Per-question results

| # | Pass | Tool | Tool match | KW recall | Latency | Question |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | PASS | sql_query | True | 100% | 36.5s | How many anomalies are in 路氹城區? |
| 2 | FAIL | sql_query | True | 0% | 23.3s | What are the top 5 highest-scoring anomalies? |
| 3 | PASS | query_anomalies | True | 100% | 8.5s | Show me anomalies in 路氹城區 |
| 4 | FAIL | get_anomaly_stats | False | 50% | 8.3s | What are the anomaly statistics for 澳門低區? |
| 5 | FAIL | get_data_overview | True | 0% | 9.2s | Give me an overview of the data |
| 6 | FAIL | query_meters | False | 0% | 15.0s | How many residential meters do we have? |
| 7 | PASS | get_predictions | True | 100% | 7.1s | Predict next week consumption for meter 753832 |
| 8 | FAIL | get_predictions | False | 0% | 6.7s | Show predictions for a building |
| 9 | PASS | query_consumption | True | 100% | 22.4s | What is the weekly trend? |
| 10 | PASS | query_rank_changes | True | 100% | 18.6s | Which meters have been in the top 20 the longest? |
| 11 | FAIL | query_monthly_diff | True | 0% | 18.0s | Show me the non-revenue water situation |
| 12 | FAIL | query_consumption | True | 0% | 17.2s | Compare January and February consumption |
| 13 | PASS | generate_chart | True | 100% | 15.6s | Draw a trend chart for 路氹城區 |
| 14 | FAIL | analyze_anomaly | False | 100% | 9.4s | Investigate meter 753832 anomalies |
| 15 | PASS | generate_report | True | 100% | 97.3s | Generate a 路氹城區 monthly report |
| 16 | PASS | sql_query | True | 100% | 20.3s | What is the total daily consumption by DMA? |
| 17 | FAIL | sql_query | True | 0% | 17.3s | Top 5 meters by total consumption |
| 18 | FAIL | sql_query | True | 0% | 18.6s | What is the average anomaly score by DMA? |
| 19 | PASS | list_tables_tool | True | 100% | 8.2s | What tables are available? |
| 20 | PASS | get_table_schema_tool | True | 100% | 9.5s | What columns does the anomalies table have? |
| 21 | PASS | query_consumption | True | 100% | 26.5s | Show me daily consumption data |
| 22 | PASS | query_meters | True | 100% | 31.2s | List all meters in 路氹城區 |
| 23 | PASS | query_anomalies | True | 100% | 14.4s | Show me watch anomalies |
| 24 | PASS | query_consumption | True | 100% | 52.8s | Compare 澳門低區 and 路氹城區 consumption |
| 25 | FAIL | generate_report | False | 0% | 11.3s | Generate a comprehensive report |
| 26 | PASS |  | False | 50% | 10.8s | 氹仔漏水 |
| 27 | PASS |  | False | 50% | 6.4s | 上周水损情况 |
| 28 | PASS |  | False | 100% | 33.7s | 氹仔的 NRW |
