# Wiki 智能增强 — 重复行业研究优化

> 版本: v0.14.0 | 日期: 2026-06-29 | 状态: 已实现 ✅
>
> 产出流程: brainstorming → 需求探索 → 方案设计 → 本 Spec

---

## 1. 动机

v0.13.2 修复了 5 个景气打分 Bug，但暴露了 wiki 系统的架构问题——当用户重复研究同一行业时：

| # | 问题 | 影响 |
|---|------|------|
| 1 | 无冷却判断，同一天可重复跑 | 浪费 Tavily + LLM 额度，重复工作 |
| 2 | Search Agent 全量搜索，新旧信息混杂 | LLM 被迫在重复信息中找增量 |
| 3 | 只有 Hypothesize Agent 读 wiki 历史 | Verify/Counter 不知道上次结论，无法做延续性判断 |
| 4 | wiki/industries 评级行每次追加不去重 | 同一日期出现多条重复行 |

**设计目标**: 5 天冷却硬门控 + 全链历史锚定 + 增量搜索分流 + 评级行去重 + key_indicators 全量入 watchlist。

---

## 2. 架构总览

```
用户请求 "研究 电气设备"
        │
        ▼
┌─ Coordinator.start_session() ─────────────────────┐
│  1. 读 wiki/industries/电气设备.md                  │
│  2. 距上次 < 5 天 → 返回 {status: "cooldown"}       │
│     force=False 默认拒绝                            │
│  3. 用户确认 → force=True → 继续                    │
└────────────────────────────────────────────────────┘
        │ (force=True 或首次研究)
        ▼
┌─ Coordinator._load_history("电气设备") ─────────────┐
│  构造 IndustryHistory:                               │
│  ├── wiki/industries/  → 评级历史                   │
│  ├── wiki/synthesis/   → 结构化截取 ~3000字         │
│  │   (L0-L3推理结论 + 选股方向，不含验证/反推)      │
│  ├── DB Hypothesis     → 最近一次session全部假设     │
│  └── DB TrackingItem   → 已有跟踪项                  │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Search Agent (history: IndustryHistory) ───────────┐
│  1. Tavily 全量搜索 5 组关键词                        │
│  2. 对比上次 raw/...yaml → URL去重                   │
│  3. 分流: 🆕新 (完整) / 📚旧 (100字摘要)             │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Hypothesize Agent (history) ───────────────────────┐
│  prompt = 历史锚定(industry_history)                  │
│         + 🆕新搜索情报                                │
│         + 📚旧情报摘要                                │
│         + "基于既有推理链延续拓展"                    │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Verify Agent (history) ────────────────────────────┐
│  prompt += history.previous_hypotheses 状态分布      │
│          "对比上次验证结论，标记变化"                 │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Counter Agent (history) ───────────────────────────┐
│  prompt += history中overturned假设及其推翻理由        │
│          "上次反推指出的风险是否仍成立"               │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Report Agent ──────────────────────────────────────┐
│  _update_industry_page():                            │
│  - 评级行去重：同日期同评级 → 替换不追加             │
│  - 标注 "第N次研究"                                  │
│  - 报告文件：同日期强制覆盖（旧session DB可查）      │
└────────────────────────────────────────────────────┘
        │
        ▼
┌─ Track Agent ───────────────────────────────────────┐
│  提取 ALL 假设的 key_indicators → watchlist           │
│  （非仅 UNVERIFIED/OVERTURNED）                       │
│  按指标名合并去重，关联多个 hypothesis_id             │
└────────────────────────────────────────────────────┘
```

---

## 3. 核心数据结构

### 3.1 IndustryHistory

```python
@dataclass
class IndustryHistory:
    industry_name: str
    study_count: int                    # 第几次（含本次）
    last_rating: str                    # "🔥 高景气" | "✅ 景气" | "⚠️ 弱景气" | "❌ 不景气"
    last_study_date: Optional[datetime]
    cooldown_days: int = 0              # 距上次天数

    # DB Hypothesis（最近一次 session）
    previous_hypotheses: list[dict]     # [{id, title, chain_level, status, confidence, key_indicators, ...}]

    # wiki/synthesis 结构化截取 (~3000字)
    last_synthesis_excerpt: str         # L0-L3推理 + 股池方向，不含验证/反推

    # wiki/industries 评级历史
    rating_history: list[str]           # ["- [2026-06-29] 🔥 高景气..."]

    # DB TrackingItem
    pending_tracking_items: list[dict]

    @property
    def is_first_study(self) -> bool:
        return self.study_count <= 1
```

### 3.2 Watchlist 条目（扩增）

```yaml
# tracking/watchlist.yaml
items:
  - indicator: "DRAM 合约价月度环比"
    industry: "半导体"
    hypothesis_ids: ["H2-1", "H2-2"]
    hypothesis_titles: ["产能过剩拐点", "价格下行压力"]
    hypothesis_statuses: ["verified", "verified"]
    source_session: 3
    check_frequency: "monthly"
    last_value: null
    last_updated: "2026-06-29T00:00:00"
    status: "pending"
    trigger_condition: "数值变化超过 ±20% 或方向反转时触发复核"
```

---

## 4. 改动范围

### 4.1 Coordinator (`coordinator.py`)
- `start_session(industry_name, force=False)` — 加 5 天冷却判断
- 新增 `_check_cooldown(industry_name, force) -> Optional[dict]`
- 新增 `_load_history(industry_name, session_id) -> Optional[IndustryHistory]`
- `run_full_pipeline` / `run_step` — search 之后调 `_load_history`，逐级下传

### 4.2 SearchAgent (`search_agent.py`)
- `search()` 签名加 `history: Optional[IndustryHistory]`
- 新增 `_load_previous_search(industry_name) -> dict` — 读上次 `raw/*/01_search_*.yaml`
- 新增 `_deduplicate_urls(results, prev_results) -> (new, old)` — URL 去重
- 写入时标记 `new_count` / `old_count`

### 4.3 HypothesizeAgent (`hypothesize_agent.py`)
- `form_hypotheses()` 签名加 `history: Optional[IndustryHistory]`
- `_build_prompt()` 从 `history` 取数据，删掉 `_load_wiki_history()`
- 旧结果截到 100 字

### 4.4 VerifyAgent (`verify_agent.py`)
- `verify()` 签名加 `history: Optional[IndustryHistory]`
- `_build_prompt` 注入 history.previous_hypotheses 状态分布

### 4.5 CounterAgent (`counter_agent.py`)
- `counter()` 签名加 `history: Optional[IndustryHistory]`
- `_build_prompt` 注入 overturned 假设及推翻理由

### 4.6 ReportAgent (`report_agent.py`)
- `_update_industry_page()` 加去重逻辑 + 第N次研究标注
- 报告文件名同日期覆盖策略

### 4.7 TrackAgent (`track_agent.py`)
- `extract_tracking()` — 从只提取 UNVERIFIED/OVERTURNED → 提取所有假设的 key_indicators
- 新增 `_merge_indicators(items)` — 按 indicator 名合并去重

### 4.8 转发层
- `run_full_pipeline` 和 `run_step` 中 `history` 对象逐级传入 6 个 Agent

---

## 5. 测试要点

| # | 场景 | 预期 |
|---|------|------|
| T1 | 首次研究行业 | history=None，Agent 行为不变 |
| T2 | 5 天内重复，force=False | 返回 cooldown，不创建 session |
| T3 | 5 天内重复，force=True | 跳过冷却，正常走软增强 |
| T4 | 搜索 URL 去重 | new_count/old_count 正确分流 |
| T5 | Verify 看到上次验证结论 | prompt 含"上次 H0-1 为 confirmed" |
| T6 | Counter 看到上次推翻记录 | prompt 含 overturned 假设+理由 |
| T7 | 行业页评级行去重 | 同日同评级只保留一条 |
| T8 | 已确认假设的指标入 watchlist | verified 假设的 key_indicators 也在 list 中 |
| T9 | 同指标多假设合并 | DRAM 价格 → hypothesis_ids: [H2-1, H2-2] |
| T10 | 无 wiki 历史的行业 | 所有增强逻辑优雅降级，不影响首次研究 |

---

## 6. 不做的事（显式排除）

- ❌ 不实现指标的自动巡检与触发逻辑（本次只铺管道）
- ❌ 不取多 session 历史假设（只取最近一次）
- ❌ 不修改 Tavily 搜索策略（仍全量 5 组关键词，不做 time_range 过滤）
- ❌ 不实现前端 UI 变更（冷却提示走 CLI/API 返回值）

---

## 7. 风险

- `_load_history` 首次实现时 DB query 可能有空值返回 → 所有 Agent 内部 `if history is None` 必须兜底
- URL 去重依赖 `raw/` 目录存在上次的搜索文件 → 文件缺失时退化回全量新结果
- 结构化截取 3000 字依赖报告 section 标题格式稳定 → 添加 fallback：解析失败时取报告前 3000 字
