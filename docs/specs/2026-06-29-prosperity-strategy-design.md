# 高景气策略 — 设计文档 (Spec)

> 版本: v0.24 | 日期: 2026-07-09 | 状态: Wiki-Centric 架构 v1.0（Phase 0+1）
>
> 产出流程: brainstorming → 需求探索 → 方案设计 → 本 Spec
>
> **后续增强 Spec**:
> - `2026-07-01-prosperity-strategy-v16-enhancement.md`（v0.16 核心增强：LLM 验证、股池推理链连接、评级重构）
> - `2026-07-05-prosperity-stability-p0.md`（v0.20 P0 稳定性增强：VerifyAgent 3 轮并行 LLM + 字段级投票聚合）
> - `2026-07-05-prosperity-stability-p1-hypothesize.md`（v0.21 P1 稳定性增强：HypothesizeAgent 两阶段骨架+填充）
> - `2026-07-09-prosperity-wiki-centric.md`（v1.0 Wiki-Centric 架构：产业链 YAML + Agent 读写中枢）

---

## 1. 策略定位

**高景气策略**是一条与龟龟策略完全独立的投资研究策略。

| 维度 | 龟龟策略 | 高景气策略 |
|------|---------|-----------|
| 核心范式 | 选股 → 打分 → 排名 | **假设驱动研究 → 知识沉淀** |
| 分析粒度 | 单股（QRV 深度分析） | **行业**（行业景气研判 + 个股初筛） |
| AI 使用 | LLM 单股分析 | **多 Agent 认知循环**（假设-验证-反推-修正） |
| 数据依赖 | Tushare 积分 API（7个） | Tushare 免费 tier + WebSearch + 行业爬取 |
| 知识产出 | 单股报告 | **LLM Wiki 知识库**（可复利增长） |
| 调用方式 | CodeBuddy 对话 + Web 管道 | 同（双形态共用核心） |

---

## 2. 核心研究流程

```
输入行业 → 情报搜索 → 假设形成 → 交叉验证 → 反推修正 → 报告+股池 → 知识库沉淀
```

### 2.1 情报搜索 — SearchAgent

- 输入：行业名称 + 已有 wiki 上下文
- 信源：`rules/prosperity/source_registry.yaml` 按行业配置的定向信源 + 默认通用搜索
- 输出：`data/prosperity/raw/{industry}/01_search_YYYY-MM-DD.yaml`
- 防幻觉：搜索原文存入 raw/，Agent 只做归类

### 2.2 假设形成 — HypothesizeAgent

> **v0.21 增强**（2026-07-05 Spec `2026-07-05-prosperity-stability-p1-hypothesize.md`）：
> 改用两阶段架构消除假设数量不稳定性（12≠14）：
> - **Phase 1**：3 轮并行 LLM（短 prompt）→ ID+title 投票 → 稳定骨架
> - **Phase 2**：1 轮 LLM（骨架强约束）→ 填充 statement/sentiment/sources 等
> - 配置开关：`PROSPERITY_HYPOTHESIZE_ROUNDS=3`（可降级为 1 轮）

- 输入：情报搜索结果 + 已有假设页（避免重复）
- 推理链结构（v2 因果推理链）：
  - **L0 现状诊断 (2-3条)**：当前行业的客观状态是什么？引用 ≥3 信源
  - **L1 一阶推演 (2-4条)**：如果 L0 成立，接下来必然发生什么？完整逻辑链 + 因果箭头
  - **L2 二阶推演 (2-4条)**：趋势发展下去，矛盾/机会/拐点在哪里？含时间窗口
  - **L3 投资落点 (2-3条)**：这个推理对选股意味着什么？含 investment_implication + key_indicators
- 每条假设强制字段：
  - `id`: H{层级}-{序号} 格式（如 H0-1, H1-2）
  - `derives_from`: 引用上游假设 id（如 "H0-1,H0-2"）
  - `chain_level`: 0=现状诊断 / 1=一阶推演 / 2=二阶推演 / 3=投资落点
  - `time_horizon`: L2/L3 必填时间窗口（如 "6个月" / "2027Q1"）
  - `investment_implication`: L3 必填可操作选股方向（含筛选条件+排除特征）
  - `key_indicators`: L3 必填跟踪指标
- 核心原则：推演而非罗列 — 每条必须有上游 premise → 本环节 → 下游 consequence 的逻辑箭头
- 输出：`wiki/hypotheses/{行业}-{标题}.md` × N 条 + 更新 `index.md`
- 防幻觉：每条假设必须引用 raw/ 中至少 2 个信源

### 2.3 交叉验证 — VerifyAgent

- 输入：所有假设页 + 确定性脚本数据
- 多信源交叉：至少 2 个独立信源一致才确认
- 数据验证：调用确定性脚本（`industry_metrics.py`）拉取同行业公司财务数据
- 反例搜索：主动搜索反对该假设的证据
- 输出：更新假设页，每条标注状态：
  - `✅ CONFIRMED` | `⚠️ PARTIAL` | `🟡 WEAK_DISPUTED` | `❌ DISPUTED` | `🔍 UNVERIFIED` | `⚰️ OVERTURNED` | `🚫 UNREACHABLE`
- 防幻觉：数据验证部分只用脚本输出
- **v0.22 精确分类级联**（2026-07-07）：Q3 从布尔（yes/no）升级为三级（none/weak/strong），按「多轮一致」原则判定强反例：
  - `strong` = 3 轮中 ≥2 轮判 ≥2 分 或 任意轮==3 且非孤立 → `overturned`（直接推翻，切断下游）
  - `weak` = 恰好 1 轮判 2 分（孤立弱反例）→ `weak_disputed`（**降级不切链**，靠信号权重自然稀释）
  - `none` = 其余（所有轮 ≤1）→ 正常状态合成
  - 效果：消除「单轮 LLM 误判→整链崩溃」的级联误杀
- **v0.19 确定性合成**：LLM 不输出 status/confidence，只输出事实字段，status 由 `_synthesize_status()` 确定性计算（v0.22 升级为 conflict_level 三级入参）
- **v0.20 多轮投票聚合**（2026-07-05 Spec）：3 轮并行 LLM 调用（Self-Consistency），字段级聚合：
  - Q1 `supporting_source_indices`: 3 轮取**交集**，消除 LLM 计数幻觉
  - Q2 `data_alignment`: 3 轮取**众数**，保留 LLM 语义判断
  - Q3 `counter_conflict_score`: 3 轮**三级分级**（见 v0.22），替换旧布尔逻辑
  - sentiment: 3 轮取**众数**，写入 `verified_sentiment`
- **字段保留规则**（v0.12.3）：LLM 验证输出与原始假设合并时，必须保留以下字段：
  - `sentiment`：假设的固有方向属性（positive/negative/neutral），HypothesizeAgent 生成，验证不改
  - `causality_strength`：因果箭头强度，LLM 验证输出
  - `causality_note`：因果强度说明，LLM 验证输出
  - 其他保留字段：title, statement, reasoning, chain_level, derives_from, sources, time_horizon, key_indicators, investment_implication, wiki_path, verification_needed, tier
- 级联规则（v2 新增，v0.22 收敛仅 overturned 切链）：
  - 按 L0 → L3 层级顺序验证
  - 上游假设状态为 OVERTURNED → 下游自动标记 `🚫 UNREACHABLE`（不可达）
  - weak_disputed / partial / unverified 一律不切断推理链
  - UNREACHABLE 假设不参与景气评级

### 2.4 反推修正 — CounterAgent

- 输入：已验证的假设 + overturned/weak_disputed 标记
- overtuned 假设 → 标注 `⚰️ OVERTURNED`（不删除），分析推翻原因 + 级联下游 unreachable
- weak_disputed 假设 → 降级置信度，**不切断下游**，靠信号权重自然稀释
- PARTIAL 假设 → 修正边界条件或降级置信度
- UNVERIFIED 假设 → 自动进入跟踪项
- 输出：更新假设页（追加「反推修正」章节）
- 级联处理（v2 增强，v0.12.3 去极性化，v0.22 收敛切链集合）：
  - 三遍扫描（纯机械，不区分 polarity）：
    1. **overturned → 切断下游**：被确凿反例证伪的假设，下游 automatic unreachable
    2. **weak_disputed → 降级不切**：有矛盾但不直接推翻，降低置信度
    3. **PARTIAL → 降级置信度**：数据不充分但不切断链
  - 级联传递集合从 `{overturned, unreachable, disputed}` 收敛为 **`{overturned, unreachable}`**
  - **设计理由**：v0.22 将 disputed 在 VerifyAgent 阶段消化为 overturned（强反例）或 weak_disputed（弱反例），CounterAgent 不再需要处理 ambiguous 的 disputed 状态。weak_disputed 保留在信号评分中，靠 causality_discount + SIGNAL_MAP 自然降权，而非一刀砍掉。
- 级联处理（v2 增强，v0.12.3 去极性化）：
  - 三遍扫描（纯机械，不区分 polarity）：
    1. **DISPUTED → OVERTURNED**：所有被数据证伪的假设，不论 sentiment，一律标记 overturned（标注推翻原因，不删除页面）
    2. **上游 OVERTURNED → 下游 UNREACHABLE**：级联传播，被推翻的前提推导出的下游全部不可达
    3. **PARTIAL → 降级置信度**：数据不充分但不切断链
  - 级联统计：overturned_count + cascade_unreachable_count
  - **设计理由**：sentiment 不改变逻辑完整性的判断。negative+disputed（坏消息被证伪）不代表下游推理链的前提成立——前提被推翻就是被推翻，不享受"保活"特权。真正的正向信号应来自正向假设本身，不是从错误推理中榨取间接利好。
- **sentiment 修正规则**（v0.12.3）：基于 verified 输出的 `corrected_statement` 判断方向是否改变：
  - 原 positive + corrected 描述为"增速放缓/局部机会" → neutral
  - 原 positive + corrected 描述为"恶化/萎缩" → negative
  - 原 negative + corrected 描述为"风险可控/好于预期" → neutral 或 positive
  - corrected 为空或与原始方向一致 → 不修正
  - 修正后保留 `original_sentiment` 作为审计痕迹
- **v0.23.1 CounterAgent 安全网增强**（2026-07-08）：
  - **LLM Prompt 硬规则**: 新增「绝对禁止」章节——partial/unverified 绝不能 overturned；disputed 分强反例(方向反转→overturned)和弱反例(程度变化→downgrade_confidence)
  - **代码层安全网**: `_apply_cascade` 程序化拦截——LLM 即使输出 keep_unreachable，partial/unverified 也会被强行 downgrade_confidence
  - **硬编码兜底增强**: `_hardcoded_cascade` 新增方向反转关键词检测(缩减/转负/萎缩/停止增长)，disputed 只有在匹配时才 overturned
  - **配置化**: `PROSPERITY_COUNTER_TIMEOUT` 替代硬编码 120s，可被 .env 覆盖

### 2.5 报告生成 + 股池 — ReportAgent

- 输入：所有修正后的假设 + 行业个股财务数据
- 产出 1：`wiki/synthesis/{日期}-{行业}景气分析.md`（Markdown 完整报告）
- 产出 2：`{industry}/stock_pool.yaml`（行业内百分位排名打分）
- 产出 3：更新 `wiki/industries/{行业}.md` 行业总览页
- 产出 4：更新 `index.md` + 追加 `log.md`
- 打分公式：所有维度基于行业内百分位排名（非绝对阈值）
- 叙事体裁报告（v2）：
  - 推理链概览图：Mermaid graph TD 可视化所有假设的因果边
  - 按层级分章节：L0 现状 → L1 推演 → L2 拐点 → L3 落点
  - 投资含义章节：汇总所有 L3 的 investment_implication
  - 景气评级排除 `unreachable` 假设

### 2.6 跟踪项 + 巡检 — TrackAgent

- 提取跟踪项 → `tracking/watchlist.yaml` + `prosperity.db`
- 触发时机：月度定时巡检 / 研究前预检 / 知识库健康检查
- 输出：wiki 健康报告 + 到期限更新

---

## 3. 确定性脚本清单（防幻觉边界）

> 脚本只输出客观数据，不允许 LLM 推理。Agent 负责解读，脚本负责事实。

| 脚本 | 职责 | 调用者 |
|------|------|--------|
| `data_fetcher.py` | Tushare 数据拉取（复用现有基础设施） | Agent 3, 5 |
| `industry_metrics.py` | 行业聚合指标（通用指标自动算 + 专属指标按 profile 配置） | Agent 3 |
| `stock_screener.py` | 行业内百分位排名打分 | Agent 5 |
| `source_crawler.py` | Tier 2 行业数据爬取（价格/产能/渗透率） | Agent 3 |
| `wiki_indexer.py` | Wiki 索引维护（文件扫描+元数据提取） | 各 Agent |

### 打分公式（`stock_screener.py`）

```python
SCORING = {
    "revenue_growth": 0.25,      # 营收增速（行业内百分位排名）
    "earnings_growth": 0.25,     # 利润增速
    "roe_level": 0.15,           # ROE 水平
    "momentum_3m": 0.15,         # 近3月相对行业超额收益
    "momentum_6m": 0.10,         # 近6月超额收益
    "quality": 0.10,             # FCF为正 + 毛利率趋势向上
}
# 权重可通过 .env 或 scoring_weights.yaml 调整
```

### 数据分层策略

| 层级 | 来源 | 实例 | 防幻觉 |
|------|------|------|--------|
| Tier 1 | Tushare 财务数据 | 营收、利润、ROE | 直出，不改字段名 |
| Tier 2 | 行业协会/政府公开数据 | 渗透率、装机量、价格 | 爬取失败返回空，不猜测 |
| Tier 3 | LLM 从研报/新闻提取 | 行业趋势描述 | 强制引用来源 + 标注置信度 |

---

## 4. 知识库架构（LLM Wiki 模式）

融合 Karpathy [[LLM Wiki]](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 核心理念：
- `raw/` 原始资料只读，不可修改
- `wiki/` LLM 维护的知识页面，假设页含推翻历史
- 矛盾标注而不删除（OVERTURNED）
- 跟踪项 + 巡检机制

```
data/prosperity/
├── SCHEMA.md                  ← 知识库维护契约
├── index.md                   ← 内容目录（每页一行链接+摘要）
├── log.md                     ← 只追加操作日志
├── prosperity.db              ← SQLite 结构化数据
│
├── raw/{industry}/            ← 原始资料（只读，不可修改）
├── wiki/
│   ├── industries/            ← 行业总览页
│   ├── hypotheses/            ← 假设页（含推翻历史）
│   ├── concepts/              ← 通用概念/方法论（跨行业复用）
│   ├── comparisons/           ← 横向对比页
│   └── synthesis/             ← 综合报告
│
└── tracking/
    └── watchlist.yaml         ← 跟踪项
```

### 数据库表结构（SQLite + SQLAlchemy ORM，可迁移 PostgreSQL）

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `industries` | 行业元数据 | id, name, first_study, last_study |
| `research_sessions` | 研究会话 | id, industry_id, status, current_step |
| `hypotheses` | 假设追踪 (v2: 4层因果链) | id, session_id, title, tier, chain_level, derives_from, time_horizon, status, confidence, wiki_path |
| `stock_pools` | 股池快照 | id, session_id, ts_code, score_total, rank |
| `industry_metrics` | 行业指标快照 | id, industry_id, period, metrics(JSON) |
| `tracking_items` | 跟踪项 | id, industry_id, item, check_date, status |

### 状态流转（v2）

```
假设状态流转（v0.22 精确分类）:
  pending → CONFIRMED ✅
         → PARTIAL ⚠️
         → UNVERIFIED 🔍
         → WEAK_DISPUTED 🟡 (降级不切链，弱反例)
         → OVERTURNED ⚰️ (强反例，多轮一致)

级联: 仅 overtuned → 下游 UNREACHABLE 🚫
       weak_disputed / partial / unverified → 保持活跃，不切链
```
- OVERTURNED 假设**不删除**，保留推翻原因
- WEAK_DISPUTED 假设**不切链**，靠 causality_discount=0.4 + SIGNAL_MAP 弱信号值自然稀释

---

## 5. 双形态架构

```
CodeBuddy Skills（对话式）        Web 前端（管道式）
      │                                │
      └──────────┬─────────────────────┘
                 │
        coordinator.py（唯一核心）
                 │
     ┌───────────┼───────────┐
     │           │            │
SearchAgent HypothesizeAgent VerifyAgent ...
     │           │            │
     └───────────┼───────────┘
                 │
        确定性脚本层 + Wiki + SQLite
```

### CodeBuddy Skill 清单

| Skill | 对应 Agent | 功能 |
|-------|-----------|------|
| `prosperity-search` | SearchAgent | 情报搜索 |
| `prosperity-hypothesize` | HypothesizeAgent | 假设形成 |
| `prosperity-verify` | VerifyAgent | 交叉验证 |
| `prosperity-counter` | CounterAgent | 反推修正 |
| `prosperity-report` | ReportAgent | 生成报告+股池 |
| `prosperity-lint` | TrackAgent | 知识库巡检 |

每个 Skill 是薄封装层，核心逻辑在 Python Agent 类中。

### Web API 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/prosperity/search` | POST | 情报搜索 |
| `/api/prosperity/hypothesize` | POST | 假设形成 |
| `/api/prosperity/verify` | POST | 交叉验证 |
| `/api/prosperity/counter` | POST | 反推修正 |
| `/api/prosperity/report` | POST | 生成报告 |
| `/api/prosperity/lint` | POST | 知识库巡检 |
| `/api/prosperity/session/status` | GET | 会话状态查询 |
| `/api/prosperity/history` | GET | 历史记录查询 |

---

## 6. 项目文件结构

```
backend/app/strategies/prosperity/
├── __init__.py
├── coordinator.py             ← 管道编排
├── api.py                     ← Web API
├── models.py                  ← SQLAlchemy 模型
├── SCHEMA.md                  ← 知识库契约
│
├── agents/
│   ├── search_agent.py
│   ├── hypothesize_agent.py
│   ├── verify_agent.py
│   ├── counter_agent.py
│   ├── report_agent.py
│   └── track_agent.py
│
├── tools/
│   ├── industry_metrics.py
│   ├── stock_screener.py
│   ├── source_crawler.py
│   └── wiki_indexer.py
│
├── codebuddy_skills/
│   ├── prosperity-search/SKILL.md
│   ├── prosperity-hypothesize/SKILL.md
│   ├── prosperity-verify/SKILL.md
│   ├── prosperity-counter/SKILL.md
│   ├── prosperity-report/SKILL.md
│   └── prosperity-lint/SKILL.md
│
data/prosperity/
├── SCHEMA.md
├── index.md
├── log.md
├── prosperity.db
├── raw/
├── wiki/
└── tracking/

backend/rules/prosperity/
├── source_registry.yaml
├── scoring_weights.yaml
└── industry_profiles/
    └── semiconductor.yaml（示例）
```

---

## 7. 与龟龟策略的隔离

- ✅ 不在同一目录（`strategies/turtle/` vs `strategies/prosperity/`）
- ✅ 独立数据缓存（`data/stock_cache/turtle/` vs `data/prosperity/`）
- ✅ 独立 API 前缀（`/api/turtle/` vs `/api/prosperity/`）
- ✅ 独立前端组件（`components/turtle/` vs `components/prosperity/`）
- ✅ 共享基础设施：`tushare_client.py`（只读不写）、`config.py`、`logging.py`
- ✅ 注册表独立注册（`registry.py` 新增一条）

---

## 8. 前置条件（MVP 范围）

| 项 | 内容 |
|----|------|
| 数据源 | Tushare 免费 tier（已覆盖）+ Tavily WebSearch API |
| 数据库 | SQLite（零配置），SQLAlchemy ORM（可迁移 PostgreSQL） |
| LLM | DeepSeek（复用现有配置） |
| 首个行业 | 半导体（配置专属信源 + 行业指标 profile） |
| 前端 | MVP 后讨论（先跑通 Agent + 后端） |

---

## 9. 待定项

- 前端页面设计（最后讨论）
- 行业专属指标 profile 的增量积累机制

---

## 10. 设计决策记录

1. **Agent 状态四态化**：CONFIRMED / PARTIAL / DISPUTED / UNVERIFIED（新增 UNVERIFIED，应对无证可验的假设）
2. **假设不设硬上限**：分层（核心判断 → 子假设 → 数据假设），只对高影响力假设深度验证
3. **渗透率等非财务数据**：优先 Tier 1 协会公开数据 → Tier 2 反推计算 → Tier 3 多信源交叉验证，不用正则猜测
4. **股池打分用行业内百分位**：消除行业间差异，不写死绝对阈值
5. **前端暂缓**：先跑通 Agent + 后端数据链路，MVP 后再讨论前端页面设计
6. **数据库选择 SQLite**：零配置、单文件、SQLAlchemy ORM 可无缝迁移 PostgreSQL
7. **假设从平铺改为因果推理链**（v0.12.2）：用户反馈"假设太散太浅，不是推演只是罗列，对挖掘标的没帮助"。重构为 4 层因果推理链（L0→L3），每条假设必须有 derives_from 因果箭头，L3 必须产生可操作投资落点。
8. **UNREACHABLE 级联机制**（v0.12.2）：上游假设被推翻 → 下游自动不可达。避免在已断裂的推理链上继续浪费验证资源，UNREACHABLE 假设不参与景气评级。
9. **报告采用叙事体裁**（v0.12.2）：从平铺列表改为按推理链分章的叙事结构，含 Mermaid 因果图可视化，投资含义章节从 L3 提取可操作选股方向。
10. **级联去极性化**（v0.12.3）：CounterAgent 的三遍扫描不区分 polarity。被证伪的前提（不论 positive 还是 negative）一律标记 overturned → 下游级联 unreachable。理由：(a) 被推翻就是被推翻，逻辑完整性不因"方向对我有利"而改变；(b) 真正的正向信号应来自正向假设的 confirmed，而非负向假设被推翻后的间接利好；(c) 实际数据中 HypothesizeAgent 极少产出 negative 假设，极性规则几乎没有实战受益者。
11. **VerifyAgent 字段保留**（v0.12.3）：LLM 验证输出与原始假设合并时，`sentiment`、`causality_strength`、`causality_note` 必须从原始假设保留。原因：sentiment 是假设的固有方向属性，HypothesizeAgent 生成后不被验证改动（只被 CounterAgent 基于 corrected_statement 修正）。若丢弃则 ReportAgent 全部按 neutral 计算，信号被系统性压低。
12. **精确分类级联**（v0.22）：Q3 反例冲突从布尔（yes/no）升级为三级（none/weak/strong），要求多轮一致才能判定强反例（strong→overturned）。weak_disputed 状态**降级不切链**，靠信号权重自然稀释。效果：消除「单轮 LLM 误判→整链崩溃」的级联误杀。CounterAgent 切链集合从 `{overturned, unreachable, disputed}` 收敛为 `{overturned, unreachable}`。\n\n---\n\n## 11. Wiki-Centric 架构（v1.0 — Phase 0+1）\n\n> **日期**: 2026-07-09 | **关联 Plan**: `docs/plans/2026-07-09-prosperity-wiki-centric.md`\n\n### 11.1 核心转向\n\n**现状诊断**：当前 wiki 被当成流水线末端的「归档输出」——每个 agent 把自己的产物写进去，下一个 agent 重新从 hypotheses + search 拼上下文，wiki 里的产业积累（产业链拓扑、瓶颈、上次推演结论）没有人读。\n\n**证据**：\n- `CounterAgent.cascade()` 签名不含 `history`，做上下游级联裁决却不知道产业链拓扑\n- `ScreeningAgent` 对 wiki 只有 `update_index` + `append_log`，从不读取 `industries/{name}.md`\n- `_load_history()` 只返回摘要（上次评级 + 假设状态 + synthesis 摘录），不包含产业链结构\n- 但 `industries/存储芯片.md` 已含完整的 7 节产业图谱（价值链/供需/瓶颈/跟踪指标等）——**知识已存在，无人消费**\n\n**转向**：wiki 从管道末端日志 → 所有 agent 共用的中枢知识库\n\n### 11.2 产业链拓扑 YAML 协议\n\n`industries/{name}.md` 保持人类可读的 Markdown 格式。同时生成**伴生 YAML 文件**供程序/Agent 结构化消费：\n\n```yaml\n# industries/{name}.yaml — 由 LearningAgent 首次生成，跨 run 复用\nindustry: 存储芯片\nupdated_at: 2026-07-08\n\nchain:\n  segments:\n    - id: upstream_equipment\n      name: 上游设备与材料\n      position: upstream\n      description: ...\n      bottleneck:\n        level: medium        # low / medium / high / critical\n        detail: ...\n        localization_rate: 30\n      representative_companies:\n        - 精测电子\n        - 中微公司\n\n    - id: mid_manufacturing\n      name: 中游设计制造与封测\n      position: mid\n      description: ...\n      bottleneck:\n        level: high\n        detail: HBM产能严重不足\n        localization_rate: 15\n      representative_companies:\n        - 兆易创新\n        - 澜起科技\n        - 北京君正\n\n    - id: downstream_applications\n      name: 下游模组与终端应用\n      position: downstream\n      description: ...\n      bottleneck:\n        level: low\n        localization_rate: 80\n      representative_companies:\n        - 江波龙\n        - 朗科科技\n\nbottlenecks:  # 全局瓶颈视图\n  - segment_id: upstream_equipment\n    severity: medium\n    description: 国产设备和材料存在卡脖子问题\n  - segment_id: mid_manufacturing\n    severity: high\n    description: HBM产能严重不足\n\nsupply_demand:\n  overall_judgment: 严重供需短缺\n  demand_drivers:\n    - driver: AI服务器数据中心HBM需求爆发\n      certainty: high\n      window: 2026-2028\n  supply_constraints:\n    - constraint: HBM产能严重偏紧\n```\n\n**设计决策**：\n- Markdown 页面保持人类可读；YAML 伴生文件提供结构化数据\n- LearningAgent 首次生成时同步产出 Markdown + YAML\n- 若 YAML 存在则 LearningAgent 跳过（跨 run 复用）\n- 后续人工可在 Markdown 编辑后触发 YAML 同步（Phase 2+）\n\n### 11.3 Agent 读写契约（v1.0 基线）\n\n| Agent | 读 wiki YAML | 写 wiki YAML | 变更 |\n|-------|:---:|:---:|------|\n| LearningAgent | ❌ | ✅ 首次生成 | 新增：`learn()` 同时产出 Markdown + YAML |\n| SearchAgent | ❌ | ❌ | 不变 |\n| HypothesizeAgent | 🟡 预留 | ❌ | Phase 1：签名新增 `chain_model` 参数（pass-through，Phase 2+ 消费） |\n| VerifyAgent | 🟡 预留 | ❌ | Phase 1：签名新增 `chain_model` 参数 |\n| CounterAgent | 🟡 预留 | ❌ | Phase 1：签名新增 `chain_model` + `history` 参数 |\n| ScreeningAgent | 🟡 预留 | ❌ | Phase 1：签名新增 `chain_model` 参数 |\n| ReportAgent | ❌ | ❌ | 不变（通过 screening_result 间接获取） |\n| TrackAgent | ❌ | ❌ | 不变 |\n\n> 🟡 预留 = Phase 1 只改签名传参，实际消费逻辑留 Phase 2+（待讨论 Hypothesize/Verify/Counter 的 wiki 分析飞轮）\n\n### 11.4 Coordinator 变更\n\n新增 `_load_chain_model()`：\n\n```python\ndef _load_chain_model(self, industry_name: str) -> dict | None:\n    yaml_path = self.data_dir / \"wiki\" / \"industries\" / f\"{industry_name}.yaml\"\n    if yaml_path.exists():\n        import yaml\n        return yaml.safe_load(yaml_path.read_text(encoding=\"utf-8\"))\n    return None\n```\n\n管道注入：\n\n```python\nchain_model = self._load_chain_model(industry_name)\nhypotheses   = self._run_hypothesize_agent(..., history, chain_model)   # 新增\nverification = self._run_verify_agent(..., history, chain_model)         # 新增\ncascade      = self._run_counter_agent(..., verified_hypotheses,\n                                        history, chain_model)            # 新增 history + chain_model\nscreening    = self._run_screening_agent(..., history, chain_model)      # 新增\n```\n\n### 11.5 迁移计划\n\n| Phase | 内容 | 版本 |\n|-------|------|------|\n| **Phase 0** | YAML schema 定义 + LearningAgent 输出 YAML + 样本文件 | v1.0.0 |\n| **Phase 1** | `_load_chain_model()` + 所有 agent 签名加 `chain_model` 参数 | v1.0.0 |\n| **Phase 2** | HypothesizeAgent / VerifyAgent / CounterAgent 消费 YAML（分析飞轮）| v1.1.0 |\n| **Phase 3** | ScreeningAgent 消费 YAML → 多桶输出 + 角色标签 | v1.2.0 |\n| **Phase 4** | TrackAgent 增加股票级跟踪 | v1.3.0 |
