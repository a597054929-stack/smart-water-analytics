# Architecture Overview

## System Design

This dashboard follows a **batch-processing pipeline** architecture: data is ingested from Excel files, processed by Node.js, enriched with Python ML predictions, and served as a self-contained HTML file with all CSS, JS, and data inlined.

### Why Single-File?

The production deployment target is a water utility operations team that needs to:
1. Open a dashboard without installing anything
2. Share it via messaging apps (Telegram, email)
3. View it on any device with a browser

A single 5MB HTML file achieves this. No server required for viewing.

## Data Flow

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Excel Files │───►│  process_data.cjs │───►│  JSON Outputs   │
│  (Daily)     │    │  (Node.js)        │    │  (17 files)     │
└─────────────┘    └──────────────────┘    └────────┬────────┘
                                                     │
                              ┌───────────────────────┤
                              │                       │
                              ▼                       ▼
                    ┌─────────────────┐    ┌──────────────────┐
                    │  predict_*.py    │    │  build.cjs        │
                    │  (scikit-learn)  │    │  (Assembly)       │
                    └────────┬────────┘    └────────┬─────────┘
                             │                      │
                             ▼                      ▼
                    ┌─────────────────┐    ┌──────────────────┐
                    │  predictions.*  │───►│  dashboard.html   │
                    │  (JSON)         │    │  (Self-contained) │
                    └─────────────────┘    └──────────────────┘
                                                    │
                                                    ▼
                                           ┌──────────────────┐
                                           │  AI Chat (Opt.)   │
                                           │  LangChain Server │
                                           └──────────────────┘
```

## Data Pipeline Stages

### Stage 1: Ingestion (`process_data.cjs`)

Reads daily Excel files containing hourly meter readings. Each Excel file represents one day of data for all meters.

**Processing steps:**
- Parse Excel → extract meter ID, hourly readings → sum to daily total (liters → m³)
- Cross-reference with reference database (meter metadata: DMA zone, building, property type)
- Filter initial reading anomalies (first-day spikes from meter installation)
- Aggregate by DMA zone, compute residential/non-residential splits
- Detect Top 20 meters per day
- Track rank changes over time
- Compute main-sub meter differences (NRW analysis)
- Fetch rainfall data from Open-Meteo API
- Build search index for meter lookup
- Generate Cotai calendar heatmap data

**Output:** 15 JSON files totaling ~10MB

### Stage 2: Prediction (`predict_*.py`)

Two prediction modules using scikit-learn:

**Top 50 Meters (`predict_top50.py`):**
- Selects top 50 meters by total consumption
- Features: day-of-week, rolling averages, trend
- Model: LinearRegression
- Output: 7-day forecast with R² score and trend direction

**Building Aggregation (`predict_by_building.py`):**
- Groups meters by building in Zone-3
- Aggregates consumption per building
- Same model architecture as meter-level
- Output: per-building 7-day forecast

### Stage 3: Assembly (`build.cjs`)

Combines everything into a single HTML file:
1. Copies JSON data files to `dist/data/`
2. Reads `template.html`
3. Inlines CSS (single file)
4. Inlines 12 JS modules in dependency order
5. Replaces data placeholders with fetch-based loading
6. Outputs `dashboard.html`

## Frontend Architecture

### Module System

12 JS modules loaded in order (dependencies first):

| Module | Responsibility |
|--------|---------------|
| `utils.js` | Constants, DMA colors, masking, chart helpers |
| `tabs.js` | Tab switching, date navigation, data refresh |
| `home.js` | Overview dashboard, KPIs, DMA cards |
| `trend.js` | DMA consumption trends with rainfall |
| `rank.js` | Top 20 ranking tracker over time |
| `diff.js` | Monthly main-sub meter difference |
| `anomaly.js` | Anomaly detection viewer with filters |
| `search.js` | Meter search by ID, contract, or building |
| `predict.js` | Prediction viewer (meter and building) |
| `map.js` | Leaflet geographic heatmap |
| `calendar.js` | Cotai non-residential calendar |
| `chat.js` | AI assistant floating chat widget |

### State Management

Global state via `window.D` (loaded data) and module-level variables:
- `selDate` — currently selected date
- `selDma` — currently selected DMA zone
- `charts` — ECharts instance registry
- `D` — main data object (all JSON data merged)
- `PRED` — meter predictions
- `PRED_BLD` — building predictions

### Chart System

All charts use ECharts 5 with dark theme. The `initChart(name, dom)` helper manages lifecycle (dispose old → create new). Charts resize on window resize via a global listener.

## AI Chat Integration (Optional)

The chat widget connects to a LangChain backend:

```
User Query → FastAPI Endpoint → LangChain Agent → Water Analytics Tools → Response
```

**Agent capabilities:**
- Query anomaly statistics by DMA and date range
- Retrieve Top 20 ranking history
- Generate chart specifications
- Compute NRW rates
- Summarize predictions

The AI backend is optional — the dashboard works fully without it.

## Deployment Options

1. **Static file** — Share `dashboard.html` directly (no server needed)
2. **Local server** — `npx serve frontend/dist` for development
3. **Telegram bot** — Auto-send updated dashboard to operations team
4. **Internal server** — Host behind VPN for remote access
