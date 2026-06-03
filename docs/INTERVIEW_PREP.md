# HKT Data Scientist Interview — Project Guide

> This document is written for the **HKT (Hong Kong Telecommunications) Data
> Scientist** interview. It explains the design decisions in this portfolio,
> connects them to telecom use cases, and gives sample answers to the most
> likely interview questions.

---

## 1. Project Overview (30-second elevator pitch)

**Smart Water Analytics** is an end-to-end analytics platform for a water
utility: daily meter ingestion, anomaly detection, 7-day forecasting, an AI
agent for natural-language queries, and an MLOps-grade data pipeline.

Built to demonstrate five things HKT cares about:
1. **MLOps maturity** — pipeline transparency, schema validation, drift detection.
2. **Structured + unstructured data** — text-to-SQL over a normalized store
   plus JSON tool calls for summarized data.
3. **Evaluation rigor** — a 25-question QA suite with automated scoring.
4. **Data engineering** — automated outlier detection, missing-value handling,
   checkpointed pipeline.
5. **Communication** — production-grade logging, clear error messages, run
   summaries.

---

## 2. Why this matters for HKT

| Portfolio capability | Telecom equivalent |
| --- | --- |
| Daily meter ingestion + cleaning | CDR (Call Detail Record) ingestion, drop noisy events |
| Anomaly detection (Z-score + rolling window) | Fraud detection, network-failure detection |
| 7-day forecast (exponential smoothing per meter) | ARPU forecast, churn risk forecast, traffic forecast |
| Text-to-SQL agent | Ops query bot for network counters and customer care tickets |
| Drift detection on anomaly features | Customer behavior drift, network topology drift |
| Evaluation QA suite | A/B test scoring, model regression in CI/CD |
| Pandera schema validation | Schema contracts between upstream (OSS) and the DS layer |

The **architectural patterns transfer** even though the data domain changes.

---

## 3. Architecture at a glance

```
Raw data (JSON)            ─┐
                            │
  pipeline/  ───────────────┼──►  Pandera schema  ──►  SQLite (analytics.db)
    ingest                   │     validation             │
    clean  (IQR + interp)    │                            │
    detect_anomalies         │                            │
    predict                  │                            ▼
    load_sql                 │              agent/  (17 LangChain tools)
    drift (KS / chi²)        │                ├─ 14 JSON tools
                            │                └─ 3  text-to-SQL tools
                            │
  reports/  ◄──────────────┘  run summaries, eval reports, drift reports
            frontend/  (ECharts dashboard, chat widget)
```

The pipeline is **stage-based with checkpoints** — if a stage fails, the
next run resumes from the last good state.

---

## 4. Key design decisions

### 4.1 Why Pandera (not Great Expectations or JSON Schema)?
- **Pandera is in Python**, which means one language across the pipeline.
- We get dtype coercion, regex matching, value-range checks, uniqueness
  constraints — all declarative, all version-controllable.
- Errors name the failing column and value range, so triage is fast.
- We deliberately did not adopt Great Expectations: it brings a heavyweight
  data-context server, which is overkill for a portfolio and adds friction.

### 4.2 Why SQLite (not Postgres, BigQuery, etc.)?
- **Zero infra** — the file is a sibling of the JSON outputs, no server
  to spin up, no credentials to manage.
- The same SQL works against any relational store. If the portfolio
  promoted to production, the SQLite file becomes a Postgres schema; the
  agent's text-to-SQL tools don't change.
- **Indexes on `meterId`, `date`, `dma`** are added at load time so
  typical queries (filter by DMA + date range) are O(log n).

### 4.3 Why a ReAct agent (not RAG)?
- The user's questions are *operational* (counts, top-N, comparisons), not
  *informational* (what is the policy on...?). RAG retrieves documents;
  an agent invokes tools. Tools are the right primitive.
- We do keep JSON files in the agent's prompt as "summarized data", so
  hybrid reasoning is possible — the agent decides.
- For HKT, this maps to ops queries over CDR tables rather than knowledge
  base lookups.

### 4.4 Why multi-agent (Planner → Executor → Synthesizer)?
- **Separation of concerns** — planning, execution, synthesis. Easier to
  debug, easier to swap the planner for a fine-tuned one later.
- **Visibility** — the explicit plan can be shown to the user. Useful
  for regulated industries (telecom is regulated).
- The cost is latency: three LLM calls instead of one. We make this
  optional via a mode toggle in the chat UI.

### 4.5 Why KS-test (not just visual drift detection)?
- KS-test gives a single number (p-value) that we can threshold.
- It works for any distribution shape — no normality assumption.
- For categorical drift we use chi-square, the standard alternative.
- Drift detection is wired into the pipeline as a stage, so every run
  produces a JSON report (`reports/drift_report.json`).

---

## 5. Terminology glossary

These are terms you should use naturally in the interview:

- **Data Drift** — when the distribution of input features changes over
  time, often silently degrading model performance.
- **Schema validation** — checking the structure of a data artifact
  (column names, types, value ranges) against a contract.
- **Checkpointing** — saving intermediate state so a failed run can
  resume without redoing work.
- **Observability** — the ability to ask "what happened during this run?"
  from logs, metrics, and traces.
- **Run ID** — a single identifier propagated through every log line of
  one pipeline execution; the unit of traceability.
- **Text-to-SQL** — converting a natural-language question into a SQL
  query that returns the answer.
- **Hybrid search** — combining a structured query (SQL) with an
  unstructured search (full-text / fuzzy) in one answer.
- **Traceability** — being able to reconstruct exactly which data, code,
  and parameters produced a given model output.

---

## 6. Likely interview Q&A

### Q1: "Walk me through your pipeline."
> Six stages: `ingest` reads JSON outputs into DataFrames; `clean`
> applies IQR-based outlier capping and missing-value interpolation;
> `detect_anomalies` validates the artifact and reports distribution
> stats; `predict` validates the forecast rows; `load_sql` writes
> everything to a SQLite database with indexes; `drift` compares the
> current run's distributions to the saved baseline via KS-test and
> chi-square. Every stage logs its start/finish with a `run_id` and
> writes a checkpoint. Pandera validates the artifact at the boundary
> of every stage.

### Q2: "How would you scale this for HKT's traffic?"
> The text-to-SQL tools work against any RDBMS — swap SQLite for
> Postgres or Snowflake. For high-throughput ingestion, the JSON read
> step would be replaced with Kafka or Kinesis; the rest of the
> pipeline is unchanged. Drift detection would move from
> "after-the-batch" to "on every window" via streaming aggregations.
> The agent itself would sit behind a queue and become a microservice
> rather than a CLI.

### Q3: "What happens if the data shape changes?"
> Pandera schema validation catches it at the boundary of the affected
> stage. The orchestrator logs the failure, leaves the checkpoint
> from the last good stage in place, and exits with a clear error.
> In production, this would page the on-call DS via the structured
> log fields (`stage`, `schema`, `errors`).

### Q4: "Why a custom evaluator and not RAGAS?"
> RAGAS is tuned for RAG pipelines (faithfulness, answer relevance,
> context recall). My agent is a tool-using agent, not a retriever.
> RAGAS wouldn't measure the right thing. My evaluator measures
> *tool accuracy* (did it call the right tool?) and *keyword recall*
> on the final answer — closer to what production care-about for an
> agent. I can add an LLM-judge pass on top later for nuance.

### Q5: "Explain data drift and how you detect it."
> Data drift is when the distribution of input features changes between
> training and production. It can be *covariate shift* (P(X) changes),
> *label shift* (P(Y) changes), or *concept drift* (P(Y|X) changes).
> I detect it with the two-sample Kolmogorov-Smirnov test for numeric
> columns and the chi-square test of independence for categorical
> columns. Both produce a p-value; if it's below 0.05, I flag the
> column. The pipeline stores a baseline on first run and compares
> every subsequent run to it.

### Q6: "Tell me about a hard data-cleaning decision you made."
> The cleaning stage uses IQR-based winsorization instead of dropping
> outliers. Dropping rows would break the time-series continuity and
> hide the truth that a meter spiked to 1000m³ last Tuesday. Capping
> preserves the *existence* of the event while bounding the
> *magnitude*, so downstream anomaly detection still sees the row.
> The threshold (k=3 by default) is a trade-off: too aggressive and
> we hide real anomalies; too lenient and we let sensor faults
> pollute the model.

### Q7: "What would you add for a production deployment?"
> Three things, in priority order:
> 1. **Schema versioning** — bump the `SCHEMA_VERSION` on breaking
>    changes, write a migration in `validators.py`, fail loudly on
>    missing migrations.
> 2. **Drift alerting** — pipe `drift_report.json` to PagerDuty or
>    Slack when `drift_count > 0`.
> 3. **Eval in CI/CD** — block PRs that drop `pass_rate` below
>    `threshold` in `tests/evaluate.py`.
> None of these requires a rewrite; the data is already there.

### Q8: "How does the agent decide between SQL and JSON tools?"
> The system prompt has a "tool selection guide" that maps question
> types to tool categories. Aggregations, joins, top-N, date-range
> filters → SQL. High-level questions like "show me Zone-3 anomalies"
> → JSON tools that return pre-summarized data. The model picks per
> sub-question, so one user turn can mix both. In production I'd
> measure which path produces fewer tool errors and bias the prompt
> accordingly.

### Q9: "Why streaming SSE for the chat endpoint?"
> The agent's planning loop can take 5–10 seconds. Without streaming,
> the user sees a frozen UI. With SSE, the server emits `tool` events
> as each tool finishes, then a final `answer` event. The frontend
> shows the user *which tool is running right now*, which makes the
> agent feel responsive and transparent. It's also how production
> observability tools like LangSmith stream traces.

### Q10: "What is your biggest regret or what would you do differently?"
> I'd split the orchestrator into a thin "runner" and a fat
> "definition" file. Right now adding a stage means editing the
> `STAGES` list and the `run()` function. A YAML or Python config
> would let ops add stages without touching code. It's a small
> refactor; I'd do it before scaling to more data sources.

---

## 7. Demo script (5 minutes)

1. **Open with problem** (30s): "Water utilities lose 30% of water to
   leaks. I built a system to detect anomalies in real-time. This is
   the same architecture pattern HKT uses for CDR analytics."

2. **Show the pipeline** (1m): `python pipeline/orchestrator.py` — point
   out the JSON logs, the checkpoint directory, the SQLite DB, the
   drift report. Show that one re-run reuses checkpoints.

3. **Show the agent** (1.5m): open the dashboard, click the chat
   widget. Ask "How many anomalies are in Zone-3?" — show the
   streaming tool calls, the `sql_query` selection, the chart that
   gets rendered inline. Toggle to multi-agent mode, ask the same
   question — show the explicit plan that appears.

4. **Show the SQL** (1m): open `backend/data/analytics.db` in a
   SQLite browser, run
   `SELECT dma, type, COUNT(*) FROM anomalies GROUP BY dma, type`.
   Explain: "In HKT, this is the same query you would run against
   a CDR table or a network-counter store."

5. **Show evaluation** (1m): `pytest tests/ -v` — show all green.
   Show `reports/eval_report.md` from a real run, point out the
   tool-accuracy metric.

6. **Close with HKT angle** (30s): "HKT has 5M+ subscribers. The
   same architecture applies: pipeline for real-time events, agent
   for ops queries, drift detection for changing customer behavior,
   evaluation as a CI gate. The data changes; the patterns don't."

---

## 8. Files to read in the repo

| File | Why it matters |
| --- | --- |
| `pipeline/orchestrator.py` | The pipeline runner — the MLOps spine. |
| `pipeline/schema.py` | Pandera schemas — the data contracts. |
| `pipeline/data_quality.py` | Outlier + missing-value handling. |
| `pipeline/drift.py` | KS-test and chi-square drift detection. |
| `agent/sql_tools.py` | Text-to-SQL: how the agent queries the DB. |
| `agent/agent_executor.py` | The ReAct agent and the tool-selection prompt. |
| `tests/qa_pairs.json` | The 25 QA pairs used to score the agent. |
| `tests/evaluate.py` | The scoring logic. |
| `docs/CHEAT_SHEET.md` | A one-page summary to skim before the interview. |

---

## 9. Out of scope (deliberately)

- **Kafka / streaming ingestion** — would distract from the core
  message of "pipeline transparency". Same code, different transport.
- **MLflow / Weights & Biases** — overkill for a portfolio; not yet
  a differentiator.
- **Deep learning models** — current models are interpretable on
  purpose. A telecom churn model would still be logistic regression
  + gradient boosting until you have hundreds of millions of rows.
- **Multi-language support** — focus is English + Chinese only.
