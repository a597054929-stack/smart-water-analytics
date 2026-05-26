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
| AI Backend | LangChain + FastAPI (optional) |
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

### 1. Generate Demo Data
```bash
python scripts/mock_data_generator.py
```

### 2. Build Dashboard
```bash
npm install
npm run build
```

### 3. Preview
```bash
npm run serve
# Opens at http://localhost:5173
```

### One-Command Demo
```bash
npm run demo
```

## Project Structure

```
portfolio/
├── backend/
│   └── scripts/
│       ├── process_data.cjs      # Data processor (Excel → JSON)
│       ├── predict_top50.py      # Top-50 meter predictions
│       └── predict_by_building.py # Building-level predictions
├── frontend/
│   ├── js/                       # 12 JS modules (tabs, charts, etc.)
│   ├── css/styles.css
│   ├── template.html             # Dashboard template
│   ├── build.cjs                 # Build script
│   └── dist/                     # Built dashboard
├── public/data/
│   └── dma_zones.geojson         # DMA zone boundaries
├── scripts/
│   └── mock_data_generator.py    # Demo data generator
└── package.json
```

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

This project was developed as a Final Year Project. The code is available for portfolio review purposes.
