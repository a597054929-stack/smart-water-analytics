# Changelog

All notable changes to the Smart Water Analytics project.

## 2026-06-04

### Bug Fix
- **`frontend/build.cjs` now cleans `dist/data/` before writing** — without this, a stale `all_data.json` from a previous mock build silently won the loader's "try bundle first" branch, causing real-data builds to display mock data. All 13 real-data JSONs were copied to `dist/data/`, but the loader bypassed them. Caught during a real-data verification session.

### Engineering
- Add `bat/real/start_daily_real.bat` — one-click daily workflow that chains `real_data_converter.py` (incremental) → `pipeline/orchestrator.py` (rebuild SQLite) → `node build.cjs USE_REAL_DATA=1` (rebuild dist) in sequence. All args pass through to the converter, so `--full` / `--since` / `--hourly-window` still work for one-off operations.

### Security
- Add to `.gitignore`: `backend/data/output_real/`, `backend/data/analytics_real.db`, `*.bak`, `daily_totals.json` — these contain either real Macau water-meter data (9,963 meters, daily consumption) or converter internal cache. The `.bat` files (containing local LLM API keys) were already covered by the existing `*.bat` rule.

### Real Data Incremental Pipeline
- **`real_data_converter.py` now supports incremental mode by default** — reads a `daily_totals.json` cache to find the last processed date, then processes only newer Excel files. Daily run with one new day: ~55s (vs ~2h full re-derivation of 151 days).
- Add `--full` flag for force re-derivation from all Excel files (use when changing schema or after a converter bugfix).
- Add `--since YYYY-MM-DD` flag for back-fill mode (re-process every Excel file on or after the given date, ignoring cache).
- Add `--hourly-window N` flag (default 30) to cap `hourly_meter.db` size.
- Add `daily_totals.json` internal cache (date → meterId → total) so the converter can skip re-reading historical Excel files.
- Suppress the noisy `Workbook contains no default style` openpyxl warning (40+ lines per run for 30 daily files + 10 reference files).
- `hourly_meter.db` is now **append + window-pruned** rather than full-rebuilt: `INSERT OR IGNORE` on `(meterId, datetime)` makes it idempotent; rows older than `today - hourly_window + 1` are deleted.
- Add **4 new hourly aggregate JSONs** (all append-only, in `backend/data/output_real/`):
  - `hourly_dma.json` — per-day per-hour per-DMA totals (24×4 = 96 entries/day)
  - `hourly_calendar.json` — per-day 24h total profile
  - `hourly_top_meters.json` — per-day top-10 meters with 24h profile
  - `peak_hours.json` — per-day per-DMA peak hour + off-peak average (peak = 18:00-22:00)
- Daily aggregates (daily_dma, daily_top20, anomalies, predictions, ...) are now **re-derived from the merged daily dict** instead of re-read from Excel, which is much faster (in-memory Python loops, ~1s for 151 days).
- `convert_real_data.bat` now passes all args through (`%*`) — no more bat-side arg parsing.

### Bug Fix
- **`pipeline/orchestrator.py` `stage_load_sql` ignored `--src`** — it hard-coded `OUTPUT_DIR` (mock path), so `hourly_meter.db` was silently never loaded into `analytics_real.db` for real-data runs. Now `src` is passed through; the load_sql log line includes `"src"` so the path is auditable. Discovered while verifying incremental compatibility with the new converter.

### Documentation
- Add `docs/REAL_DATA_ARCHITECTURE.md` — full description of the storage tiers (daily JSONs / hourly JSONs / SQLite / cache), the three converter modes, the daily workflow, the 14+4 output artefacts, and the known trade-offs (SQLite window, anomaly cold-start, hourly JSON append-only semantics for back-fill).
- Update README.md "Real Data Mode" section to point at the new architecture doc and describe the incremental workflow.

### Real Data Integration (initial)
- Add `scripts/real_data_converter.py` — reads 10 MACAU-reference + daily Macau 2026 Excel files → 14 JSONs + hourly_meter.db
- Add dual-granularity storage: daily JSONs for Agent/frontend + hourly SQLite for SQL analysis
- Add `WATER_DB_PATH` env var override so the agent can switch to real-data SQLite without code changes
- Update `pipeline/schema.py` `VALID_DMAS` to include the 4 real Macau zones (澳門低區, 澳門填海A區, 澳大橫琴區, 路氹城區) and add `REAL_PROPERTY_TYPE_MAPPING` for the 43 real property types
- Update `pipeline/sql_loader.py`: add `load_hourly_meter` (ATTACH-based bulk copy from converter's hourly_meter.db)
- Update `pipeline/orchestrator.py` `stage_ingest` to accept `--src` so it can ingest real data dir
- Update `frontend/build.cjs`: dual-mode loader — try `all_data.json` (mock), fall back to 12 individual JSONs (real). `USE_REAL_DATA=1` env var switches the build to copy real data files

### Pipeline Optimization
- Trim chat history from 20 to 6 messages per request (reduces ~1,200 input tokens)
- Reduce max_tokens from 2048 to 1024 (faster output generation)
- Add in-memory cache for JSON data loading (tool calls: 15-69ms → <1ms)
- Streamline system prompt from ~845 to ~304 tokens (64% reduction)
- Merge 18 tools down to 13 (reduce LLM selection overhead)
  - query_anomalies: added mode=list/stats/analyze (was 3 separate tools)
  - get_predictions: added query_type=meter/building (was 2 separate tools)
  - query_consumption: new tool merging daily/weekly/compare (was 3 separate tools)
- Add conversation memory: summarize old messages into [CONVERSATION MEMORY] system message
- Add rule-based tool pre-selection: keyword matching injects [TOOL HINT] into system message

### Bug Fixes
- Fix MiniMax-M3 Anthropic-compatible API not supporting tool use (hallucinated tool calls)
- Add diagnostic logging for tool calls and message flow
- Clear stale chat history containing failed page-context attempts

### Configuration
- Switch MiniMax bat to OpenAI-compatible endpoint (`api.minimax.chat/v1`)
- Add mimo-v2.5-pro bat file with OpenAI-compatible config

### Documentation
- Add `docs/DEBUGGING_LOG.md` — full debugging journey for page-context issue
- Add `docs/PERFORMANCE_ANALYSIS.md` — bottleneck analysis and optimization plan
- Add `docs/OPTIMIZATION_GUIDE.md` — comprehensive optimization experience guide (P0-P3, LLM providers, Windows tips)
- Add `docs/BLUEPRINT.md` — overall project blueprint in Chinese, explaining architecture and technical decisions
- Add `docs/INTERVIEW_PREP.md` — interview preparation in Chinese (removed HKT-specific references)
- Remove all HKT-specific references from CHANGELOG, CHEAT_SHEET, and INTERVIEW_PREP

### Pipeline Optimization
- Remove redundant `daily_total_by_dma.json` (data already in `daily_dma.json`)
- Remove redundant `daily_top20_by_dma.json` (data already in `daily_top20.json`)
- Split `predictions.json` → `predictions.json` (predictions only) + `predictions_fitted.json` (historical fitted values). Reduces main file ~90%
- Remove 3 redundant Agent tools: `query_daily_dma`, `query_weekly`, `compare_months` (all merged into `query_consumption`)
- Add Pandera schemas for `meter_daily`, `cotai_calendar`, `daily_top20` (previously unvalidated)

## 2026-06-03

### Engineering Completeness
- Add GitHub Actions CI: pytest on push/PR, ubuntu-latest, Python 3.12
- Add Dockerfile + docker-compose for one-command dev setup
- Add MIT LICENSE
- Add `.env.example` documenting all environment variables
- Add gitleaks pre-commit hook + `.gitleaks.toml` allowlist
- Add `.gitattributes` enforcing CRLF for bat files, LF for Python/YAML/Markdown

### Bug Fixes
- Fix bat files failing with "'x' is not recognized" — caused by LF-only line endings
- Add pre-flight port check using PowerShell (kills orphan processes on port 8000)
- Fix SQL tools silently not registered — broken `from .sql_tools import` in non-package dir
- Fix "multiple non-consecutive system messages" crash — strip stale system entries from history

### Features
- Add `set_page_context` / `get_current_page_context` tool for frontend page-state awareness
- Add `_page_state.py` module for process-wide page context (survives LangGraph tool rebinding)
- Add `/api/debug/pagestate` endpoint (temporary, for diagnosis)

### Documentation
- Add Docker, pre-commit, and secret scanning sections to README
- Add `docs/DEBUGGING_LOG.md` and `docs/PERFORMANCE_ANALYSIS.md`

## 2026-06-02

### Features
- Add text-to-SQL tools: `list_tables_tool`, `get_table_schema_tool`, `sql_query`
- Add MLOps pipeline: schema validation (pandera), drift detection, evaluation framework
- Add LLM evaluation with prompt templates and scoring
- Add page-context tools and frontend context injection
- Add interview preparation docs

### Bug Fixes
- Fix agent crash when `WATER_DATA_DIR` or `__file__` is a relative path

## 2026-06-01

### Features
- Add streaming SSE output with real-time token delivery
- Add tool call visualization (shows which tools are being used)
- Add conversation persistence (saves to JSON file)
- Add multi-agent mode (planner + executor + synthesizer)
- Add 3 new tools: `compare_months`, `analyze_anomaly`, `generate_report`
- Add MiMo as default LLM provider + NVIDIA provider support

### Bug Fixes
- Fix agent response parsing for Anthropic-compatible providers

## 2026-05-30

### Initial Release
- Smart Water Analytics Dashboard with demo data
- AI Agent integration with LangChain + FastAPI
- 15 data query tools (anomalies, meters, predictions, consumption, NRW, charts)
- ECharts visualization generation
