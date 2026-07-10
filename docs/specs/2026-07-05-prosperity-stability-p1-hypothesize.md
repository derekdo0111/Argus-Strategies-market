# 高景气策略 P1 稳定性增强 — HypothesizeAgent 两阶段设计 Spec

> 版本: v1.0 | 日期: 2026-07-05 | 状态: **设计中**
>
> 来源: Brainstorming → 收敛性实验分析 → 本 Spec
>
> 关联 Spec:
> - `docs/specs/2026-06-29-prosperity-strategy-design.md` §2.2（原 HypothesizeAgent 设计）
> - `docs/specs/2026-07-05-prosperity-stability-p0.md`（P0 VerifyAgent 3 轮投票）
>
> 目标版本: v0.21.0

---

## 1. 背景与动机

### 1.1 实验结论：HypothesizeAgent 是第二大波动源

P0 修复了 VerifyAgent（3 轮并行 LLM + 字段级聚合），使 Q3 counter_conflict 100% 稳定。但收敛性实验进一步揭示了：**HypothesizeAgent 的输出在 3 次运行中 12≠14 条假设，凭空出现/消失一整条"国产替代"推理链**。

| 维度 | Run 1 | Run 2 | Run 3 | 一致？ |
|------|-------|-------|-------|:---:|
| 假设数量 | 12 | 14 | 14 | ❌ |
| H2-4「国产替代加速」 | ❌ 不存在 | ✅ | ✅ | ❌ |
| H3-4「配置国产替代龙头」 | ❌ 不存在 | ✅ | ✅ | ❌ |
| statement 文本 | 3 版本措辞不同 | — | — | ❌ |
| confidence (H0-1) | high | high | medium | ❌ |
| sentiment (H1-2) | neutral | negative | positive | ❌ |

### 1.2 当前架构缺陷

```
14 条 Tavily 搜索结果（100% 缓存命中）
         │
         ▼
   HypothesizeAgent
   一次 LLM 调用 × temperature=0
         │
         ▼
   12 或 14 条假设（不可预测）
```

**根因**：

1. **单次 LLM 调用 × temperature=0 ≠ 确定性**：DeepSeek temperature=0 在当前 118 行 prompt 下不产生确定性输出。与 P0 修复前的 VerifyAgent 一模一样。
2. **LLM 同时产出"树结构"和"叶子内容"**：一次调用既要决定推理链有多少条、怎么分叉，又要写每条的具体文本。结构 + 内容耦合，放大了随机性。
3. **prompt 约束全是软性的**：L0 2-3 条、L1 2-4 条、L2 2-4 条、L3 2-3 条。LLM 在上下限间游走完全合法。
4. **下游级联放大**：+2 条假设 → VerifyAgent 多验证 2 条 → CounterAgent 多处理 2 条 → ScreeningAgent 输出 0→23 股 → ReportAgent 评级波动 ±1 级。

### 1.3 8 个已识别问题

| # | 问题 | 严重度 | 实验证据 |
|---|------|:---:|------|
| 1 | 假设数量不稳定 12≠14 | 🔴 致命 | 3 次运行 2 种输出 |
| 2 | 新链条凭空出现/消失（国产替代） | 🔴 致命 | Run 2/3 独有 |
| 3 | 新增链条质量极差（source_count 1↔0） | 🟡 重 | H2-4/H3-4 验证惨败 |
| 4 | 共享假设的 statement 文本漂移 | 🟡 重 | 3 版本语序不同 |
| 5 | confidence 字段不一致 | 🟡 重 | H0-1: high↔medium |
| 6 | sentiment 字段不一致 | 🟡 重 | H1-2: neutral↔negative↔positive |
| 7 | prompt 约束是软性的 | 🟡 重 | "2-4 条"给 LLM 自由裁量 |
| 8 | 单次调用 × temp=0 非确定 | 🔴 根本 | 与 VerifyAgent 同样的 bug |

---

## 2. 核心设计：两阶段分离 + 3 轮投票

### 2.1 设计理念

**把 LLM 一次调用同时产出的"树结构"和"叶子内容"拆开**：

```
当前：
┌─────────────────────────────────────────┐
│          一次 LLM 调用产出                 │
│  ┌──────────────┐ ┌────────────────────┐ │
│  │ 树结构        │ │ 叶子内容            │ │
│  │ id/层级/上下游│ │ statement/sentiment/ │ │
│  │ (12 vs 14)   │ │ confidence/sources/  │ │
│  │              │ │ reasoning            │ │
│  └──────────────┘ └────────────────────┘ │
└─────────────────────────────────────────┘

v0.21 两阶段：
Phase 1: 骨架（3 轮投票）          Phase 2: 填充（1 轮强约束）
┌──────────────────────┐           ┌──────────────────────┐
│ 3 轮 LLM 并行         │           │ 1 轮 LLM              │
│ 只输出:               │  ──传递──→ │ 骨架不可增删改         │
│ id + title +          │  固定骨架   │ 只填充:              │
│ chain_level +         │           │ statement +          │
│ derives_from          │           │ reasoning +          │
│                       │           │ sentiment +          │
│ 投票后: 稳定骨架       │           │ confidence +         │
│                       │           │ sources +            │
│                       │           │ key_indicators + ... │
└──────────────────────┘           └──────────────────────┘
```

### 2.2 Phase 1：骨架生成（3 轮投票）

#### 2.2.1 Prompt 极简化

Phase 1 只要求 LLM 输出 4 个字段（当前 118 行 prompt → 估计 ~40 行）：

```
你是一位行业研究分析师。基于以下情报，构建「{industry_name}」因果推理链的骨架。

## 情报
{results_text}

## 输出要求
只输出 JSON 数组，每个元素仅有 4 个字段：
- id: H{层级}-{序号}
- title: ≤10字
- chain_level: 0/1/2/3
- derives_from: 字符串数组

层级约束：
- L0: 2-3条现状诊断，derives_from=[]
- L1: 2-4条一阶推演，每条derives_from引用≥1个L0的id
- L2: 2-4条二阶推演，每条derives_from引用≥1个L1的id
- L3: 2-3条投资落点，每条derives_from引用≥1个L2的id
- 不允许死胡同：每条L1≥1条L2，每条L2≥1条L3
```

**为什么短 prompt 有利于稳定性**：

- Token 少 → LLM 的 softmax 分布更集中
- 输出结构简单（4 字段 vs 当前 12 字段） → JSON 解析失败概率低
- 不需要 reasoning/sources 等自由文本 → LLM 没有"措辞自由度"

#### 2.2.2 投票策略：ID + title 双重匹配

```python
def _aggregate_skeletons(self, rounds: list[list[dict]]) -> list[dict]:
    """对 3 轮骨架投票，返回稳定骨架"""
    # Step 1: 按 ID 收集
    id_counter = Counter()
    id_details = {}  # id → {"titles": [...], "derives": [...], "level": int}
    
    for round_hyps in rounds:
        seen = set()
        for h in round_hyps:
            h_id = h.get("id", "")
            if h_id in seen:
                continue
            seen.add(h_id)
            id_counter[h_id] += 1
            if h_id not in id_details:
                id_details[h_id] = {
                    "titles": [],
                    "derives": [],
                    "level": h.get("chain_level", 0),
                }
            id_details[h_id]["titles"].append(h.get("title", ""))
            id_details[h_id]["derives"].append(tuple(sorted(h.get("derives_from", []))))
    
    # Step 2: ID + title 双重校验
    # 同一 ID 下 title 相似度 < 0.5 → 视为不同假设，分别投票
    skeleton = []
    for h_id, count in id_counter.items():
        if count < 2:  # 保留出现 ≥2 轮的假设
            continue
        detail = id_details[h_id]
        title = Counter(detail["titles"]).most_common(1)[0][0]
        derives = list(Counter(detail["derives"]).most_common(1)[0][0])
        skeleton.append({
            "id": h_id,
            "title": title,
            "chain_level": detail["level"],
            "derives_from": derives,
        })
    
    return skeleton
```

#### 2.2.3 链完整性回填

投票可能破坏链完整性（如 L2 被 2/3 轮保留但 L3 只 1/3 轮被丢弃 → 死胡同）。

```python
def _fix_chain_completeness(self, skeleton, discarded):
    """确保每条 L1 有 ≥1 条 L2，每条 L2 有 ≥1 条 L3"""
    for h in skeleton:
        if h["chain_level"] in (1, 2):
            has_downstream = any(
                h["id"] in other.get("derives_from", [])
                for other in skeleton
                if other["chain_level"] == h["chain_level"] + 1
            )
            if not has_downstream:
                # 从被丢弃的假设中找回下游
                rescued = self._rescue_downstream_for(h["id"], discarded, h["chain_level"] + 1)
                if rescued:
                    skeleton.append(rescued)
    return skeleton
```

#### 2.2.4 三轮全分歧兜底

如果 ≥2/3 规则过滤后骨架为空（极其罕见），降级取第一轮骨架，标记低置信度：

```python
if not skeleton:
    logger.warning("Phase 1: all 3 rounds diverged, falling back to round 1 skeleton")
    skeleton = rounds[0]
    skeleton_confidence = "low"
```

### 2.3 Phase 2：内容填充（1 轮 + 骨架强约束）

#### 2.3.1 Prompt 设计

Phase 2 给 LLM 一个"不可增删改"的骨架文本：

```
你是一位行业研究分析师。以下是已确定的推理链骨架，请为每条假设填充详细内容。

## 推理链骨架（不可修改，不可增删）
{skeleton_text}

## 情报
{results_text}

## 要求
- 严格按照骨架中的 id/title/chain_level/derives_from，不可增删改任何假设
- 只填充以下字段：statement, reasoning, sentiment, confidence, sources, verification_needed, key_indicators, investment_implication, time_horizon
- 每条 L0 statement 必须引用 ≥3 个情报信源编号
- statement 必须可直接证实/证伪
- reasoning 必须体现「因为上游 → 所以本条 → 导致下游」的逻辑箭头
- sentiment 用 positive/negative/neutral
- key_indicators 每个元素是对象：name/frequency/search_query/expected_direction

输出 JSON（保留骨架中的 id/title/chain_level/derives_from，填充其余字段）
```

骨架文本示例：

```
- H0-1 [L0] AI算力需求爆发 (derives_from: 无)
- H0-2 [L0] 产业链盈利高增 (derives_from: 无)
- H0-3 [L0] AI应用加速落地 (derives_from: 无)
- H1-1 [L1] AI基建投资扩张 (derives_from: H0-1, H0-2)
- H1-2 [L1] 存储涨价周期延续 (derives_from: H0-2)
- H1-3 [L1] 推理算力需求扩张 (derives_from: H0-3)
- H2-1 [L2] 算力投资过热风险 (derives_from: H1-1)
- H2-2 [L2] HBM胜出 (derives_from: H1-2)
- H2-3 [L2] 端侧AI崛起 (derives_from: H1-3)
- H2-4 [L2] 国产替代加速 (derives_from: H1-1)
- H3-1 [L3] 聚焦算力核心设备 (derives_from: H2-1)
- H3-2 [L3] 布局HBM弹性标的 (derives_from: H2-2)
- H3-3 [L3] 布局端侧AI (derives_from: H2-3)
- H3-4 [L3] 配置国产替代龙头 (derives_from: H2-4)
```

#### 2.3.2 程序化校验 + 重试

Phase 2 输出后校验骨架一致性：

```python
def _validate_fill_output(self, filled: list[dict], skeleton: list[dict]) -> bool:
    skeleton_ids = {h["id"] for h in skeleton}
    filled_ids = {h["id"] for h in filled}
    
    if skeleton_ids != filled_ids:
        missing = skeleton_ids - filled_ids
        extra = filled_ids - skeleton_ids
        logger.warning(f"Skeleton mismatch: missing={missing}, extra={extra}")
        return False
    
    for h in filled:
        expected = next((s for s in skeleton if s["id"] == h["id"]), None)
        if expected is None:
            continue
        if set(h.get("derives_from", [])) != set(expected.get("derives_from", [])):
            logger.warning(f"derives_from changed for {h['id']}")
            return False
    
    return True

# 调用方式：
for attempt in range(3):
    llm_output = self._call_llm_phase2(prompt, skeleton)
    filled = self._parse_hypotheses(llm_output)
    if self._validate_fill_output(filled, skeleton):
        return filled
    logger.warning(f"Phase 2 validation failed, attempt {attempt + 1}/3")

logger.error("Phase 2: all 3 attempts failed skeleton validation")
return []  # 兜底空返回
```

#### 2.3.3 为什么 Phase 2 只需 1 轮

Phase 2 产出的字段下游全都会被 VerifyAgent 重新审视或覆盖：

| Phase 2 字段 | 下游覆盖者 | 是否需要投票 |
|-------------|-----------|:---:|
| id/title/derives_from | Phase 1 已固定 | ❌ |
| statement | VerifyAgent Q1（交集计数） | ❌ |
| reasoning | 仅用于人类阅读 | ❌ |
| sentiment | VerifyAgent Q4（众数）→ verified_sentiment | ❌ |
| confidence | VerifyAgent 重新计算 | ❌ |
| sources | VerifyAgent Q1 重新评估 | ❌ |
| verification_needed | VerifyAgent 生成 counter queries | ⚠️ |

---

## 3. 解决的 8 个问题（对照表）

| # | 问题 | 如何解决 | 解决程度 |
|---|------|---------|:---:|
| 1 | 假设数量 12≠14 | Phase 1 3 轮投票 → 骨架固定 | ✅ |
| 2 | 新链条凭空出现 | ≥2/3 轮才保留，过滤 1 轮噪音 | ✅ |
| 3 | 新链条质量差 | 保留的被 Phase 2 正确填充，丢弃的不存在 | ⚠️ |
| 4 | statement 文本漂移 | Phase 2 用固定 title/derives_from 约束 | ⚠️ |
| 5 | confidence 不一致 | VerifyAgent 会覆盖 | ✅ |
| 6 | sentiment 不一致 | VerifyAgent Q4 会覆盖 | ✅ |
| 7 | prompt 约束软性 | Phase 2 骨架是硬约束 | ✅ |
| 8 | 单次调用非确定 | Phase 1 用 3 轮投票消除 | ✅ |

---

## 4. 8 个风险与修复方案

| # | 风险 | 严重度 | 发生概率 | 修复 |
|---|------|:---:|:---:|------|
| R1 | ID 语义漂移（同 ID 不同概念） | 🔴 高 | 低 | ID + title 编辑距离双重校验 |
| R2 | 链完整性被投票破坏 | 🟡 中 | 中 | 投票后回填缺失下游 |
| R3 | 稳定地保留一条烂假设（国产替代） | 🟡 中 | 高 | ScreeningAgent 应正确跳过 unreachable，属下游问题 |
| R4 | 三轮全分歧 → 骨架为空 | 🟡 中 | 低 | 降级取第一轮骨架，标记低置信度 |
| R5 | Phase 2 LLM 创造性破坏骨架 | 🔴 高 | 中 | 程序化校验 + 最多 2 次重试 |
| R6 | statement 仍有措辞漂移 | 🟢 低 | 低 | 下游影响可控，可接受 |
| R7 | 性能退化 1.8-2.5x | 🟡 中 | 低 | Phase 1 单轮超时 25s，超时丢弃 |
| R8 | sentiment 仍在骨架外 | 🟡 中 | 中 | CounterAgent 后续修复吸收 |

### 4.1 R1 详细修复：ID + title 双重匹配

```python
from difflib import SequenceMatcher

def _match_hypotheses_across_rounds(self, rounds):
    # 第一遍：纯 ID 匹配
    # 第二遍：对同一 ID 下 title 相似度 < 0.5 的，视为不同假设
    # 第三遍：合并，重新按 rules 计数
```

### 4.2 R5 详细修复：Phase 2 骨架校验

见 §2.3.2 的 `_validate_fill_output()`。

---

## 5. LLM 调用与性能

| 阶段 | 调用次数 | 每次耗时 | 并行？ |
|------|:---:|------|:---:|
| Phase 1 (骨架) | 3 | ~15-20s/次（短 prompt） | ✅ 并行 |
| Phase 2 (填充) | 1 | ~30-40s | — |
| **总计** | **4** | **~45-55s** | |

vs 当前 1 次调用 ~30-40s。多了 ~15-25s，换取骨架确定性。

### 5.1 超时保护

```python
# Phase 1 单轮超时 25s，超时则丢弃该轮
TIMEOUT_PHASE1_SINGLE = 25  # 秒
# Phase 2 单次超时 60s
TIMEOUT_PHASE2 = 60
```

### 5.2 配置开关

新增 `.env` 配置项：

```bash
# HypothesizeAgent 稳定性增强
PROSPERITY_HYPOTHESIZE_ROUNDS=3       # Phase 1 轮数，设为 1 降级为单轮（调试用）
PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT=25  # Phase 1 单轮超时秒数
```

---

## 6. 新增文件 / 受影响的文件

### 6.1 必须修改的文件

| 文件 | 操作 | 估计行数 | 风险 | 说明 |
|------|------|---------|------|------|
| `agents/hypothesize_agent.py` | **重写** | ~200 | **高** | 拆为 Phase 1 + Phase 2 |
| `rules/prosperity/prompts/hypothesize_phase1_prompt.md` | **新建** | ~50 | 低 | Phase 1 骨架 prompt |
| `rules/prosperity/prompts/hypothesize_phase2_prompt.md` | **新建** | ~60 | 低 | Phase 2 填充 prompt |
| `core/config.py` | **修改** | ~5 | 低 | 新增配置项 |
| `.env` / `.env.example` | **修改** | ~3 | 低 | 新增配置项 |

### 6.2 不受影响的文件

| 文件 | 原因 |
|------|------|
| `coordinator.py` | 调用接口不变——`HypothesizeAgent.form_hypotheses()` 返回格式不变 |
| `verify_agent.py` | 输入仍是 `list[dict]` 假设，格式不变 |
| `counter_agent.py` | 消费的字段（status/sentiment/statement 等）值域不变 |
| `screening_agent.py` | 消费的是 L3 investment_implication + 假设集，格式不变 |
| `report_agent.py` | 消费的字段不变 |
| `search_agent.py` | 完全无关 |
| `learning_agent.py` | 完全无关 |
| `track_agent.py` | 完全无关 |
| `tools/*` | 完全无关 |
| 前端 / 龟龟策略 | 完全无关 |

### 6.3 下游消费者兼容性确认

| 消费方 | 消费的字段 | 是否受本次改动影响 |
|--------|-----------|:---:|
| VerifyAgent | 所有假设字段（id, title, statement, sentiment, ...） | **否** — 字段名和值域不变 |
| CounterAgent `_llm_cascade()` | `status`, `sentiment`, `reason` 等 | **否** |
| ReportAgent `_assess_prosperity()` | `status`, `sentiment`, `chain_level` | **否** |
| ScreeningAgent | L3 `investment_implication`, 假设集 | **否** |
| TrackAgent | `key_indicators`, `status` | **否** |
| DB `Hypothesis` 表 | 全量字段 | **否** |

**对外接口完全不变**。唯一变化：假设数量和树结构变稳定。

---

## 7. 关键设计决策

1. **Phase 1 用 ≥2/3 规则而非全票**：国产替代在 2/3 轮出现，说明在多数情况下有意义。全票会丢弃合理的推理方向。
2. **Phase 1 只输出 4 字段**：id/title/level/derives_from 是纯结构信息，不含自由文本。短 prompt → 更稳定的输出。
3. **Phase 2 用 1 轮不投票**：Phase 2 产出的字段下游全被 VerifyAgent 覆盖。投票没收益。
4. **ID + title 双重匹配**：防止 LLM 给不同概念分配相同 ID。title 编辑距离 < 0.5 视为不同假设。
5. **链完整性回填**：投票可能破坏链完整性（L2 保留但 L3 被丢弃）→ 投票后回填缺失的下游。
6. **Phase 2 骨架校验 + 重试**：程序化防止 LLM "创造性"地改骨架。最多重试 2 次。
7. **降级兜底**：Phase 1 三轮全分歧 → 取第一轮。Phase 2 三次校验失败 → 返回空。确保不阻塞 pipeline。

---

## 8. 版本号

- Spec 版本: v1.0
- 目标版本: v0.21.0（从 v0.20.0）
- pyproject.toml: 0.12.0 → 0.13.0

---

## 9. 与已有 Spec 的关系

- 本 Spec 是对 `2026-06-29-prosperity-strategy-design.md` §2.2（HypothesizeAgent）的重写
- 与 `2026-07-05-prosperity-stability-p0.md`（P0 VerifyAgent）**叠加**——两者共同消除最大两个波动源
- P0 后仍有 P2：CounterAgent 软衰减（待本 Spec 实施后评估残余差异量再决定规模）
