# Smart Water Consumption Analytics Dashboard

A full-stack data analytics platform for monitoring and predicting urban water consumption across DMA (District Metered Areas). Built as a capstone project integrating real-time data processing, machine learning prediction, anomaly detection, and an AI-powered chat interface.

> **Note:** This portfolio version uses synthetic demo data. The production system processes data from 8,000+ smart water meters.

## Key Features

### AI & Machine Learning
- **Anomaly Detection** — 14-day rolling window with Z-score analysis and tanh compression. Classifies anomalies into spike, drop, zero, and watch categories with configurable sensitivity thresholds.
- **Linear Regression Prediction** — 7-day consumption forecast for individual meters and building aggregations using scikit-learn with feature engineering (day-of-week, trend, seasonality).
- **AI Chat Integration** — Natural language interface powered by LangChain backend. Users can query anomalies, rankings, predictions, and NRW metrics in plain language.

### Data Analytics
- **DMA Zone Monitoring** — Real-time consumption breakdown across 4 district metered areas with residential/non-residential splits.
- **NRW (Non-Revenue Water) Analysis** — Main-sub meter difference tracking to identify leakage and water loss.
- **Top 20 Ranking Tracker** — Monitors meters that consistently appear in high-consumption rankings with trend analysis.
- **Cotai Calendar Heatmap** — Visualizes non-residential consumption patterns in the entertainment district.

### Visualization
- **Interactive Dashboard** — 9-tab single-page application with ECharts 5 for charts and Leaflet.js for geographic mapping.
- **Geographic Heatmap** — DMA zone boundaries with consumption intensity overlay.
- **Export Capabilities** — PNG chart export and CSV data export for all views.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla JS, ECharts 5, Leaflet.js |
| Data Processing | Node.js (xlsx library) |
| Machine Learning | Python, scikit-learn (LinearRegression), NumPy |
| Visualization | ECharts 5 (charts), Leaflet.js (maps) |
| AI Backend | LangChain + FastAPI (ReAct agent, 17 tools, multi-agent) |
| MLOps Pipeline | Pandera (schemas), SQLite, scipy (KS-test drift) |
| Build | Custom Node.js build script (CSS/JS inlining) |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Data Pipeline                      │
│                                                      │
│  Excel Files ──► Node.js Processor ──► JSON Output   │
│       │                              │               │
│       │                    ┌─────────┴────────┐      │
│       │                    │   Python ML      │      │
│       │                    │  (Predictions)   │      │
│       │                    └─────────┬────────┘      │
│       │                              │               │
│       ▼                              ▼               │
│  ┌──────────────────────────────────────────┐        │
│  │         Single-File Dashboard            │        │
│  │    (HTML + CSS + JS + Data inlined)      │        │
│  └──────────────────────────────────────────┘        │
│       │                                               │
│       ▼                                               │
│  ┌──────────────┐                                    │
│  │  AI Chat     │ ◄── LangChain Backend (optional)   │
│  └──────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

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

### Supported LLM Providers
Set `LLM_PROVIDER` env var to switch:
- `openai` (default) — needs `LLM_API_KEY`
- `deepseek` — needs `LLM_API_KEY` or openclaw.json config
- `mimo` — needs openclaw.json config

## Project Structure

```
portfolio/
├── backend/
│   ├── data/
│   │   ├── output/                # JSON artifacts (ingest source)
│   │   └── analytics.db           # SQLite (load_sql output)
│   └── scripts/
│       ├── process_data.cjs       # Data processor (Excel → JSON)
│       ├── predict_top50.py       # Top-50 meter predictions
│       └── predict_by_building.py # Building-level predictions
├── pipeline/                      # MLOps data pipeline
│   ├── logger.py                  # Structured JSON logging with run_id
│   ├── schema.py                  # Pandera schemas (data contracts)
│   ├── validators.py              # Checkpoint validation
│   ├── data_quality.py            # IQR/z-score outlier, missing-value
│   ├── sql_loader.py              # JSON → SQLite loader with indexes
│   ├── drift.py                   # KS-test / chi-square drift detection
│   └── orchestrator.py            # Stage-based pipeline runner
├── agent/                         # AI Agent (LangChain + FastAPI)
│   ├── agent_tools.py             # 14 JSON tools
│   ├── sql_tools.py               # 3 text-to-SQL tools
│   ├── agent_executor.py          # ReAct agent + system prompt
│   ├── multi_agent.py             # Planner → Executor → Synthesizer
│   ├── server.py                  # FastAPI with SSE streaming
│   ├── chart_generator.py         # ECharts option builder
│   ├── data_loader.py
│   └── config.py
├── tests/                         # Evaluation framework
│   ├── qa_pairs.json              # 25 QA test pairs
│   ├── test_data_quality.py       # Outlier / missing-value tests
│   ├── test_pipeline.py           # End-to-end pipeline tests
│   ├── test_agent_tools.py        # Agent tool smoke tests
│   ├── test_evaluator.py          # Evaluator unit tests
│   └── evaluate.py                # Tool accuracy + keyword recall scorer
├── docs/
│   ├── INTERVIEW_PREP.md          # HKT interview guide (GitHub)
│   └── CHEAT_SHEET.md             # One-page summary (local)
├── frontend/                      # 9-tab dashboard
│   ├── js/                        # 12 JS modules
│   ├── css/styles.css
│   ├── template.html              # Dashboard template
│   ├── build.cjs                  # Build script
│   └── dist/                      # Built dashboard
├── public/data/
│   └── dma_zones.geojson          # DMA zone boundaries
├── scripts/
│   └── mock_data_generator.py     # Demo data generator
├── reports/                       # Run summaries, drift reports, eval reports
├── logs/                          # Pipeline JSON logs
├── checkpoints/                   # Stage checkpoints (resume support)
└── package.json
```

## MLOps Pipeline

The `pipeline/` module turns raw JSON artifacts into a production-grade
data flow. Six stages, each with structured logging, schema validation,
and checkpoint support:

```bash
python pipeline/orchestrator.py --force   # run end-to-end
pytest tests/test_pipeline.py -v          # verify all stages pass
```

Stages:
1. **ingest** — read JSON outputs into typed DataFrames
2. **clean** — IQR outlier capping + missing-value interpolation
3. **detect_anomalies** — validate the anomaly artifact
4. **predict** — validate the forecast rows
5. **load_sql** — write to SQLite with indexes on `meterId`, `date`, `dma`
6. **drift** — KS-test (numeric) and chi-square (categorical) drift detection

## AI Agent

17 LangChain tools: 14 read from the JSON files, 3 query the SQLite
database directly via text-to-SQL. The system prompt teaches the model
when to use which category (aggregations → SQL, summarized data → JSON).

```bash
# Run the agent
cd agent
export LLM_API_KEY="..."
python server.py                 # streams at http://localhost:8000/api/chat
```

Multi-agent mode adds a Planner → Executor → Synthesizer chain (toggle
in the chat UI).

## Evaluation

```bash
pytest tests/ -v                 # 39 unit tests
python tests/evaluate.py         # 25 QA pairs, real LLM
```

The evaluator scores:
- **tool accuracy** — did it call the expected tool?
- **keyword recall** — fraction of expected keywords in the answer
- **latency** — end-to-end wall time
- **failure rate** — % of unanswered questions

Output: `reports/eval_per_qa.json` and `reports/eval_report.md`.

## Anomaly Detection Algorithm

The system uses a **14-day rolling window** approach:

1. Compute mean and standard deviation of the past 14 days
2. Calculate Z-score: `z = (current - mean) / std`
3. Apply tanh compression for score normalization: `score = tanh(z / 3)`
4. Classify based on thresholds:
   - **Spike**: `current > mean × 4` and `score > 0.5`
   - **Drop**: `current < mean × 0.3` and `score > 0.4`
   - **Zero**: `current = 0` and `mean > 1`
   - **Watch**: `current > mean × 1.5` and `score > 0.25`

## Prediction Model

Uses **scikit-learn LinearRegression** with feature engineering:
- Day-of-week encoding (cyclical)
- Rolling 7-day and 14-day averages
- Trend coefficient (linear time index)
- Seasonal decomposition residuals

Generates 7-day ahead forecasts with R² model scoring.

## License

MIT — see [LICENSE](LICENSE).

## Development

### Running with Docker

```bash
cp .env.example .env       # fill in LLM_API_KEY
docker compose up --build
# Dashboard: http://localhost:5173
# Agent:     http://localhost:8000/api/health
```

### Running locally on Windows

Use the `start_*.bat` scripts — they set the right env vars and dependencies automatically.

### Secret scanning

A pre-commit hook ([`.pre-commit-config.yaml`](.pre-commit-config.yaml)) runs **gitleaks** to block accidental commits of API keys.

```bash
pip install pre-commit
pre-commit install
```

GitHub also offers [native secret scanning](https://docs.github.com/en/code-security/secret-scanning/about-secret-scanning) — enable it in the repo's **Settings → Security** tab.
