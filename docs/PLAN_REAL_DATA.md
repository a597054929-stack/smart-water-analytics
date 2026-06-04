# 真实数据接入 — 完整实施计划

> 目标：把 `workspace/data/` 下的真实澳门水务数据接入 Smart Water Analytics 管道。

---

## 一、数据源概况

| 目录 | 内容 | 文件数 | 大小 | 时间范围 |
|------|------|--------|------|----------|
| `data/MACAU-reference` | 水表参考数据（26列） | 10 | 1.6MB | — |
| `data/Macau 2026` | 每日用水（每天一个） | 151 | 2.2GB | 2026-01 ~ 2026-05 |
| `data/Macau 2025` | 每日用水（3天合批） | 83 | 1.5GB | 2025-05 |

**关键列（Macau 2026）：**
- 錶位編號（水表ID）、抄錶日期、用水量、讀值
- 分區、建物、合同號碼

**参考文件列：**
- 錶位編號、合同編號、DMA分區、物業類型、建築物名稱、主錶錶碼、供水模式

---

## 二、核心问题：数据量

| 粒度 | 记录数 | JSON 大小 | 可行性 |
|------|--------|-----------|--------|
| 小时级（原始） | 15M 行 | ~1.2GB | 不适合 JSON |
| **日级（聚合后）** | **627K 行** | **~2.5MB** | 完全可用 |
| 只保留仪表盘需要的 | ~100K 行 | **~2MB** | 最优 |

### 方案：双粒度存储

```
Excel 原始数据（小时级）
    │
    ├─→ 日级聚合 → JSON 文件（~2MB）
    │   用途：Agent 工具、前端看板、异常检测、预测
    │
    └─→ 小时级保留 → SQLite hourly_meter 表（15M 行）
        用途：持续用水检测、夜间分析、慢漏检测、Agent SQL 查询
```

---

## 三、文件级改动清单

### 3.1 新增文件

| 文件 | 作用 | 说明 |
|------|------|------|
| `scripts/real_data_converter.py` | Excel → JSON 转换器 | 核心：读 Excel，输出 14 个 JSON |
| `scripts/setup_real_data.bat` | 一键运行转换器 | 可选 |

### 3.2 修改文件

| 文件 | 改动 | 原因 |
|------|------|------|
| `pipeline/schema.py` | VALID_DMAS 增加真实区域名 | 澳門低區等中文 DMA 名 |
| `pipeline/sql_loader.py` | 增加 hourly_meter 表加载 | 小时级数据入库 |
| `pipeline/orchestrator.py` | stage_ingest 支持跳过不存在的文件 | 不是所有 JSON 都必须存在 |
| `backend/scripts/process_data.cjs` | 可选：增加 Python 转换器路径 | 两套数据源共存 |
| `frontend/build.cjs` | 不再复制 all_data.json | 改为复制独立 JSON 文件 |
| `frontend/js/tabs.js` | loadData() 改为并行加载多个 JSON | 不再依赖 all_data.json |

### 3.3 删除的文件

| 文件 | 原因 |
|------|------|
| `all_data.json` | 180MB，不可用。改为独立 JSON 按需加载 |
| `meter_daily.json`（独立文件） | 日级数据存 SQLite 即可，不生成独立 JSON |
| `meterMonthly`（在 all_data 中） | 同上 |

### 3.4 不改动的文件

| 文件 | 原因 |
|------|------|
| `agent/agent_tools.py` | JSON 工具不变，SQL 工具不变 |
| `agent/agent_executor.py` | 系统提示不变 |
| `agent/tool_router.py` | 关键词路由不变 |
| `pipeline/data_quality.py` | 异常检测逻辑不变 |
| `pipeline/drift.py` | 漂移检测不变 |
| `tests/*` | 测试不变（mock 数据仍可用） |

---

## 四、转换器设计（real_data_converter.py）

### 输入 → 输出映射

```
MACAU-reference/*.xlsx
    ↓
meter_info.json = {
    "752960": {
        "dma": "澳門低區",
        "propertyType": "001:Residential",
        "isResidential": true,
        "contractId": "3390691",
        "buildingName": "政府長者公寓",
        "supplyMode": "DIRECT",
        "mainCode": "752961"
    }
}

Macau 2026/*.xlsx (hourly)
    ↓ 按水表+日期聚合
meter_daily (SQLite) = {meterId, date, total, readings: {hour: value}}

    ↓ 进一步聚合
daily_dma.json = [{date, dmas: {"澳門低區": {total, residential, ...}}}]
weekly.json = [{weekStart, weekEnd, totalByDma: {"澳門低區": ...}}]
daily_top20.json = [{date, top20: [...]}]
rank_changes.json = [{meterId, daysInTop20, ...}]
monthly_main_sub_diff.json = [{month, diffs: [...]}]
search_index.json = [{id, contract, building, dma, type}]
cotai_calendar.json = [{date, items: [...]}]
available_dates.json = ["2026-01-01", ...]
anomalies.json = [...] (管道检测生成)
predictions.json = [...] (指数平滑生成)
predictions_fitted.json = [...] (拆分的拟合值)
predictions_by_building.json = [...] (按建筑聚合预测)
```

### 关键转换逻辑

#### 4.1 水表 ID 映射

```
参考文件：錶位編號 = 752960 (整数)
用水文件：錶位編號 = 105825 (整数)

参考文件用 錶碼 (条码) 做主分表关联：
  主錶錶碼 = I23BI017070 → 对应錶碼 = I23BI017070 的水表

映射步骤：
1. 从参考文件建立：錶碼 → 錶位編號 的映射
2. 从参考文件建立：錶位編號 → 主錶錶碼 的映射
3. 主錶錶碼 → 通过錶碼映射找到对应的主表錶位編號
```

#### 4.2 DMA 区域处理

```
参考文件只有一个区域：DMA分區 = "澳門低區"
管道原来有 5 个区域：Zone-1/2/3/4/Unclassified

方案：保留真实区域名，更新 schema
  VALID_DMAS = ["Zone-1","Zone-2","Zone-3","Zone-4","Unclassified",
                "澳門低區","路氹新城","氹仔","澳門半島",...]
```

#### 4.3 物业类型映射

```
真实类型 → 管道类型映射：
  001:住宅 → 001:Residential
  018:大廈內公共用水 → 013:Public Facility
  019:其他店舖 → 002:Commercial
  022:餐廳酒樓 → 004:Restaurant
  048:醫療衛生 → 009:Healthcare
  049:老人福利 → 009:Healthcare
  058:食水總錶 → 005:Office (主表)
  065:消防系統 → 012:Fire System
```

#### 4.4 异常检测

```
复用管道 data_quality.py 逻辑：
1. Z-score > 3 标记异常
2. 滚动窗口（7天）检测局部异常
3. 零读数检测
4. 输出 anomalies.json
```

#### 4.5 预测

```
复用管道预测逻辑：
1. 取 Top-50 用水量最高的水表
2. 指数平滑 7 天预测
3. 拆分：predictions.json + predictions_fitted.json
```

---

## 五、前端改造

### 当前：单文件加载

```javascript
// loadData() — 当前
fetch('data/all_data.json').then(r => r.json())  // 180MB !!!
```

### 改为：并行加载独立文件

```javascript
// loadData() — 改后
Promise.all([
  fetch('data/daily_dma.json').then(r => r.json()),
  fetch('data/daily_top20.json').then(r => r.json()),
  fetch('data/anomalies.json').then(r => r.json()),
  fetch('data/rank_changes.json').then(r => r.json()),
  fetch('data/weekly.json').then(r => r.json()),
  fetch('data/meter_info.json').then(r => r.json()),
  fetch('data/available_dates.json').then(r => r.json()),
  fetch('data/predictions.json').then(r => r.json()),
  fetch('data/predictions_by_building.json').then(r => r.json()),
]).then(([dma, top20, anomalies, rank, weekly, meters, dates, pred, predBld]) => {
  window.D = {
    dma, top20, anomalies, rank, weekly,
    dates,
    // 需要从其他文件补充的字段
    search: [], // 从 search_index.json 加载
    diff: [],   // 从 monthly_main_sub_diff.json 加载
    cotai: [],  // 从 cotai_calendar.json 加载
    trend: dma, // 复用 daily_dma
    top20dma: buildTop20ByDma(top20), // 前端计算
    meterMonthly: {}, // 按需从 SQLite 查询
    meterDaily: {},   // 按需从 SQLite 查询
  };
  renderHome();
});
```

**总下载量**：~2MB（vs 之前的 180MB）

### 前端改动范围

| JS 文件 | 改动 | 说明 |
|---------|------|------|
| `tabs.js` | loadData() 重构 | 并行加载多个 JSON |
| `build.cjs` | 复制 12 个独立 JSON 而非 all_data.json | 构建脚本 |
| 其他 JS | **不改** | D 对象的字段名保持一致 |

---

## 六、SQLite 小时表

```sql
CREATE TABLE hourly_meter (
    meterId TEXT,
    datetime TEXT,     -- YYYY-MM-DD HH:00
    consumption REAL,  -- 小时用水量
    reading REAL       -- 表读数
);
CREATE INDEX idx_hourly_meter ON hourly_meter(meterId, datetime);
```

用途：
- Agent SQL 工具查询：`SELECT meterId, datetime, consumption FROM hourly_meter WHERE meterId='752960' AND datetime LIKE '2026-03%'`
- 持续用水检测：`SELECT meterId, date, COUNT(*) as hours FROM hourly_meter WHERE consumption > 0 GROUP BY meterId, date HAVING hours >= 48`
- 夜间高峰分析：`SELECT meterId, SUM(consumption) as night_total FROM hourly_meter WHERE CAST(substr(datetime, 12, 2) AS INTEGER) BETWEEN 0 AND 5 GROUP BY meterId`

---

## 七、实施步骤

### Step 1: 更新 Schema（低风险）
- schema.py: VALID_DMAS 增加中文区域名
- schema.py: VALID_PROPERTY_TYPES 增加真实物业类型
- 增加 hourly_meter Schema

### Step 2: 写转换器（核心）
- scripts/real_data_converter.py
- 读 Excel → 输出 14 个 JSON
- 不生成 all_data.json、meter_daily.json（独立文件）

### Step 3: 更新 SQL Loader
- sql_loader.py: 增加 load_hourly_meter()
- sql_loader.py: load_all() 增加小时表
- sql_loader.py: 跳过不存在的 JSON 文件

### Step 4: 更新前端
- build.cjs: 复制 12 个独立 JSON
- tabs.js: loadData() 并行加载

### Step 5: 更新 Pipeline
- orchestrator.py: stage_ingest 容错（文件可选）
- 重新生成 mock 数据验证

### Step 6: 验证
- 运行转换器
- 运行管道
- 运行测试
- 启动 Agent，测试 SQL 查询小时数据
- 启动前端，验证看板正常

---

## 八、数据范围决策

| 选项 | 数据量 | 适合场景 |
|------|--------|---------|
| A: 全量 2026 (151天) | 627K 日级 + 15M 小时级 | 完整演示 |
| B: 最近 60 天 | 250K 日级 + 6M 小时级 | 轻量演示 |
| C: 最近 30 天 | 125K 日级 + 3M 小时级 | 快速验证 |

**建议**：先用 **Option C（30天）** 跑通全流程，确认没问题后再扩展到全量。

---

## 九、风险点

| 风险 | 影响 | 缓解 |
|------|------|------|
| DMA 区域只有一个 | Agent 区域筛选功能弱化 | 按物业类型/建筑分组替代 |
| 水表 ID 格式不同 | 管道 Schema 验证失败 | 更新 regex 匹配 |
| 主分表关联复杂 | 錶碼→錶位編號 映射可能出错 | 转换器做完整性检查 |
| 前端改动 | 可能引入 bug | 保留 mock 数据可切换 |
| 小时数据量大 | SQLite 写入慢 | 批量插入 + 事务 |

---

## 十、完成后的效果

```
面试演示：
"这是澳门真实水务数据，1831个水表，151天的小时级读数。
 我的管道把它转成双粒度存储：日级 JSON 用于快速查询和可视化，
 小时级存 SQLite 用于深度分析（持续用水检测、夜间高峰、慢漏识别）。
 Agent 可以用自然语言查询，也可以用 SQL 直接分析小时级数据。"
```
