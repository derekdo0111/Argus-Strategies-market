# 高景气策略 v0.16 — 核心增强设计 Spec

> 版本: v0.16 | 日期: 2026-07-01 | 状态: 已实现 ✅
>
> 产出流程: brainstorming → 缺陷分析 → 逐项设计讨论 → 本 Spec
>
> 前置 Spec: `2026-06-29-prosperity-strategy-design.md`（v0.12.2 核心设计）

---

## 0. 概述

### 问题根源

高景气策略 v0.15 存在 **两个致命缺陷**，根源是同一件事：**整条 6 Agent 管道中只有 HypothesizeAgent 用到了 LLM，其余 5 个 Agent 全是确定性代码。** LLM 产出的大量推理内容（假设、因果链、选股方向）从未被代码去挑战或利用。

### 改进总览

| 缺陷 | 严重度 | 方案 | 涉及 Agent |
|------|:--:|------|-----------|
| 验证是伪验证 | 🔴 致命 | VerifyAgent LLM 串行验证推理链 + 反例搜索 | VerifyAgent |
| 股池与推理链脱节 | 🔴 致命 | 新增 ScreeningAgent，LLM 方向匹配 + 财务打分 50/50 | ScreeningAgent (新) |
| 评级只看数量 | 🟠 严重 | sentiment 方向标注 + 加权信号聚合 | HypothesizeAgent + ReportAgent |
| 搜索乐观偏差 | 🟠 严重 | VerifyAgent 内 LLM 生成反例搜索词并执行 | VerifyAgent |
| 动量因子占位 | 🟡 中等 | Tushare daily 实时拉取真实动量 | ScreeningAgent |
| 级联只有阻断 | 🟡 中等 | causality_strength 因果箭头强度 | VerifyAgent + ReportAgent |
| CounterAgent 冗余 | — | 合并进 VerifyAgent，管道 6→5 | VerifyAgent |

### LLM 调用变化

| | v0.15 | v0.16 |
|---|-------|-------|
| SearchAgent | 0 | 0 |
| HypothesizeAgent | 1 | 1 |
| VerifyAgent | 0 | N（推理链条数） |
| CounterAgent | 0 | —（移除） |
| ScreeningAgent | — | 1 |
| ReportAgent | 0 | 0 |
| TrackAgent | 0 | 0 |
| **合计** | **1 次** | **(推理链条数 + 2) 次** |

---

## 1. 管道架构变更

```
旧: Search → Hypothesize → Verify → Counter → Report → Track
                              ↓          ↓
                         纯代码3条        纯代码
                         if-else       标签搬运工

新: Search → Hypothesize → Verify → Screening → Report → Track
              ↑                    ↑            ↑
           LLM ×1              LLM ×N       LLM ×1
```

### CounterAgent 移除理由

CounterAgent 三种操作在新设计中的归宿：

| 旧操作 | 新处理方式 |
|--------|-----------|
| DISPUTED → OVERTURNED | VerifyAgent LLM 直接输出 status=disputed（证据不足）或 overturned（已证伪）。disputed 不触发级联，overturned 触发下游 UNREACHABLE。 |
| 上游推翻 → 下游 UNREACHABLE | 串行验证天然处理；确定性后处理作为安全网 |
| PARTIAL → 降级置信度 | VerifyAgent LLM 直接输出修正后置信度 |

### 新增 ScreeningAgent

取代原有 `ReportAgent._generate_stock_pool()` 中的纯财务打分。职责：
1. LLM 方向匹配：基于 L3 investment_implication + 搜索素材，对每只成分股判断"方向契合度" 0~1
2. 代码财务打分：保留原有六因子（含真实动量），行业内百分位排名
3. 50/50 融合：最终分 = 方向契合度 × 0.5 + 财务质量 × 0.5

---

## 2. 各 Agent 详细改动

### 2.1 HypothesizeAgent — 新增 `sentiment` 字段

**背景**：评级公式需要区分"行业正在变好"和"行业有风险"——两者被 CONFIRMED 时对景气度的影响方向相反。

**改动**：LLM 生成每条假设时额外输出：

```json
{
  "id": "H0-1",
  "statement": "工程化加速启动，多个聚变项目进入实质性建设阶段",
  "sentiment": "positive",
  ...
}
```

**取值**：

| sentiment | 含义 | 示例 |
|-----------|------|------|
| `positive` | 正向信号（有机会） | "订单集中释放"、"政策大力支持" |
| `negative` | 负向信号（有风险） | "估值泡沫风险"、"产能过剩隐忧" |
| `neutral` | 中性事实描述 | "高温超导为技术主线"（不评价好坏） |

**规则**：sentiment 是假设的固有属性，在生成时就确定，不由 VerifyAgent 修改。

---

### 2.2 VerifyAgent — 完全重构

#### 2.2.1 新流程

```
VerifyAgent:
  ① 拉取 Tushare 行业聚合指标 + 成分股基本面数据
  ② LLM 根据推理链内容自动生成反例搜索词（见 §2.2.2）
  ③ 执行反例搜索（Tavily）
  ④ 串行验证每条推理链（见 §2.2.3）
  ⑤ 确定性后处理（见 §2.2.5）
  ⑥ 写回假设页面验证章节 + 更新数据库
```

#### 2.2.2 反例搜索（LLM 生成搜索词）

**背景**：当前 SearchAgent 仅搜索正向/中性信息，管道输入从源头就偏乐观。反例搜索在验证阶段补上缺失的负面视角。

**机制**：
- 输入推理链条（4 条假设的完整上下文）
- LLM 自动生成 2-3 个针对该链路的反例搜索词
- 执行 Tavily 搜索
- 搜索结果作为验证 LLM 的输入之一

示例 —— 针对链路 3"估值泡沫风险"：
```
LLM 生成:
  - "可控核聚变 概念股 炒作 证据 OR 监管关注"
  - "超导概念 估值回撤 2025 OR 2026"
  - "核聚变 商业化 距离 5年 OR 10年"
```

#### 2.2.3 LLM 串行验证推理链

**输入**（每条链路）：
1. 当前链路的 4 条假设（L0 到 L3 带 derives_from）
2. 上一轮验证结果摘要（串行上下文）
3. Tushare 行业聚合指标 + 成分股核心指标
4. 原搜索阶段的正向素材（SearchAgent 产出）
5. 本轮生成的反例搜索素材

**输出**（每条假设）：

```json
{
  "id": "H1-1",
  "status": "confirmed",
  "reason": "Tushare 显示供应链相关公司 Q1 新签订单同比 +15%，信源 [1][3][5] 均确认多个聚变项目已进入采购阶段",
  "corrected_statement": null,
  "confidence": "high",
  "causality_strength": "strong",
  "causality_note": "H0-1 多个项目开工成立，Q1 订单数据明确支撑'带动'关系"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | enum | `confirmed` / `partial` / `disputed` / `overturned` / `unverified` |
| `reason` | string | 验证理由，必须引用具体数据或信源 |
| `corrected_statement` | string/null | 若假设错误或不精确，LLM 基于真实数据写出修正版（不含推测） |
| `confidence` | enum | `high` / `medium` / `low`（数据支撑程度） |
| `causality_strength` | enum | `strong` / `moderate` / `weak` / `broken` — 因果箭头的牢固程度 |
| `causality_note` | string | 因果强度简短说明 |

**状态语义**：
- `confirmed` — 多信源一致确认，证据充足
- `partial` — 部分确认，边界条件有待观察
- `disputed` — **证据不足**，缺乏足够数据支撑确认或推翻
- `overturned` — **已证伪**，反例证据明确推翻原始假设
- `unverified` — 尚未验证

**级联规则**：只有 `overturned` 触发下游 UNREACHABLE，`disputed` 不触发级联（仅标记自身状态，等待更多证据）。

**串行验证规则**：
- 链路串行执行，第 N 条能拿到前 N-1 条的验证结果
- 上游 overturned → LLM 在 prompt 中看到后自主判定下游链路是否断裂
- 上游 disputed → 仅作为信息传递，不强制触发级联
- 确定性后处理作为安全网（防止 LLM 漏判级联）

#### 2.2.4 假设页面验证章节

每条假设页面追加：

```markdown
## 验证（2026-07-01）

**验证结果**: ✅ CONFIRMED
**置信度**: high
**验证说明**: Tushare 数据显示...
**修正陈述**: （若原始假设有误）
**因果箭头强度**: strong — H0-1 成立且 Q1 订单数据明确支撑

### 反例证据
- [反例搜索词1] — 2 条结果
  - "超导线材 良率低 量产困难" — 来源 [R1]，但样本公司良率已达 85%...
- [反例搜索词2] — 0 条强证据
```

#### 2.2.5 确定性后处理（安全网）

LLM 验证后，代码做两件事防漏判：

1. **级联安全网**：上游假设被 LLM 标记为 OVERTURNED → 检查下游是否被正确标记 UNREACHABLE，若漏判则补标。DISPUTED 不触发级联。
2. **页面写入**：将 LLM 输出的验证字段写入假设页面文件 + SQLite

---

### 2.3 ScreeningAgent（新增）—— LLM 方向匹配 + 代码财务打分

#### 2.3.1 整体流程

```
ScreeningAgent.screen(industry_name, hypotheses, industry_data):

  Stage 1 — LLM 方向匹配:
    输入: 成分股列表(名称+ts_code+行业) + 搜索素材 + L3 investment_implication
    任务: 对每只股票判断是否匹配 L3 方向
    输出: 每只股票的「方向契合度」0~1 + 一句话理由

  Stage 2 — 代码财务打分:
    和现有 stock_screener 一样，六因子行业内百分位排名
    动量因子不再为占位符，使用 Tushare daily 实时拉取

  Stage 3 — 融合:
    最终分 = 方向契合度 × W_direction + 财务质量 × W_finance
    W_direction 和 W_finance 可通过 .env 调整，默认各 0.5
```

#### 2.3.2 LLM 方向匹配细节

**输入**：
- 成分股列表（名称、ts_code、行业归属）
- SearchAgent 产出的大搜索素材（44 条新闻/研报摘要）
- L3 假设的 `investment_implication` 字段
- L3 假设的验证结果（方向被推翻的跳过）

**LLM 判断规则**：
- 股票在搜索素材中被明确提到 + 与 L3 方向相关 → 高契合度（0.8~1.0）
- 股票在搜索素材中未出现但行业与 L3 方向相关 → 中性（0.4~0.6）
- 股票与 L3 排除方向匹配 → 低契合度（0.0~0.3）
- **未提及 = 倾向于排除**：搜索素材完全未提到 → 契合度 0.3~0.4（不排除但低信心）

**输出格式**：

```json
{
  "matches": [
    {
      "ts_code": "000657.SZ",
      "name": "中钨高新",
      "direction_score": 0.90,
      "matched_l3": "H3-1",
      "reason": "公告中标 BEST 项目超导材料供应合同，搜索素材 [12][15] 确认"
    },
    {
      "ts_code": "600105.SH",
      "name": "永鼎股份",
      "direction_score": 0.85,
      "matched_l3": "H3-2",
      "reason": "高温超导带材量产企业，产能 200km/年，素材 [8][22] 提及为技术标杆"
    },
    {
      "ts_code": "00XXXX.SZ",
      "name": "某概念股",
      "direction_score": 0.15,
      "matched_l3": null,
      "reason": "搜索素材未出现，且公告澄清核聚变业务占比<2%，符合 H3-3 排除方向"
    }
  ]
}
```

**幻觉兜底**：连续跟踪中交叉验证——如果某股票上轮因"公告中标"得高分，下轮跟踪时可通过新的搜索素材重新验证。MVP 阶段不额外加实时事实核查。

#### 2.3.3 代码财务打分改动

##### 动量因子：从占位符变为真实数据

```python
# 旧：_momentum_stub() returns 0.5 for all stocks
# 新：调用 Tushare daily 接口

def _momentum(self, ts_code: str, days: int) -> float:
    """计算 N 日价格动量"""
    df = tushare_client.call("daily", ts_code=ts_code, 
                              start_date=start, end_date=end)
    if df is None or len(df) < 2:
        return 0.5  # 兜底中性分
    close = df["close"].values
    return (close[-1] - close[0]) / close[0]
```

保持六因子权重不变：
```python
SCORING = {
    "revenue_growth": 0.25,
    "earnings_growth": 0.25,
    "roe_level": 0.15,
    "momentum_3m": 0.15,    # 60 个交易日
    "momentum_6m": 0.10,    # 120 个交易日
    "quality": 0.10,
}
```

所有因子基于行业内百分位排名，最终分归一化到 0~1。

#### 2.3.4 融合公式

```
final_score = direction_score × 0.5 + finance_score × 0.5
```

融合效果：
- 方向契合度高 + 财务好 → 高分（真正值得关注的标的）
- 方向契合度高 + 财务差 → 中分（炒作被基本面约束）
- 方向契合度低 + 财务好 → 中分（财务优秀但与行业主题无关）
- 方向契合度低 + 财务差 → 低分

权重可通过 `.env` 中的 `PROSPERITY_DIRECTION_WEIGHT` / `PROSPERITY_FINANCE_WEIGHT` 调整。

---

### 2.4 ReportAgent — 评级公式重构

#### 2.4.1 加权信号聚合

```
景气信号强度 = Σ(每条假设的信号值 × 层级权重 × causality 折扣)

其中：
  sentiment=positive  + CONFIRMED → +1.0
  sentiment=positive  + DISPUTED  → -0.5 (期待的好事没发生)
  sentiment=negative  + CONFIRMED → -1.0 (担心的风险被证实)
  sentiment=negative  + DISPUTED  → +0.5 (风险被推翻，利好)
  sentiment=neutral   + CONFIRMED → +0.3

  L0 权重 1.0  (基础事实最重要)
  L1 权重 0.8
  L2 权重 0.7
  L3 权重 0.5  (选股方向对行业整体景气影响较小)

  causality_strength=strong    → ×1.0
  causality_strength=moderate  → ×0.7
  causality_strength=weak      → ×0.4
  causality_strength=broken    → 同 DISPUTED
  UNVERIFIED/PARTIAL           → ×0.5
  UNREACHABLE                  → 不参与
```

#### 2.4.2 阈值映射

```
total_signal > 3.0  → 🔥 高景气
total_signal > 1.5  → ✅ 景气
total_signal > 0.0  → ⚠️  弱景气
total_signal ≤ 0.0  → ❄️ 不景气
```

阈值初始值来自假设结构的自然推断（3 条链路 × L0+L1 正面 CONFIRMED = ~3.0），后续通过回测校准。

#### 2.4.3 变更影响

旧公式只看 number of confirmed（计数），新公式看 weighted signal（加权聚合）。可控核聚变在旧公式下 7/12 CONFIRMED → 🔥 高景气，在新公式下：
- H2-3（估值泡沫风险，negative, partial）→ 信号值接近 0（不拖后腿也不加分）
- 各假设的 causality_strength 可能拉低总信号
- 预期评级可能从 🔥 降为 ✅，但也更真实

---

## 3. 数据与字段新增

### 3.1 HypothesizeAgent 输出新增字段

| 字段 | 类型 | 位置 |
|------|------|------|
| `sentiment` | `"positive"` / `"negative"` / `"neutral"` | 每条假设 |

### 3.2 VerifyAgent 输出新增字段

| 字段 | 类型 | 位置 |
|------|------|------|
| `status` | `"confirmed"` / `"partial"` / `"disputed"` / `"unverified"` | 每条假设 |
| `reason` | string | 每条假设 |
| `corrected_statement` | string / null | 每条假设 |
| `confidence` | `"high"` / `"medium"` / `"low"` | 每条假设 |
| `causality_strength` | `"strong"` / `"moderate"` / `"weak"` / `"broken"` | 每条假设 |
| `causality_note` | string | 每条假设 |
| `counter_evidence` | list[string] | 每条链路 |

### 3.3 ScreeningAgent 输出

| 字段 | 类型 |
|------|------|
| `direction_score` | 0~1 float |
| `matched_l3` | string (L3 假设 ID) 或 null |
| `matched_reason` | string |
| `finance_score` | 0~1 float |
| `final_score` | 0~1 float |

### 3.4 数据库变更

`hypotheses` 表新增字段：
- `sentiment` TEXT
- `causality_strength` TEXT
- `causality_note` TEXT

`stock_pools` 表新增字段：
- `direction_score` REAL
- `finance_score` REAL
- `matched_l3` TEXT
- `matched_reason` TEXT

---

## 4. 配置文件新增

### 4.1 `.env` 新增字段

```bash
# 高景气 — ScreeningAgent 融合权重
PROSPERITY_DIRECTION_WEIGHT=0.5
PROSPERITY_FINANCE_WEIGHT=0.5
```

### 4.2 `config.py` 默认值

```python
PROSPERITY_DIRECTION_WEIGHT: float = 0.5
PROSPERITY_FINANCE_WEIGHT: float = 0.5
```

---

## 5. 项目文件结构变更

```
backend/app/strategies/prosperity/
├── agents/
│   ├── search_agent.py          (不变)
│   ├── hypothesize_agent.py     (修改: +sentiment)
│   ├── verify_agent.py          (重构: LLM验证+反例搜索+后处理)
│   ├── screening_agent.py       (新增: LLM匹配+财务打分融合)
│   ├── report_agent.py          (修改: 评级公式重构)
│   └── track_agent.py           (不变)
│
├── tools/
│   ├── stock_screener.py        (修改: +真实动量, 仍为纯代码)
│   └── ...
│
└── coordinator.py               (修改: Counter→Screening, 管道5步)

# 删除
├── agents/counter_agent.py      (移除)
```

---

## 6. CodeBuddy Skills 变更

| 旧 Skill | 新 Skill | 状态 |
|----------|---------|:--:|
| `prosperity-search` | `prosperity-search` | 不变 |
| `prosperity-hypothesize` | `prosperity-hypothesize` | 不变 |
| `prosperity-verify` | `prosperity-verify` | Skill 文件更新 |
| `prosperity-counter` | — | 删除 |
| — | `prosperity-screening` | 新增 |
| `prosperity-report` | `prosperity-report` | 不变 |
| `prosperity-lint` | `prosperity-lint` | 不变 |

---

## 7. Web API 端点变更

| 旧端点 | 新端点 | 状态 |
|--------|--------|:--:|
| `/api/prosperity/search` | `/api/prosperity/search` | 不变 |
| `/api/prosperity/hypothesize` | `/api/prosperity/hypothesize` | 不变 |
| `/api/prosperity/verify` | `/api/prosperity/verify` | 不变（内部重构） |
| `/api/prosperity/counter` | — | 删除 |
| — | `/api/prosperity/screening` | 新增 |
| `/api/prosperity/report` | `/api/prosperity/report` | 不变 |
| `/api/prosperity/lint` | `/api/prosperity/lint` | 不变 |

---

## 8. 测试变更

| 测试 | 变更 |
|------|------|
| `test_prosperity_coordinator.py` | CounterAgent mock → ScreeningAgent mock；验证结果字段新增 sentiment/causality_strength 断言 |
| `test_spec_compliance.py` | 断言 6 Agent → 5 Agent；WebSearch 词数量断言（5条不变）；新增 ScreeningAgent 合规检查 |

---

## 9. 实现优先级

按对投资决策质量的影响排序：

```
P0: VerifyAgent LLM 重构（验证不再伪）
P0: ScreeningAgent 新增（股池与推理链连接）
P1: HypothesizeAgent sentiment 字段
P1: ReportAgent 评级公式重构
P2: VerifyAgent 反例搜索
P2: 动量真实数据
P2: Causality_strength
P3: CounterAgent 移除（重构后的清理）
```

P0 是必须一起做的（有 ScreeningAgent 没 VerifyAgent = 用伪验证结果打方向分；有 VerifyAgent 没 ScreeningAgent = 验证了推理链但股池仍然脱节）。

---

## 10. 设计决策记录

1. **验证范式从代码规则改为 LLM**：3 条 if-else 永远无法验证"营收增速 50%"这类语义性假设。LLM 验证能理解数据含义并进行交叉比对。
2. **按推理链分组串行验证而非逐条并行**：LLM 同时看到 4 层能判断因果箭头是否断裂，而非只检查独立事实。
3. **股池两阶段融合而非 LLM 全包**：纯 LLM 筛选有幻觉风险，纯代码筛选无法理解 L3 方向。两阶段互为约束。
4. **sentiment 由 HypothesizeAgent 生成而非 VerifyAgent 判定**：方向是假设的固有属性，生成时就知道。
5. **反例搜索词由 LLM 生成而非固定模板**：针对每条链路的具体内容定向搜索，比通用负面关键词有效得多。
6. **CounterAgent 移除而非保留**：验证 LLM 已产生完整认知判断（status + reason + corrected），不需要标签搬运工再处理一遍。
