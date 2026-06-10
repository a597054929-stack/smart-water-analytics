-- 4-Layer Time-Granularity Schema (v2, 2026-06-09)
-- Replaces the v1 schema where data was split across:
--   - backend/data/output_real/*.json (10+ files, ~2.8GB)
--   - analytics_real.db (10 tables, ~350MB)
-- New design: ALL data goes into a single SQLite file, organized by
-- time granularity. JSON files are eliminated (or only used as
-- build-time export for the frontend bundle).
--
-- Layers:
--   L1: Point-in-time (permanent / event-triggered)
--   L2: Daily Aggregated (151 days)
--   L3: Weekly / Monthly (<= 5 months)
--   L4: Hourly Raw (30 days, ~15M rows)

-- ── L1: Point-in-time ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS meters (
    meterId TEXT PRIMARY KEY,
    id TEXT,
    contractId TEXT,
    propertyType TEXT,
    isResidential INTEGER,
    buildingName TEXT,
    dma TEXT,
    supplyMode TEXT,
    mainCode TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    meterId TEXT,
    date TEXT,
    predicted REAL,
    lower REAL,
    upper REAL,
    PRIMARY KEY (meterId, date)
);

CREATE TABLE IF NOT EXISTS predictions_building (
    building TEXT,
    date TEXT,
    predicted REAL,
    lower REAL,
    upper REAL,
    PRIMARY KEY (building, date)
);

CREATE TABLE IF NOT EXISTS rank_changes (
    meterId TEXT PRIMARY KEY,
    contractId TEXT,
    buildingName TEXT,
    dma TEXT,
    propertyType TEXT,
    daysInTop20 INTEGER,
    avgTotal REAL,
    avgRank REAL,
    trend TEXT
);

CREATE TABLE IF NOT EXISTS anomalies (
    date TEXT,
    meterId TEXT,
    total REAL,
    contractId TEXT,
    dma TEXT,
    buildingName TEXT,
    reason TEXT,
    type TEXT,
    anomalyScore REAL,
    pastMean REAL,
    pastStd REAL,
    windowDays INTEGER,
    originalType TEXT,
    PRIMARY KEY (date, meterId)
);

CREATE TABLE IF NOT EXISTS data_errors (
    ts TEXT,
    meterId TEXT,
    date TEXT,
    reason TEXT,
    rawValue REAL
);

CREATE TABLE IF NOT EXISTS corrections (
    meterId TEXT,
    startDate TEXT,
    endDate TEXT,
    factor REAL,
    reason TEXT
);

-- ── L2: Daily Aggregated ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS daily_dma (
    date TEXT,
    dma TEXT,
    total REAL,
    residential REAL,
    nonResidential REAL,
    resCount INTEGER,
    nonResCount INTEGER,
    meterCount INTEGER,
    rain TEXT,
    PRIMARY KEY (date, dma)
);

CREATE TABLE IF NOT EXISTS meter_daily (
    meterId TEXT,
    date TEXT,
    total REAL,
    PRIMARY KEY (meterId, date)
);

-- ── L3: Weekly / Monthly ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS weekly (
    weekStart TEXT PRIMARY KEY,
    weekEnd TEXT,
    label TEXT,
    dates TEXT,         -- JSON-encoded array of dates
    totalByDma TEXT,    -- JSON-encoded {dma: total}
    grandTotal REAL,
    weekdayAvg REAL,
    weekendAvg REAL,
    wdByDmaRes TEXT,    -- JSON-encoded {dma: {res, nonRes, ...}}
    rain REAL,
    dailyTotals TEXT    -- JSON-encoded [{date, total}, ...]
);

CREATE TABLE IF NOT EXISTS monthly_diff (
    month TEXT,
    mainMeterId TEXT,
    mainContractId TEXT,
    mainBuilding TEXT,
    dma TEXT,
    subs TEXT,         -- JSON-encoded [{meterId, ...}]
    mainTotal REAL,
    subsTotal REAL,
    diff REAL,
    diffPercent REAL,
    PRIMARY KEY (month, mainMeterId)
);

-- ── L4: Hourly Raw ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS hourly_meter (
    meterId TEXT,
    datetime TEXT,
    consumption REAL,
    reading REAL
);

CREATE INDEX IF NOT EXISTS idx_hourly_meter_datetime
    ON hourly_meter(datetime);
CREATE INDEX IF NOT EXISTS idx_hourly_meter_meterId
    ON hourly_meter(meterId);

-- ── Search index (helper, L1) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS search_index (
    id TEXT,
    contract TEXT,
    building TEXT,
    dma TEXT,
    type TEXT
);
