# Watchlist 巡检系统 — 全自动研究触发器

> 版本: v1.0 | 日期: 2026-07-01 | 状态: 设计中

## 动机

当前 watchlist 是"备忘录"而非"巡检系统"——`check_watchlist()` 只判断日期到期，不获取指标数据，`last_value` 永远为 `None`。"数值变化超 ±20%" 或 "方向反转" 从未被代码执行。

**升级目标**: 全自动研究触发器（路径 C）——指标变化超过阈值 → 自动触发新一轮研究。

---

## §1 整体架构 & 数据流

```
用户发起行业研究
  → TrackAgent.check_industry(行业名)
    → 加载 tracking/watchlist/{行业}.yaml
    → 筛选到期项（now - last_updated >= frequency 对应天数）
    → 对每条到期项：Tavily 搜索 → LLM 提取值 → 对比判断
    → 更新 YAML（last_value, last_updated, history[]）
    → 同步 SQLite
    → 返回 {triggered_items: [...], checked_items: [...], summary: str}
  → triggered_items > 0 ？
    → YES: 输出变化摘要，提示用户是否进入 pipeline
    → NO: 正常走 pipeline
```

**触发方式**: 按需触发（路径 B）——研究前预检，零空跑。

---

## §2 Indicator 数据结构增强

### HypothesizeAgent prompt 改动

`key_indicators` 从 `string[]` 改为 `object[]`：

```json
"key_indicators": [
  {
    "name": "DRAM 合约价月度环比",
    "frequency": "monthly",
    "search_query": "DRAM 合约价 2026",
    "expected_direction": "rising"
  }
]
```

新增字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 指标名（原裸字符串） |
| `frequency` | string | daily/weekly/monthly/quarterly — LLM 判断 |
| `search_query` | string | LLM 推荐的 WebSearch 检索词 |
| `expected_direction` | string | rising/falling/stable/breaking — 假设成立时指标应该怎么走 |

### 跟踪范围过滤

```python
TRACKABLE_STATUSES = {"confirmed", "partial", "unverified", "disputed"}
# 排除: unreachable（上游断裂）, overturned（已被推翻）
```

### YAML 新格式

```yaml
# tracking/watchlist/{行业}.yaml
- indicator: "年度招标金额"
  industry: 可控核聚变
  hypothesis_ids: ["H0-1"]
  hypothesis_statuses: ["confirmed"]
  frequency: monthly
  search_query: "中国核聚变 年度招标金额 2026"
  expected_direction: "rising"
  source_session: 2
  last_value: 42.5
  last_value_text: "42.5 亿"
  last_updated: "2026-07-01"
  threshold: 0.20
  status: pending
  trigger_condition:
    type: threshold
    threshold: 0.20
    direction: "up_trigger"
  history:
    - timestamp: "2026-07-01"
      value: "招标总额 380 亿"
      trend: "rising"
```

---

## §3 巡检 & 触发逻辑

### 入口：TrackAgent.check_industry()

```python
def check_industry(self, industry_name: str) -> dict:
    """行业级巡检入口"""
    # 1. 加载 YAML
    items = self._load_industry_watchlist(industry_name)
    
    # 2. 筛选到期项
    due_items = self._filter_due(items)
    
    # 3. 逐条巡检（Tavily → LLM → 对比）
    triggered = []
    checked = []
    for item in due_items:
        result = self._check_single(item)
        if result["triggered"]:
            triggered.append(result)
        else:
            checked.append(result)
    
    # 4. 更新 YAML + 同步 SQLite
    self._save_industry_watchlist(industry_name, items)
    self._sync_to_db(industry_name, items)
    
    return {
        "triggered_items": triggered,
        "checked_items": checked,
        "summary": self._build_summary(industry_name, triggered, checked),
    }
```

### 单条巡检：_check_single()

```python
def _check_single(self, item: dict) -> dict:
    """单条指标巡检：Tavily 搜 → LLM 提取 → 对比判断"""
    # Step 1: Tavily 搜索
    tavily_results = self._tavily_search(
        query=item["search_query"],
        max_results=5
    )
    
    # Step 2: LLM 从搜索结果中提取结构化值
    prompt = f"""从以下搜索结果中提取指标「{item['indicator']}」的最新值：
    
    {tavily_snippets}
    
    返回 JSON：
    {{
      "current_value": "数字或描述",
      "value_numeric": 42.5,
      "trend": "rising | falling | stable | unclear",
      "confidence": "high | medium | low",
      "source_url": "https://...",
      "source_date": "2026-06",
      "summary": "一句话总结"
    }}
    """
    check_result = self._call_llm(prompt)
    
    # Step 3: 触发判定
    triggered = self._should_trigger(item, check_result)
    
    # Step 4: 更新历史
    item["last_value"] = check_result.get("value_numeric")
    item["last_value_text"] = check_result.get("current_value")
    item["last_updated"] = datetime.utcnow().isoformat()
    item.setdefault("history", []).append({
        "timestamp": datetime.utcnow().isoformat(),
        "value": check_result.get("current_value"),
        "trend": check_result.get("trend"),
    })
    
    return {**item, "check_result": check_result, "triggered": triggered}
```

### 触发判定规则

```python
def _should_trigger(self, item: dict, check_result: dict) -> bool:
    """判断是否触发研究"""
    # 1. LLM 置信度低 → 不触发
    if check_result.get("confidence") == "low":
        return False
    
    # 2. 暂无上次值 → 不触发（基准线不存在）
    if item.get("last_value") is None:
        return False
    
    # 3. 数值类指标：变化超阈值
    if check_result.get("value_numeric") and item.get("last_value"):
        delta = abs(check_result["value_numeric"] - item["last_value"]) / item["last_value"]
        if delta > item.get("threshold", 0.20):
            return True
    
    # 4. 方向反转：预期 rising 但实际 falling
    expected = item.get("expected_direction", "")
    actual = check_result.get("trend", "")
    if actual == "falling" and expected == "rising":
        return True
    if actual == "rising" and expected == "falling":
        return True
    
    return False
```

---

## §4 数据存储统一

### 策略：YAML 权威源 + SQLite 查询缓存

- **YAML**: 人可读的权威源，git 可追溯
- **SQLite**: 快速检索/聚合/趋势分析
- **同步**: 单向 YAML → SQLite，不存在双写不一致

### TrackingItem 表新增列

```sql
ALTER TABLE tracking_items ADD COLUMN indicator_name TEXT;       -- 指标名称
ALTER TABLE tracking_items ADD COLUMN frequency TEXT;            -- 检查频率
ALTER TABLE tracking_items ADD COLUMN last_value REAL;           -- 上次数值
ALTER TABLE tracking_items ADD COLUMN last_value_text TEXT;      -- 上次文本值
ALTER TABLE tracking_items ADD COLUMN search_query TEXT;         -- 检索词
ALTER TABLE tracking_items ADD COLUMN expected_direction TEXT;   -- 预期方向
ALTER TABLE tracking_items ADD COLUMN history_json TEXT;         -- 历史记录 JSON
```

### migrate_v4()

```python
def migrate_v4(engine=None):
    """v4 迁移：tracking_items 新增 7 列"""
    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_cols = {c["name"] for c in inspector.get_columns("tracking_items")}
        for col_name, col_type in [
            ("indicator_name", "TEXT"),
            ("frequency", "TEXT"),
            ("last_value", "REAL"),
            ("last_value_text", "TEXT"),
            ("search_query", "TEXT"),
            ("expected_direction", "TEXT"),
            ("history_json", "TEXT"),
        ]:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE tracking_items ADD COLUMN {col_name} {col_type}"))
                conn.commit()
```

### YAML 旧格式兼容

旧 watchlist 文件 `indicator` 字段为裸字符串 → TrackAgent 加载时自动补默认值：
- `frequency="monthly"`
- `search_query` = indicator 名本身
- `expected_direction="unknown"`

---

## §5 文件结构 & 接口

### 改动文件清单

```
backend/app/strategies/prosperity/
├── coordinator.py              ← +pre_check 步骤（search 前）
├── agents/
│   ├── hypothesize_agent.py    ← prompt: key_indicators string[] → object[]
│   └── track_agent.py          ← 核心重构（+check_industry, +_check_single, +_sync_to_db）
├── models.py                   ← TrackingItem 加 7 列 + migrate_v4()

data/prosperity/
└── tracking/watchlist/
    └── {行业}.yaml             ← 字段增强（旧文件自动补默认值）
```

### API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/prosperity/watchlist/{industry}` | GET | 查看某行业全部跟踪项 |
| `/api/prosperity/watchlist/{industry}/check` | POST | 手动触发巡检（研究前预检） |

### Pipeline 集成

```python
# coordinator.py run_full_pipeline() 开头（search 之前）
pre_check = self._run_track_pre_check(industry_name)
if pre_check["triggered_count"] > 0:
    print(f"⚠️ {pre_check['triggered_count']} 项指标异常，建议研究:")
    for item in pre_check["triggered_items"]:
        print(f"  - {item['indicator']}: {item['change_summary']}")
```

---

## §6 设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 路径 2: LLM + WebSearch 动态获取 | indicator 是 LLM 生成的非结构化文本，无法绑定 Tushare API |
| 2 | 按需触发（路径 B） | 零空跑，token 只花在用户要研究的方向上 |
| 3 | 跟踪范围含 disputed | 争议状态可能翻转，正是自动触发的价值 |
| 4 | YAML 权威 + SQLite 查询缓存 | YAML 人类可读 + git 可追溯；SQLite 快速聚合/趋势分析 |
| 5 | TrackAgent 复用 SearchAgent 的 Tavily + HypothesizeAgent 的 LLM | 不引入新依赖，不改架构 |
| 6 | temperature=0 | 数值提取需确定性，不可有 LLM 幻觉 |

---

## §7 测试策略

1. **TrackAgent 单元测试** — mock Tavily + LLM 返回，验证触发判定
2. **旧格式兼容测试** — 不带新字段的 YAML 文件加载后自动补默认值
3. **状态过滤测试** — unreachable/overturned 不被追踪
4. **集成测试** — 跑一次完整 pipeline，验证新格式 YAML 写入 + SQLite 同步
