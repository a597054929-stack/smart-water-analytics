# Smart Water Consumption Analytics Dashboard

A full-stack data analytics platform for monitoring and predicting urban water consumption across DMA (District Metered Areas). Built as a capstone project integrating real-time data processing, machine learning prediction, anomaly detection, and an AI-powered chat interface.

> **Two data modes are supported:** a mock generator (500 synthetic meters, 125 days) and a real-data converter (9,963 Macau water meters in reference, 6,630 with active daily readings, 151-day daily cache + 30-day hourly window). See the [Quick Start](#quick-start) section for both.

## Key Features

### AI & Machine Learning
- **Anomaly Detection** ??14-day rolling window with Z-score analysis and tanh compression. Classifies anomalies into spike, drop, zero, and watch categories with configurable sensitivity thresholds.
- **LightGBM Prediction** ??7-day consumption forecast for individual meters and building aggregations using LightGBM with 13 hand-crafted features (weekday, month, lag-1/7, rolling-7/14 mean/std/max/min, day-over-day change, is_weekend, trend index, deviation ratio). R? mean 0.84 vs LinearRegression 0.05 (17? improvement). Provides feature importance for interpretability.
- **AI Chat Integration** ??Natural language interface powered by LangChain backend. Users can query anomalies, rankings, predictions, NRW metrics, and data integrity in plain language. 16 tools total; ask-back clarification for ambiguous questions; self-refinement SQL loop for bad-query recovery.

### Data Analytics
- **DMA Zone Monitoring** ??Real-time consumption breakdown across 4 district metered areas with residential/non-residential splits.
- **NRW (Non-Revenue Water) Analysis** ??Main-sub meter difference tracking to identify leakage and water loss.
- **Top 20 Ranking Tracker** ??Monitors meters that consistently appear in high-consumption rankings with trend analysis.
- **Cotai Calendar Heatmap** ??Visualizes non-residential consumption patterns in the entertainment district.

### Visualization
- **Interactive Dashboard** ??9-tab single-page application with ECharts 5 for charts and Leaflet.js for geographic mapping.
- **Geographic Heatmap** ??DMA zone boundaries with consumption intensity overlay.
- **Export Capabilities** ??PNG chart export and CSV data export for all views.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla JS, ECharts 5, Leaflet.js |
| Data Processing | Node.js (xlsx library) |
| Machine Learning | Python, scikit-learn, LightGBM, NumPy |
| Visualization | ECharts 5 (charts), Leaflet.js (maps) |
| AI Backend | LangChain + FastAPI (ReAct agent, 16 tools, multi-agent, self-refinement SQL, ask-back clarification) |
| MLOps Pipeline | Pandera (schemas), SQLite, scipy (KS-test drift) |
| Build | Custom Node.js build script (CSS/JS inlining) |

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │  Excel 原始文件                       │
                  │  真实数据：9,963 表 / 151 天          │
                  │  Mock 数据：500 表 / 125 天           │
                  └─────────────────┬────────────────────┘
                                    ▼
                  ┌──────────────────────────────────────┐
                  │  数据处理层                           │
                  │  real_data_converter.py              │
                  │  pipeline/orchestrator.py (7 stage)  │
                  │  (含 LightGBM + Pandera 校验)        │
                  └─────────────────┬────────────────────┘
                                    ▼
                  ┌──────────────────────────────────────┐
                  │  产物（文件系统）                     │
                  │  13 个 daily JSON                    │
                  │  + hourly_meter.db (~4.6M 行)        │
                  └─────────────────┬────────────────────┘
                                    ▼
                  ┌──────────────────────┐  ┌──────────────────────┐
                  │  前端仪表盘           │  │  AI 代理（可选）      │
                  │  dashboard.html      │  │  LangChain           │
                  │  (~5MB 单文件)       │◄►│  FastAPI :8000       │
                  │  ECharts + Leaflet   │  │  16 工具 + SQL       │
                  │  完全离线可跑        │  │  Planner-Executor-   │
                  │                      │  │  Synthesizer         │
                  └──────────────────────┘  └──────────────────────┘
```

> 注：本 README 是项目门面。**完整架构说明见 `docs/ARCHITECTURE.md`**。

## Quick Start

### Dashboard Only (no AI)
```bash
npm install
npm run demo        # generates mock data + builds + serves at localhost:5173
```

### Full Demo (Dashboard + AI Agent)
```bash
# Terminal 1: Generate data and build dashboard
npm install
npm run demo

# Terminal 2: Start AI Agent server
pip install -r requirements.txt
cd agent
export LLM_API_KEY="your-api-key"    # or set in ~/.openclaw/openclaw.json
python server.py                      # runs at localhost:8000

# Open http://localhost:5173 and click the chat icon
```

### Real Data Mode (Macau water data)
The converter runs in **incremental mode by default** ??it reads a
`daily_totals.json` cache to find the last processed date, then processes
only newer Excel files. A daily run with one new file is ~55 seconds.
See [`docs/REAL_DATA_ARCHITECTURE.md`](docs/REAL_DATA_ARCHITECTURE.md) for
the full design (storage tiers, SQLite windowing, daily workflow,
backfill, --full re-derivation).

#### Data volume (current as of 2026-06-05)

| Tier | Meters | Rows | Size | Window |
|------|--------|------|------|--------|
| `backend/data/output_real/meter_info.json` | **9,963** | ??| 2.6 MB | reference (master list of registered Macau meters) |
| `backend/data/output_real/daily_totals.json` | **6,630** | **905,805** | 13.5 MB | 151 days (2026-01-01 ??2026-05-31) |
| `backend/data/output_real/hourly_meter.db` | **6,551** | **4,600,794** | 2,725 MB | 30 days rolling (windowed via `--hourly-window`) |
| `backend/data/analytics_real.db` `meters` table | 9,963 | ??| 354 MB | full (the `meters` table mirrors the reference) |
| `backend/data/output_mock/all_data.json` (mock mode) | 500 | 62,500 | ??| 125 days |

The 3,333-meter gap between the 9,963 reference count and the 6,630
active daily count is meters that were registered but had no consumption
in the 1??5??window (closed accounts, seasonal buildings, or simply
no Excel entries for the period). All pipeline JSONs / dashboard /
agent see the 6,630 active set.

```bash
# Terminal 1: incremental update (only new Excel files processed)
cd portfolio
python scripts/real_data_converter.py          # ~55s / new day

# Force a full re-derivation (e.g. after a converter bugfix):
# python scripts/real_data_converter.py --full
#
# Back-fill from a specific date:
# python scripts/real_data_converter.py --since 2026-01-01

# Terminal 1 (cont.): build dashboard with real data
USE_REAL_DATA=1 node frontend/build.cjs
npx serve frontend/dist -l 5173

# Terminal 2: run pipeline on real data
python pipeline/orchestrator.py --src backend/data/output_real --db backend/data/analytics_real.db --force

# Terminal 3: agent reads from real data dir + SQLite
WATER_DATA_DIR=backend/data/output_real \
WATER_DB_PATH=backend/data/analytics_real.db \
python agent/server.py
```

**Storage tiers:**

| Tier | What's there | Where it goes | Who reads it |
| --- | --- | --- | --- |
| Daily aggregates | 14 JSONs (`daily_dma`, `daily_top20`, `predictions`, ...) | `backend/data/output_real/*.json` | Dashboard, Agent JSON tools |
| Hourly aggregates | 4 new JSONs (`hourly_dma`, `hourly_calendar`, `hourly_top_meters`, `peak_hours`) | same dir, append-only | Reserved for future dashboard views |
| Hourly raw | per-meter per-hour rows | `backend/data/output_real/hourly_meter.db` (capped at 30 days) | Agent's text-to-SQL ad-hoc queries |
| Internal cache | `{date: {meterId: total}}` | `daily_totals.json` (converter-only) | Converter's incremental mode |

The two data modes (mock vs real) are physically isolated: different output
directories, different SQLite files, different env vars. Switching is just
running the other set of bats.

On Windows the equivalent is one click per terminal in `bat/real/`:
`convert_real_data.bat` (incremental) ??`start_dashboard_real.bat` ??`start_pipeline_real.bat` ??`start_agent_real.bat`.

### Supported LLM Providers
Set `LLM_PROVIDER` env var to switch:
- `openai` (default) ??needs `LLM_API_KEY`
- `deepseek` ??needs `LLM_API_KEY` or openclaw.json config
- `mimo` ??needs openclaw.json config

## Project Structure

```
portfolio/
??? backend/
??  ??? data/
??  ??  ??? output/                # JSON artifacts (ingest source)
??  ??  ??? analytics.db           # SQLite (load_sql output)
??  ??? scripts/
??      ??? process_data.cjs       # Data processor (Excel ??JSON)
??      ??? predict_top50.py       # Top-50 meter predictions
??      ??? predict_by_building.py # Building-level predictions
??? pipeline/                      # MLOps data pipeline
??  ??? logger.py                  # Structured JSON logging with run_id
??  ??? schema.py                  # Pandera schemas (data contracts)
??  ??? validators.py              # Checkpoint validation
??  ??? data_quality.py            # IQR/z-score outlier, missing-value
??  ??? sql_loader.py              # JSON ??SQLite loader with indexes
??  ??? drift.py                   # KS-test / chi-square drift detection
??  ??? orchestrator.py            # Stage-based pipeline runner
??? agent/                         # AI Agent (LangChain + FastAPI)
??  ??? agent_tools.py             # 11 JSON tools (incl. query_data_quality)
??  ??? sql_tools.py               # 3 text-to-SQL tools
??  ??? sql_refinement.py          # Self-refinement wrapper (retry on SQL error)
??  ??? agent_executor.py          # ReAct agent + system prompt (incl. CLARIFICATION rule)
??  ??? multi_agent.py             # Planner ??Executor ??Synthesizer
??  ??? server.py                  # FastAPI with SSE streaming
??  ??? chart_generator.py         # ECharts option builder
??  ??? data_loader.py
??  ??? config.py
??? tests/                         # Evaluation framework
??  ??? qa_pairs.json              # 30 QA pairs (25 routing + 3 clarification + 2 data-quality)
??  ??? test_data_quality.py       # Outlier / missing-value tests
??  ??? test_pipeline.py           # End-to-end pipeline tests
??  ??? test_agent_tools.py        # Agent tool smoke tests
??  ??? test_clarification_prompt.py # Prompt rule + token budget tests
??  ??? test_prompt_schema_integrity.py # Asserts prompt-referenced tables exist in real DB
??  ??? test_query_data_quality_tool.py # Tests for the new query_data_quality tool
??  ??? test_sql_refinement.py     # 11 tests for the self-refinement wrapper
??  ??? test_evaluator.py          # Evaluator unit tests
??  ??? evaluate.py                # Tool accuracy + keyword recall + behavior-aware scorer
??? frontend/                      # 9-tab dashboard
??  ??? js/                        # 12 JS modules
??  ??? css/styles.css
??  ??? template.html              # Dashboard template
??  ??? build.cjs                  # Build script
??  ??? dist/                      # Built dashboard
??? public/data/
??  ??? dma_zones.geojson          # DMA zone boundaries
??? scripts/
??  ??? mock_data_generator.py     # Demo data generator
??? reports/                       # Run summaries, drift reports, eval reports
??? logs/                          # Pipeline JSON logs
??? checkpoints/                   # Stage checkpoints (resume support)
??? package.json
```

## MLOps Pipeline

The `pipeline/` module turns raw JSON artifacts into a production-grade
data flow. Seven stages, each with structured logging, schema validation,
and checkpoint support:

```bash
python pipeline/orchestrator.py --force   # run end-to-end
pytest tests/test_pipeline.py -v          # verify all stages pass
```

Stages:
1. **ingest** ??read JSON outputs into typed DataFrames
2. **clean** ??IQR outlier capping + missing-value interpolation
3. **detect_anomalies** ??validate the anomaly artifact
4. **predict** ??validate the forecast rows
5. **load_sql** ??write to SQLite with indexes on `meterId`, `date`, `dma`
6. **drift** ??KS-test (numeric) and chi-square (categorical) drift detection
7. **data_health** ??pattern detection on the cleaned daily data (per-meter z-score outliers, value-ratio daily jumps, cancellation-style negative pairs). Writes `checkpoints/stage_data_health.json` with `summary` + `recent_*` (top 50 from last 30 days) + `*_all` (full lists). Consumed by `scripts/notebooks/02_health_check.ipynb` for human review and by `01_data_correction.ipynb` for the investigate ??apply ??rebuild ??verify workflow that edits `backend/data/corrections.json`.

## AI Agent

16 LangChain tools: 11 read from the JSON files (incl. `query_data_quality` for the integrity log), 3 query the SQLite database directly via text-to-SQL, 1 reads the live page context, 1 is a chart-builder. The system prompt teaches the model when to use which category (aggregations ??SQL, summarized data ??JSON, integrity questions ??`query_data_quality`).

### Three layers of resilience (added 2026-06-05/06)

The agent has three coordinated mechanisms for handling the two most common failure modes in production LLM agents ??execution errors and intent errors ??plus a tool that surfaces the data-side failures for visibility.

| Layer | Failure mode | Mechanism | Where it lives |
| --- | --- | --- | --- |
| **1. Self-refinement SQL** | Execution: LLM writes a bad SQL (typo, wrong column) | On error, ask the LLM to rewrite with a few-shot prompt; retry up to 2 times **inside the tool** (doesn't burn a ReAct step). Returns `attempts: 1..3` so the caller can see what happened. | `agent/sql_refinement.py` |
| **2. Ask-back clarification** | Intent: question is materially ambiguous | LLM returns a brief Chinese clarification with 2-4 numbered options (most-likely marked default) and calls **no tools**. For minor uncertainty, falls back to GUESS+STATE (state assumption in a parenthetical). Hard cap: 1 question per turn. | Prompt block in `agent/agent_executor.py` |
| **3. `query_data_quality` tool** | Data: converter dropped a record (fire-test, typo, sensor fault) | Agent can answer "?唳???? / "is the data accurate" by reading `data_errors.json` (cumulative sidecar). 6 unit tests + 2 QA pairs (English + Chinese). | `agent/agent_tools.py` |

### Why these three together

- Self-refinement fixes the "code I wrote is wrong" case (~30% of agent failures in early evals)
- Ask-back fixes the "I picked the wrong tool because the question was unclear" case (~20%)
- Data quality visibility fixes the "my answer is right but the underlying data had a typo" case (e.g. the 2026-01-08 +42,940,982 m糧 meter reading on 713911 that cancelled in the daily sum)

```bash
# Run the agent
cd agent
export LLM_API_KEY="..."
python server.py                 # streams at http://localhost:8000/api/chat
```

Multi-agent mode adds a Planner ??Executor ??Synthesizer chain (toggle
in the chat UI).

## Evaluation

```bash
pytest tests/ -v                          # 181 unit tests (was 175, +6 execute dedup)
python tests/evaluate.py                  # 30 QA pairs, real LLM, ~10 min
npm run model:compare                     # LightGBM vs LinearRegression comparison
python scripts/health_check.py            # Data freshness + SQLite integrity check
```

The evaluator scores:
- **tool accuracy** ??did it call the expected tool?
- **keyword recall** ??fraction of expected keywords in the answer **or in the raw tool output** (so SQL column paraphrases don't false-FAIL)
- **behavior-aware pass** ??for clarification pairs, pass = (no tool calls) AND keywords present; for guess+state, pass = (any tool call) AND keywords present
- **latency** ??end-to-end wall time
- **failure rate** ??% of unanswered questions

Output: `reports/eval_per_qa.json` and `reports/eval_report.md`.

Latest real-data run (30 pairs, mimo-v2.5-pro, `analytics_real.db`):
- **pass_rate 86.7%** (26/30) / tool_accuracy 80.0% / avg_kw_recall 88.3% / avg_latency 30.8s
- **0% failure rate** (all 30 pairs completed)
- All 3 clarification pairs PASS (regression OK), both data-quality pairs PASS
- 4 remaining FAIL: 2 tool-choice (Q8, Q25), 1 keyword mismatch (Q24), 1 tool-choice+keyword (Q14)

### Test layers
- **66 unit tests** (`pytest tests/ --ignore=tests/evaluate.py`) ??pure logic, no live LLM, ~2s
- **30 live-LLM QA pairs** (`python tests/evaluate.py`) ??runs the agent end-to-end, ~10 min
- **2 schema-integrity tests** (`tests/test_prompt_schema_integrity.py`) ??grep the system prompt for `FROM <table>` and `get_table_schema_tool("...")` references, assert each exists in `analytics_real.db`. Catches the 2026-06-05 `meter_daily` bug at unit-test time.

## Anomaly Detection Algorithm

The system uses a **14-day rolling window** approach:

1. Compute mean and standard deviation of the past 14 days
2. Calculate Z-score: `z = (current - mean) / std`
3. Apply tanh compression for score normalization: `score = tanh(z / 3)`
4. Classify based on thresholds:
   - **Spike**: `current > mean ? 4` and `score > 0.5`
   - **Drop**: `current < mean ? 0.3` and `score > 0.4`
   - **Zero**: `current = 0` and `mean > 1`
   - **Watch**: `current > mean ? 1.5` and `score > 0.25`

## Prediction Model

Uses **LightGBM** (gradient boosting) with 13 hand-crafted features:
- **Calendar**: weekday, month, is_weekend
- **Lag**: lag-1 (yesterday), lag-7 (last week same day)
- **Rolling windows** (7-day, 14-day): mean, std, max, min
- **Trend**: day-over-day change, linear trend index, deviation ratio

Generates 7-day ahead forecasts. R-square mean = 0.84 (vs LinearRegression 0.05, 17x improvement). Per-meter feature importance is exposed in the predict tab for interpretability.

Run `npm run model:compare` to benchmark LightGBM vs LinearRegression side-by-side.

## Engineering Foundation

Beyond the business logic, this project ships with a serious engineering baseline:

- **Reproducible builds** — `requirements.lock.txt` pins 135 packages; `pyproject.toml` declares project metadata and dev tools.
- **Linted + type-checked** — ruff (`E/F/W/I/UP/B` rule sets) runs in CI on every push; per-file ignores for `tests/` / `agent/` / `scripts/`.
- **Structured logging** — `pipeline/logger.py` uses `structlog` (JSON output, `run_id` propagated through context vars, stage-aware loggers).
- **Schema contracts** — 11 Pandera `DataFrameSchema` validated at every stage boundary; bad data fails fast.
- **Typed API** — All 8 FastAPI endpoints declare `response_model` + `tags` + `summary`; Swagger UI at `http://localhost:8000/docs`.
- **Healthcheck** — `Dockerfile` has a real `HEALTHCHECK` hitting `/api/health`; works with `docker inspect` and K8s liveness probes.
- **Architecture Decision Records** — see [`docs/adr/`](docs/adr/README.md) for the "why" behind SQLite, Pandera, monorepo, and Claude Code design philosophy.
- **Shared test fixtures** — `tests/conftest.py` exposes `tmp_ckpt` / `db_path` / `pipeline_output` / `mock_llm` for any new test file.
- **In-process metrics** — `GET /api/metrics` returns Prometheus-style counters for chat requests, tool calls, failures, and questions logged.
- **Sensitive data protection** — Password-gated masking for building names, contract IDs, and meter IDs in real-data mode (`USE_REAL_DATA=1`). Mock mode stays fully open.
- **Tool sandbox** — `@safe_tool_call` decorator adds timeout (threading-based, Windows compatible), path blacklist (`.env`, `/etc`, `C:/Windows`), and JSONL audit log (`logs/tool_audit.log`) to all 18 agent tools.
- **Memory compression** — Two-tier conversation memory: recent 6 turns verbatim + older turns summarized via LLM. Three-layer fallback on LLM failure.
- **30-case agent harness** — Offline mock-LLM tests covering tool selection (10), ambiguous input (8), privilege escalation rejection (7), and edge cases (5). Runs in ~3 seconds.
- **153 tests** — pipeline, agent tools, memory, sandbox, harness, regression, adversarial, evaluator.

Full architecture map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT ??see [LICENSE](LICENSE).

## Development

### Running with Docker

```bash
cp .env.example .env       # fill in LLM_API_KEY
docker compose up --build
# Dashboard: http://localhost:5173
# Agent:     http://localhost:8000/api/health
```

### Running locally on Windows

The `bat/` folder has one-click scripts split by data source:

| Script | Purpose |
| --- | --- |
| `bat/mock/start_dashboard.bat` | Mock data dashboard (port 5173) |
| `bat/mock/start_agent.bat` | Mock data agent (port 8000) |
| `bat/mock/start_pipeline.bat` | Run pipeline on mock data |
| `bat/mock/start_tests.bat` | Run pytest |
| `bat/real/convert_real_data.bat [N]` | Convert last N days (default 30) of real Macau Excel ??JSON + SQLite |
| `bat/real/start_pipeline_real.bat` | Run pipeline on real data |
| `bat/real/start_dashboard_real.bat` | Real data dashboard (USE_REAL_DATA=1) |
| `bat/real/start_agent_real.bat` | Real data agent (sets WATER_DATA_DIR + WATER_DB_PATH) |

### Secret scanning

A pre-commit hook ([`.pre-commit-config.yaml`](.pre-commit-config.yaml)) runs **gitleaks** to block accidental commits of API keys.

```bash
pip install pre-commit
pre-commit install
```

GitHub also offers [native secret scanning](https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning) ??enable it in the repo's **Settings ??Security** tab.



