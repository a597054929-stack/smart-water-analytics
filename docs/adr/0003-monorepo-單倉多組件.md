# ADR-0003: 單一 monorepo 包含 agent / pipeline / frontend / data 四大組件

**狀態**: Accepted · **日期**: 2026-06-07

## Context

專案由四個明顯不同技術棧的組件組成：
- **agent/** (Python · LangChain · FastAPI) — AI 對話後端
- **pipeline/** (Python · Pandera · SQLite) — ETL 管道
- **frontend/** (Vanilla JS · ECharts · Leaflet) — Dashboard
- **backend/data/** (JSON · SQLite · Excel) — 資料層

候選方案：
- **多倉** (polyrepo): 每個組件獨立 repo，用 git submodule 或 package 互相依賴
- **單倉** (monorepo): 一個 repo 包含所有組件，共享 `requirements.txt`、`tests/`、根目錄 CI

## Decision

採用單倉結構，根目錄為入口。所有組件在同一個 git repo，共享：
- 根目錄 `requirements.txt` / `requirements.lock.txt`
- 根目錄 `.github/workflows/ci.yml`
- 根目錄 `tests/` (跨組件整合測試)
- 根目錄 `docs/`

## Consequences

### 正面
- ✅ **跨組件 refactor 容易** — 一次 PR 可以同時改 `pipeline/` 和 `agent/`
- ✅ **統一 CI** — 一個 workflow 跑所有測試，不必在 4 個 repo 之間同步版本
- ✅ **新人 onboarding 快** — 一個 `git clone` 拿到全部
- ✅ **共享版本約束** — `pyproject.toml` 一處定義，所有組件用同一份依賴
- ✅ **整合測試自然** — `tests/test_pipeline.py` 同時 import agent 和 pipeline

### 負面
- ❌ **耦合風險** — 不嚴格時，frontend 可能 import pipeline 內部模組
- ❌ **CI 全跑** — 改 frontend 也會跑 Python 測試（用 `paths-ignore` 緩解）
- ❌ **Tagging 模糊** — 無法給單一組件打版本 tag

### 緩解措施
- 設定 `.github/workflows/ci.yml` 用 `paths-ignore` 減少不必要的觸發
- 模組邊界靠目錄劃分（`agent/` 不 import `frontend/`，反之亦然）
- 用 `pyproject.toml` 的 `packages = ["agent", "pipeline", "scripts"]` 明確定義 Python package 邊界
- 若將來拆倉，git history 已經能乾淨分離（每個目錄變動獨立）

## 參考

- 根目錄結構：
  ```
  agent/         ← Python: LangChain backend
  pipeline/      ← Python: ETL + validation
  frontend/      ← JS: dashboard
  backend/data/  ← JSON + SQLite + Excel
  tests/         ← pytest，跨組件
  docs/          ← 文件
  ```
- 整合範例：`tests/test_pipeline.py` 同時測 pipeline 跑完後 agent 能用 SQL 查到結果
