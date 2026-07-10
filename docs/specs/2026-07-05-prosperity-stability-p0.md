# 高景气策略 P0 稳定性增强 — 设计 Spec

> 版本: v1.0 | 日期: 2026-07-05 | 状态: **已实施**
>
> 关联: 收敛性实验报告（`.codebuddy/memory/` + `data/prosperity/raw/人工智能/convergence_report.md`）
>
> 范围: **仅 VerifyAgent**（Plan A — 不碰 CounterAgent）

---

## 1. 背景与动机

### 1.1 实验结论

2026-07-05 对「人工智能」板块做了 3 轮收敛性实验——冻结全部外部输入（Search 缓存 14/14 命中、Hypothesize 产出 12 条完全相同假设、Tushare 数据一致），Temperature=0。

**结果**：3 次运行仍有 42 处差异，股池 20→12→18（±40%），信号强度 ±18%。

**差异归因**：

| 环节 | 差异数 | 占比 | 性质 |
|------|--------|------|------|
| **VerifyAgent LLM** | 25/42 | **60%** | **根因波动源** |
| 确定性合成 status | 8/42 | 19% | 纯下游，跟随 Q1/Q2/Q3 |
| CounterAgent LLM | 叠加 | — | 二次 LLM 调用 |
| 下游全局指标 | 9/42 | 21% | 纯级联后果 |

### 1.2 当前架构缺陷

v0.19 的"确定性合成"（`_synthesize_status`）虽然保证了 **status 合成** 的确定性，但它的 3 个输入仍是 LLM 单次调用的输出：

```
LLM（temperature=0，1次）
  ├─ Q1 source_count: 整数 0/1/2/3  ← 单轮计数不可靠
  ├─ Q2 data_alignment: 支持/部分支持/不支持/无相关数据  ← 单轮判断随机
  ├─ Q3 counter_conflict: yes/no  ← 二元判断杀伤力最大
  └─ sentiment: positive/negative/neutral  ← 单轮情感判断
    ↓
_synthesize_status() [确定性]  ← 上游不稳，下游再怎么确定都没用
```

**四个字段的波动特征**：

| 字段 | 3 轮差异数 | 最大波动模式 | 根因 |
|------|-----------|-------------|------|
| `source_count` | 5/12 链 | 0↔2 剧烈翻转 | LLM 不擅长精确计数 |
| `data_alignment` | 10/12 链 | "支持"↔"无相关数据" | LLM 对同一份 Tushare 数据方向判断随机 |
| `counter_conflict` | 2/12 链 | no→yes→no 全部覆盖 | 二元判断 + 模糊边界 = 随机 flip |
| `sentiment` | 8/12 链 | positive↔neutral | LLM 情感方向判断不稳 |

### 1.3 方案选择：Plan A（仅修 VerifyAgent）

B 修 VerifyAgent + CounterAgent，C 修 VerifyAgent + 砍 CounterAgent，**选择 A**：
- 60% 波动来自 VerifyAgent，修复后下游 CounterAgent 的输入自然更稳定
- CounterAgent 不改动，风险最低
- 后期如仍不满足稳定性，再对 CounterAgent 做多轮投票（成本低）

---

## 2. 核心设计：多轮投票

### 2.1 设计理念

**Self-Consistency**（Wang et al. 2022）：对同一 prompt 做多次 LLM 调用，对输出做多数投票/中位数/交集，利用"多次采样—聚合"消除单次随机性。

本设计的特殊之处：每个字段用最适合的聚合方式，而非统一取众数。

### 2.2 四字段聚合方案

| 字段 | 当前格式 | 新格式 | 轮数 | 聚合方式 | 理由 |
|------|---------|--------|------|---------|------|
| Q1 | `source_count: int` | `supporting_source_indices: [int]` | 3 | **交集** → count | LLM 易多数（幻觉），不会少数（漏真实信源）。交集过滤幻觉 |
| Q2 | `data_alignment: "支持"/...` | 不变 | 3 | **众数** | 保留 LLM 语义判断能力（如识别"结构性分化"） |
| Q3 | `counter_conflict: "yes"/"no"` | `counter_conflict_score: 0/1/2/3` | 3 | **MAX** | 安检逻辑：反例证据宁可多检不漏检 |
| Q4(新) | sentiment（原不在 verify prompt 中输出） | `sentiment: "positive"/"negative"/"neutral"` | 3 | **众数** | sentiment 方向判断，众数最稳健 |

### 2.3 Q1：source_count → supporting_source_indices

**为什么换格式**：
- LLM 输出"2"是不可审计的——不知道它数了哪两个信源
- LLM 输出 `[1, 3, 5]` 是可审计的——知道它指的是搜索素材的第 1/3/5 条
- 代码做 `len(intersection(round1, round2, round3))`，消除 LLM 的计数噪音

**prompt 变更**（verify_prompt.md）：
```
### Q1: source_count → supporting_source_indices
搜索素材中，哪些信源编号明确提供了支持该陈述的具体数据？
- 输出一个整数数组，如 [1, 3, 5]
- 只包含直接陈述该事实的信源编号
- 同一机构的多篇文章算同一信源（只写第一个编号）
- 无信源 → 输出 []
```

**代码变更**（verify_agent.py `_synthesize_status`）：
```python
# 旧: source_count = vh.get("source_count", 0)
# 新: 3 轮取交集
indices_r1 = set(r1_sources or [])
indices_r2 = set(r2_sources or [])
indices_r3 = set(r3_sources or [])
source_indices = indices_r1 & indices_r2 & indices_r3  # 交集
source_count = len(source_indices)
```

### 2.4 Q3：counter_conflict yes/no → 0-3 评分

**为什么换格式**：
- 当前 yes/no 是二元判断，对"边界情况"（很弱的反例/间接冲突）每次随机 flip
- 改为 0-3 分级后，边界情况落到 score=1，不触发级联
- 只有真正强的反例（score=2 或 3）才触发

**评分定义**（verify_prompt.md）：
```
### Q3: counter_conflict_score — 反例冲突程度
反例搜索证据中，对陈述的挑战程度：
- 3: 直接推翻（如「Token量实际在下降」推翻「Token量在增长」）
- 2: 明显矛盾（核心假设被质疑，但不完全推翻）
- 1: 间接怀疑（如「AI创业公司烧钱」→ 不直接推翻Token增长）
- 0: 无冲突
```

**代码变更**（verify_agent.py `_synthesize_status`）：
```python
# 旧: counter_conflict == "yes" → disputed
# 新: 3 轮取 MAX，≥2 触发
cc_rounds = [cc1, cc2, cc3]
cc_score = max(cc_rounds)  # MAX，不取众数
counter_conflict = "yes" if cc_score >= 2 else "no"
```

### 2.5 并行调用架构

```
_verify_chain_with_llm(chain):
  ├─ 构建完整 prompt（不变）
  └─ 并行调用 LLM × 3（asyncio.gather / concurrent.futures）
      ├─ round1 → {supporting_source_indices, data_alignment, counter_conflict_score, sentiment, reason, ...}
      ├─ round2 → ...
      └─ round3 → ...
        ↓
  └─ _aggregate_rounds(round1, round2, round3):
      ├─ Q1: 交集 → source_count
      ├─ Q2: 众数 → data_alignment
      ├─ Q3: MAX → counter_conflict
      ├─ sentiment: 众数 → sentiment
      └─ 其他字段（reason, corrected_statement, causality_strength, causality_note）→ 多数轮（取第一轮）
        ↓
  └─ _synthesize_status(source_count, data_alignment, counter_conflict)
  └─ _synthesize_confidence(source_count, data_alignment, counter_conflict)
```

---

## 3. 新增字段：sentiment 在 VerifyAgent 中输出

### 3.1 动机

当前 sentiment 是 HypothesizeAgent 生成的，VerifyAgent 不重新判断 sentiment。但收敛性实验显示：**假设的 sentiment 本身也有波动**——LLM 虽不直接输出 sentiment 字段，但 sentiment 是通过 hypothesis 文本在 HypothesizeAgent 阶段生成的。

实际上，sentiment 波动源自 HypothesizeAgent（8/12 链不一致），不是 VerifyAgent。但我们选择在 VerifyAgent 阶段做多轮重判，原因是：
1. HypothesizeAgent 已经做了历史锚定优化（读 wiki），进一步改动风险大
2. VerifyAgent 已经有验证上下文，做 sentiment 判断更准确
3. 改动集中在一个环节，好维护

### 3.2 Prompt 新增

在 verify_prompt.md 的「额外字段」部分新增：

```
### sentiment — 假设的情感方向（新增）
根据验证结果，判断该假设的整体方向：
- "positive": 描述的是利好/增长/机会方向
- "negative": 描述的是利空/衰退/风险方向
- "neutral": 描述的是结构性/中性状态
```

### 3.3 与 HypothesizeAgent sentiment 的关系

VerifyAgent 输出的 sentiment 作为**第二参考**，不是对 HypothesizeAgent sentiment 的覆盖：
- 正常流程：HypothesizeAgent sentiment → CounterAgent 可能修正 → ReportAgent 消费
- 3 轮投票后的 sentiment 写入 `verified_sentiment` 字段
- 下游（CounterAgent → ReportAgent）优先使用 `verified_sentiment`
- 保留 `sentiment`（原始值）作为审计痕迹

---

## 4. _synthesize_status / _synthesize_confidence 适配

### 4.1 status 合成规则（不变）

```python
def _synthesize_status(source_count, data_alignment, counter_conflict):
    if counter_conflict == "yes":      # Q3 MAX ≥ 2
        return "disputed"
    if source_count == 0:              # 3 轮交集为空
        return "unverified"
    if source_count == 1 or data_alignment == "不支持":
        return "partial"
    if source_count >= 2 and data_alignment in ("支持", "部分支持"):
        return "confirmed"
    return "partial"
```

输入变了（source_count 由交集计算，counter_conflict 由 MAX ≥ 2 计算），但规则本身不变。

### 4.2 confidence 合成规则（不变）

```python
def _synthesize_confidence(source_count, data_alignment, counter_conflict):
    if counter_conflict == "yes":
        return "high"
    if source_count >= 3 and data_alignment == "支持":
        return "high"
    if source_count >= 2 and data_alignment in ("支持", "部分支持"):
        return "high"
    if source_count >= 1 and data_alignment in ("支持", "部分支持"):
        return "medium"
    if source_count >= 1:
        return "medium"
    return "low"
```

同样，只有输入源自多轮投票，规则本身不变。

---

## 5. 受影响的文件（完整清单）

### 5.1 必须修改的文件

| 文件 | 操作 | 估计行数 | 风险 | 说明 |
|------|------|---------|------|------|
| `rules/prosperity/prompts/verify_prompt.md` | **修改** | ~30 | **中** | Q1 格式：int→[int]；Q3 格式：yes/no→0-3；+sentiment 输出 |
| `agents/verify_agent.py` | **修改** | ~100 | **中高** | +`_call_llm_with_retry` 独立方法；+`_aggregate_rounds`；`_verify_chain_with_llm` 改为 3 轮并行；解析格式适配 |
| `tests/test_prosperity_coordinator.py` | **修改/新增** | ~80 | 低 | 状态合成测试可能需更新输入格式；新增多轮投票 mock 测试 |

**合计 ~210 行代码变更**。

### 5.2 不受影响的文件

| 文件 | 原因 |
|------|------|
| `counter_agent.py` | **Plan A 不改 CounterAgent** |
| `coordinator.py` | 调用接口不变——`verify_agent.verify()` 返回格式不变 |
| `report_agent.py` | SIGNAL_MAP 不变，消费的字段（status/sentiment）仍存在 |
| `hypothesize_agent.py` | VerifyAgent 改动不触及 hypothese 生成 |
| `screening_agent.py` | 消费的是 status + sentiment，格式不变 |
| `search_agent.py` | 完全无关 |
| `learning_agent.py` | 完全无关 |
| `track_agent.py` | 完全无关 |
| `tools/*`（purity_scorer/stock_screener/industry_metrics 等） | 完全无关 |
| 前端 | 完全无关 |
| 龟龟策略 | 完全无关 |

### 5.3 下游消费者兼容性确认

| 消费方 | 消费的字段 | 是否受本次改动影响 |
|--------|-----------|------------------|
| CounterAgent `_llm_cascade()` | `status`, `sentiment`, `reason`, `corrected_statement`, `causality_strength`, `causality_note` | **否** — 字段名和值域不变 |
| ReportAgent `_assess_prosperity()` | `status`, `sentiment`, `chain_level`, `causality_strength` | **否** — 字段名和值域不变 |
| ReportAgent `_render_report()` | `status`, `sentiment`, `statement`, `reason`, `corrected_statement` 等 | **否** — 字段名和值域不变 |
| TrackAgent `extract_tracking()` | `key_indicators`, `status` | **否** |
| DB `Hypothesis` 表 | 全量字段 | **否** |

**对外接口完全不变** — status 仍是 confirmed/partial/disputed/unverified 四值，sentiment 仍是 positive/negative/neutral。唯一变化是**这些值变得更稳定**。

---

## 6. 关键设计决策

1. **Q3 用 MAX 不用 median**：反例冲突是"安检"逻辑——一条强反例就值得触发。3 轮中只要有一轮 score≥2，就应该标记 disputed。用 median 可能漏掉（一轮 score=3、两轮 score=0 → median=0 → 不触发）。

2. **Q1 用交集不用 median**：LLM 数信源容易多数（把无关内容也算信源）但几乎不会漏真实信源。所以 3 轮都认出 → 真信源；2/3 或 1/3 → 可能是幻觉。

3. **sentiment 新增 `verified_sentiment` 字段**：不覆盖原始 sentiment，下游可用 `h.get("verified_sentiment", h.get("sentiment"))`。

4. **3 轮并行调用**：不增加整体耗时（并行 3 × 串行 1 ≈ 串行 1 的时间）。成本 ×3，DeepSeek 单价极低，12 条链 × 3 轮 ≈ 0.02 元。

5. **其他字段（reason/corrected/causality）取第一轮**：这些字段的波动不直接导致 status 变化，不需要多轮投票。取第一轮即可。

6. **保留 _synthesize_status 确定性合成不变**：逻辑一层不变，只是输入由单轮 LLM → 多轮聚合。

7. **Plan A 边界**：CounterAgent 不改。VerifyAgent 稳定后，CounterAgent 的输入质量提升，自身波动自然减少。若仍不满意，后续再做 P1（CounterAgent 多轮投票）。

---

## 7. 版本号

- Spec 版本: v1.0
- 目标版本: v0.20.0（从 v0.19.1）
- pyproject.toml: 0.11.1 → 0.12.0

---

## 8. 与已有 Spec 的关系

- 本 Spec 是对 `docs/specs/2026-06-29-prosperity-strategy-design.md` §2.3（VerifyAgent）的增强
- 不改变 `docs/specs/2026-07-01-prosperity-strategy-v16-enhancement.md` 的架构
- 不改变 `docs/plans/2026-07-03-prosperity-cascade-fix.md` 的级联逻辑
- 与 `docs/specs/2026-07-04-llm-deterministic-verification.md`（v0.19）**叠加**——v0.19 做了合成确定性，本 Spec 做了输入稳定性
