# 术語字典

> **最後更新**：2026-06-08
> **維護者**：李志泉

本項目用到的所有"不常用"或"外行可能不懂"的技术詞。
面試前查、文件措辞參考、新同事上手都用得到。

按主題分類：每個詞給"英文全称 / 中文 / 解释 / 項目裡的例子"。

---

## 1. 數據庫 / 數據仓庫

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **OLAP** | Online Analytical Processing | 联機分析處理 | 面向"讀很多、分析多"的設計。跟 OLTP 相反。**特征**：反 3NF、预聚合、批量載入 | `analytics.db` 就是 OLAP——10 張表，JSON 欄位，故意不規范化 |
| **OLTP** | Online Transaction Processing | 联機事務處理 | 面向"頻繁增删改"的設計。**特征**：严格 3NF、並發安全、行級鎖 | （本項目**不**是 OLTP） |
| **1NF** | First Normal Form | 第一范式 | 欄位值必须是"原子"的（不可再分） | 10 張表都滿足 |
| **2NF** | Second Normal Form | 第二范式 | 在 1NF 基礎上，非主键欄位必须"完全依賴"主键，不能只依賴一部分 | 滿足 |
| **3NF** | Third Normal Form | 第三范式 | 在 2NF 基礎上，非主键欄位不能"传递依賴"其他非主键欄位 | **故意违反**——為了 OLAP 效能 |
| **DDL** | Data Definition Language | 數據定義語言 | `CREATE TABLE` / `DROP TABLE` 這種定義 schema 的 SQL | Stage 5 `load_sql` 跑 DDL |
| **DML** | Data Manipulation Language | 數據操作語言 | `INSERT` / `UPDATE` / `DELETE` 這種改數據的 SQL | text-to-SQL 工具**禁止** DML |
| **ACID** | Atomicity, Consistency, Isolation, Durability | 事務四特性 | 數據庫事務的四個保证——原子/一致/隔离/持久 | SQLite 單檔案滿足 ACID |
| **DBA** | Database Administrator | 數據庫管理員 | 維護數據庫的人 | （單人項目，没這角色） |
| **Schema** | - | 表結構 | 一張表的"骨架"——列名、類型、約束 | `pipeline/schema.py` 裡 10 個 Pandera schema |
| **Migration** | - | 迁移 | schema 從版本 A 變到版本 B 的過程 | （**当前没有** migration 工具） |
| **Alembic** | - | - | SQLAlchemy 的 migration 工具 | （**未引入**——可以做加分项） |
| **Index** | - | 索引 | 數據庫的"目錄"，加速查找 | （**当前没建**——`meter_daily` 表查 (meterId, date) 應该有 index） |

---

## 2. MLOps / 數據工程

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **MLOps** | Machine Learning Operations | 機器學习運維 | 把 ML 模型從"實驗室"搬到"生產"的過程。包含训练、部署、監察、迭代 | 整個 pipeline 7 stage 都是 MLOps |
| **Pipeline** | - | 管線 / 管道 | 數據從 A 流到 B 的處理鏈 | `pipeline/orchestrator.py` 7 stage 串成 pipeline |
| **Stage** | - | 階段 | pipeline 裡的一步 | ingest / clean / detect / ... / data_health |
| **Checkpoint** | - | 检查點 | 把"当前進度"存盘，崩了能續跑 | `checkpoints/stage_*.json` |
| **Idempotent** | - | 幂等 | 跑 N 次和跑 1 次效果一样 | pipeline **幂等**——重跑出同样 DB |
| **ETL** | Extract, Transform, Load | 抽取-轉換-載入 | 經典數據流程：抽出來、轉換、灌進去 | converter 乾的就是 ETL |
| **ELT** | Extract, Load, Transform | 抽取-載入-轉換 | 變體：先灌進去再轉換（靠 SQL 算） | （項目是 ETL，不是 ELT） |
| **Pandera** | - | - | Python 的 dataframe 校驗庫（類似 pydantic 但對 dataframe） | `pipeline/schema.py` 用它做邊界校驗 |
| **Drift** | - | 漂移 | 數據分布随時間變化 | `pipeline/drift.py` 用 KS / 卡方检測 |
| **KS test** | Kolmogorov-Smirnov test | - | 检驗兩個分布是否相同 | drift.py 對數值列用 |
| **卡方检驗** | Chi-square test | - | 检驗分類變量比例是否變了 | drift.py 對分類列用 |
| **Baseline** | - | 基線 | "正常"狀態的快照，用來對比"现在" | 第一次跑 drift 時自動存 |
| **Z-score** | - | 標準分數 | 一個數偏离均值几個標準差。绝對值 > 3 通常算異常 | data_health 用它找單表異常 |
| **IQR** | Interquartile Range | 四分位距 | Q3 - Q1，中段 50% 數據的寬度 | clean stage 用 IQR 缩尾 |
| **Tanh** | Hyperbolic tangent | 雙曲正切 | 把任意數压到 (-1, 1) 的函數 | 異常分數用 tanh 壓縮 |
| **Rolling window** | - | 滾動視窗 | "最近 N 天/小時"這種滑動時間窗 | 異常检測用 14 天滾動 |
| **Cap** | - | 上限 | 數據超過這個值就视為誤值 | 4000 m³/日 cap |

---

## 3. AI Agent / LLM

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **LLM** | Large Language Model | 大語言模型 | 像 Claude、GPT 那種大模型 | agent 調的就是 LLM |
| **Prompt** | - | 提示詞 | 喂給 LLM 的文字指令 | Planner / Synthesizer 都有專門的 prompt |
| **ReAct** | Reasoning + Acting | 推理+行動 | 一種 agent 模式：think → act → observe → repeat | 老 agent 用的就是 ReAct |
| **Agent** | - | 智能體 | LLM 加上"能調工具"的循環 | `agent/server.py` 是入口 |
| **MCP** | Model Context Protocol | 模型上下文协議 | 让 LLM 調外部工具的標準协議 | `markitdown` MCP server |
| **SSE** | Server-Sent Events | - | 服務器單向推送數據流（HTTP 長連接） | `/api/chat` 用 SSE 流式傳回 |
| **Text-to-SQL** | - | 文字轉 SQL | LLM 把自然語言問題轉成 SQL | `agent/sql_tools.py` 乾的活 |
| **Hallucination** | - | 幻覺 | LLM 编造不存在的"事實" | 三層容錯防的就是這個 |
| **Tool calling** | - | 工具調用 | LLM 不直接回答，而是選一個工具跑 | Planner 输出 JSON 計劃，Executor 跑 |
| **System prompt** | - | 系統提示詞 | LLM 的"人設"——告诉它扮演什麼角色 | `PLANNER_PROMPT` / `SYNTHESIZER_PROMPT` |
| **Context window** | - | 上下文視窗 | LLM 一次能"看"多少 token | mimo-v2.5-pro 是 1M |
| **Reasoning effort** | - | 推理力度 | LLM "想多久" | `mimo_reasoning_effort = "high"` |
| **Trace ID** | - | 追踪 ID | 一個請求的"身份证"——所有記錄帶同一個 ID | 三層容錯裡提到 |
| **Temperature** | - | 溫度 | 控制 LLM 输出的随機性（0 = 確定性，1 = 随機） | Planner 用 temperature=0 |
| **RAG** | Retrieval Augmented Generation | 检索增強生成 | LLM 回答前先查相關資料 | （**項目没用**——純工具調用） |

---

## 4. 前端 / Web

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **SPA** | Single Page Application | 單頁應用 | 整個應用在一個 HTML 裡，不刷新頁面 | `dashboard.html` 5MB 單檔案 |
| **CDN** | Content Delivery Network | 內容分發網络 | 把靜态資源放全球各地加速访問 | （dashboard 没 CDN——全內联） |
| **ECharts** | - | - | 百度開源圖表庫 | 仪表盘所有圖都用 ECharts |
| **Leaflet** | - | - | 開源地圖庫 | 仪表盘 DMA 地圖 |
| **Bundle** | - | 打包 | 把多個檔案合並成一個 | `all_data.json` 是一個 bundle |
| **Inlining** | - | 內联 | 把 CSS/JS/数据塞进 HTML 本身 | dashboard.html 全內联（~5MB） |
| **Endpoint** | - | 端點 | URL 路徑——一個 API 入口 | `/api/chat` / `/api/health` |
| **Mock** | - | 模拟 | 假數據，用於開發/測試 | 500 表 125 天的合成數據 |
| **Synthetic data** | - | 合成數據 | 人工造的數據，不是真采集的 | `mock_data_generator.py` 造的就是 |
| **Real data** | - | 真實數據 | 真采集的數據 | 9,963 表 151 天的澳門水務數據 |

---

## 5. Python / 编程

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **venv** | Virtual Environment | 虛拟環境 | 隔离的 Python 環境 | 項目根有 `venv/` 目錄 |
| **Wheel** | - | - | Python 的预編譯包格式（`.whl`） | pip 裝的就是 wheel |
| **Coerce** | - | 強制轉換 | 類型不匹配時自動轉 | Pandera `coerce=True` |
| **Type hint** | - | 類型提示 | `def foo(x: int) -> str:` 裡的類型標注 | 項目用了但不全 |
| **Lambda** | - | 匿名函數 | 一行的小函數 | pandas 操作裡常見 |
| **Decorator** | - | 裝饰器 | `@something` 加在函數上面 | FastAPI `@app.get(...)` |
| **Dict** | Dictionary | 字典 | Python 的 key-value 數據結構 | `artifacts: dict[str, pd.DataFrame]` |
| **JSON** | JavaScript Object Notation | - | 一種文字數據格式 | 21 個產物的格式 |
| **Pickle** | - | - | Python 對象序列化（不跨語言） | （項目**没用**——用 JSON） |
| **Pinned version** | - | 固定版本 | `package==1.2.3` 而不是 `>=1.2.0` | requirements.txt 用了 `>=`（**應改成** `==`） |
| **AST** | Abstract Syntax Tree | 抽象語法樹 | 代碼的樹形表示 | 一些 lint 工具用 |

---

## 6. 機器學习

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **R²** | R-squared / Coefficient of Determination | 決定系數 | 0~1，模型對數據的解释力。1 = 完美，0 = 等於预測均值 | LightGBM 0.84 vs 線性 0.05 |
| **RMSE** | Root Mean Square Error | 均方根誤差 | 预測誤差的"平均"——但放大了大誤差 | Stage 3 残差分析输出 RMSE |
| **MAE** | Mean Absolute Error | 平均绝對誤差 | 预測誤差的"平均"——不放大 | Stage 3 也输出 |
| **Feature** | - | 特征 | 喂給模型的输入變量 | 13 個手搓特征（DOW、rolling 7 等） |
| **Feature engineering** | - | 特征工程 | 把原始數據加工成"好特征" | 13 個特征就是 engineer 出來的 |
| **Train/test split** | - | 训练/測試集劃分 | 80% 训练 + 20% 測試，避免"作弊" | （腳本裡應该有） |
| **LightGBM** | - | - | 一種梯度提升樹模型 | R² 0.84 的功臣 |
| **Linear regression** | - | 線性回归 | 假設 y = ax + b 的簡單模型 | R² 0.05，被 LightGBM 取代 |
| **Hyperparameter** | - | 超參數 | 模型"設定"——不是學出來的，是人設的 | LightGBM 的 max_depth、num_leaves 等 |
| **Time series** | - | 時序數據 | 按時間順序的數據點 | 每日用水量就是時序 |
| **Forecast** | - | 预測 | 预測未來 N 步 | 7 天 forecast |
| **Baseline model** | - | 基線模型 | 簡單的"占位"模型，用來對比 | 線性回归就是 LightGBM 的 baseline |

---

## 7. 軟件工程

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **Tech stack** | - | 技术栈 | 一個項目用到的所有技术 | Python + LangChain + FastAPI + SQLite + ... |
| **Trade-off** | - | 取舍 | 任何決策都有得有失 | 3NF 取舍：join 成本 vs 讀速度 |
| **CI/CD** | Continuous Integration / Deployment | 持續集成/部署 | 改完代碼自動測、自動發 | `.github/workflows/ci.yml` |
| **Unit test** | - | 單元測試 | 測單個函數 | 104 個 pytest |
| **Integration test** | - | 集成測試 | 測多個組件配合 | （**当前缺**） |
| **End-to-end test** | - | 端到端測試 | 模拟用戶操作測全鏈路 | （**当前缺**） |
| **Smoke test** | - | 冒烟測試 | 跑一下看會不會崩 | （建議加） |
| **Refactor** | - | 重構 | 不改行為，只改結構 | （項目目前穩） |
| **Tech debt** | Technical Debt | 技术债 | "先這样以後改"——累积的妥协 | 缺 `pyproject.toml`、缺 migration |
| **Dead code** | - | 死代碼 | 寫了但没人用的代碼 | `predictions_building` 表（寫過但没讀） |
| **Yak shaving** | - | 牦牛剃毛 | 做着做着跑偏了，做了一堆前置工作 | （要小心避免） |
| **Robust** | - | 健壯 | 錯誤输入不崩 | Stage 缺檔案時 warning 而不是 crash |
| **Linting** | - | 靜态检查 | 不跑代碼，只看代碼"風格"對不對 | ruff / flake8 |
| **Pre-commit hook** | - | - | 提交代碼前自動跑 | `.pre-commit-config.yaml` 跑 gitleaks |
| **Schema migration** | - | - | 數據庫 schema 變更管理 | （**当前缺**——用 Alembic 补） |

---

## 8. 數據 / 統計

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **Aggregate** | - | 聚合 | 把多行算成一個數（sum / avg / count） | 每日 DMA 總量 = aggregate |
| **Anomaly** | - | 異常 | "不正常"的數據點 | 4 種類型：spike / drop / zero / watch |
| **Outlier** | - | 离群點 | 偏离群體大部分的點 | z-score > 3 算 outlier |
| **Distribution** | - | 分布 | 數據"長什麼样"——頻率/概率 | drift 比较的是 distribution |
| **Variance** | - | 方差 | 數據离散程度 | drift 比较 variance 變化 |
| **Mean** | - | 均值 | 平均數 | rolling_7_mean |
| **Std / SD** | Standard Deviation | 標準差 | 數據圍繞均值的"散開"程度 | rolling_7_std |
| **Sample** | - | 樣本 | 一份數據 | "9,963 表"是 9963 個 sample |
| **Confidence interval** | - | 置信區間 | "真實值有 95% 概率落在這個區間" | （項目没顯式用） |
| **Hypothesis test** | - | 假設检驗 | "兩組數據是不是同分布" | KS test / 卡方 |

---

## 9. 網络 / 协議

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **HTTP** | - | - | 網络协議 | FastAPI 跑 HTTP |
| **API** | Application Programming Interface | 應用编程介面 | 軟件之間的"合約" | `/api/chat` 是 API |
| **REST** | - | - | 一種 API 設計風格 | FastAPI 算 RESTful |
| **JSON-RPC** | - | - | 用 JSON 传數據的 RPC 协議 | MCP 用的是 JSON-RPC |
| **stdio** | Standard Input/Output | 標準输入输出 | 進程間通訊（用 stdin/stdout） | MCP server 走 stdio |
| **OAuth** | - | - | 第三方授權协議 | （**未用**——Mimo 是 API key） |
| **JWT** | JSON Web Token | - | 一種 token 格式 | （**未用**——單用戶） |
| **CORS** | Cross-Origin Resource Sharing | 跨域資源共享 | 浏览器安全策略 | （**未配**——同源访問） |

---

## 10. 部署 / 運維

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **Container** | - | 容器 | 隔离的運行環境 | Docker |
| **Docker Compose** | - | - | 多容器编排 | `docker-compose.yml` |
| **Volume** | - | 卷 | 容器外持久化存储 | `data:` volume 挂载 |
| **Health check** | - | 健康檢查 | "/api/health" 端點 | ✅ 已有 |
| **Observability** | - | 可觀測性 | 記錄 + 指標 + 追踪 | （**当前弱**——只有 stage 記錄） |
| **Metrics** | - | 指標 | 數字化的運行時數據 | （**缺**） |
| **Tracing** | - | 追踪 | 跨服務追踪一個請求 | （**缺**） |
| **Structured logging** | - | 結構化記錄 | JSON 格式的記錄（不是 print 字串） | （建議升級 structlog） |
| **SLO** | Service Level Objective | 服務等級目標 | "99.9% 時間內可用" 這種承诺 | （**未定義**） |
| **SLA** | Service Level Agreement | 服務等級协議 | 跟客戶的合約承诺 | （**未签**） |
| **Oncall** | - | 值班 | "線上挂了谁來處理" | （**單人**——你自己） |

---

## 11. 文件 / 流程

| 术語 | 全称 | 中文 | 解释 | 項目例子 |
|------|------|------|------|---------|
| **ADR** | Architecture Decision Record | 架構決策記錄 | "為什麼這麼設計" 的文件 | （**当前缺**） |
| **README** | - | - | 項目"門面"——快速上手 | ✅ 有 |
| **CHANGELOG** | - | - | 版本變更歷史 | ✅ 39KB |
| **Runbook** | - | 運行手册 | "線上挂了怎麼修" | （**当前缺**） |
| **RFC** | Request for Comments | - | "我想這麼改，大家來 review" | （**未用流程**） |
| **PR / MR** | Pull Request / Merge Request | - | "改完了，請合入" | （單人項目，**没真用**） |
| **Code review** | - | 代碼審查 | 同事帮你看代碼 | （單人項目，**没真用**） |
| **Tech radar** | - | 技术雷達 | "哪些技术我們用 / 試用 / 不用" | （**未做**） |

---

## 12. 我之前對話裡用到的"非术語"詞

| 詞 | 解释 |
|----|------|
| **抓手** | 意思"能拿來說事的點"——比如"R² 0.84 是個抓手" |
| **金句** | 面試時直接能背出來的漂亮話 |
| **工程感** | "看起來像中高級工程師做的"那種质感 |
| **Demo 痕迹** | "看着像個人項目不像生產"的那種信號 |
| **现成的** | 不用自己造，用现成的 |
| **抓手 vs 亮點** | 几乎同義，但"抓手"更強調"能引出問題深入聊" |
| **杀雞用牛刀** | `--full` 修 1 個數據點 = 杀雞用牛刀 |
| **不見兔子不撒鹰** | 没明確收益前不動手（先做 ROI 高的） |
| **過度工程** | 做了超出需要的事情（比如給單用戶加 JWT） |
| **副作用** | 改一個东西導致別處出問題（schema 改動會級联） |
| **ROI** | Return on Investment 投入產出比 |

---

## 怎麼用這本字典

| 場景 | 用法 |
|------|------|
| 面試被問到不熟的詞 | 查這裡 |
| 寫 README/CHANGELOG 時的措辞參考 | 查"工程感"那几條 |
| 改代碼時考虑"會不會破壞什麼" | 查"Trade-off"、"死代碼"、"過度工程" |
| 評估"该不该做某件事" | 查"ROI"、"復雜度" |
| 新同事上手 | 让他們先讀這個 |
