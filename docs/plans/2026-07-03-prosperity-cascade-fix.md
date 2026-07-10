# 高景气策略 Cascade 修复 — 实施计划

> 版本: v1.1 | 日期: 2026-07-03 | 状态: **已实施 + 去极性化修正**
>
> 来源: brainstorming 会话（2026-07-03）→ 本计划 → 去极性化修正
>
> 关联 Spec: `docs/specs/2026-06-29-prosperity-strategy-design.md`（CounterAgent §2.4, VerifyAgent §2.3）
>
> 修复版本: v0.11.0

---

## 0. 问题摘要

对「人工智能」行业的全链路分析发现 **4 个结构性问题**：

| 编号 | 严重度 | 问题 | 根因 | 影响 |
|------|--------|------|------|------|
| **P0** | 致命 | **sentiment 字段在 VerifyAgent 合并时被丢弃** | `_parse_verification_result` 保留字段列表缺少 `sentiment` / `causality_strength` / `causality_note` | ReportAgent 全部按 neutral 计算，信号从 2.86 被压低到 0.65，评级从「景气」→「弱景气」 |
| **P0** | 致命 | H0-2 "AI公司业绩中位数增长超400%" 是 LLM 幻觉 | HypothesizeAgent 一次 LLM 生成 12 条假设，无量化断言 vs 搜索素材的自动比对 | 被 VerifyAgent 用 Tushare 硬数据证伪 → disputed → overturned → 级联 4 条全废 |
| **P1** | 严重 | Chain C（AI 应用）终止于 L1，无 L2/L3 | HypothesizePrompt 只约束数量（2-4条/层），未要求结构性完整 | H1-3 的正向信号浪费，无对应投资落点 |
| **P2** | 中等 | SIGNAL_MAP 5/9 覆盖 → 缺失的 4 种组合信号零化 | 缺 (positive, partial)/(negative, partial)/(positive, unverified)/(negative, unverified) | 评级偏保守，partial 被双重打折 |

### v1.1 去极性化修正（2026-07-03 brainstorming 后续）

v1.0 方案中 CounterAgent 使用了**极性感知级联**（positive+disputed→切 / negative+disputed→保活），但这在逻辑上是错误的：

- 被证伪的前提（不论 positive 还是 negative）推导出的下游都应该切断——前提不成立，推理链从根部断裂
- "坏消息被否认 = 利好"这个信号不应该从错误的推理中榨取，真正的正向信号应来自正向假设的 confirmed
- 实际数据中 HypothesizeAgent 极少产出 negative 假设（本次 12 条中 0 条），极性规则几乎无实战受益者

**修正**：CounterAgent 的三遍扫描改为纯机械——不区分 polarity，所有 DISPUTED 一律 → OVERTURNED → 级联下游 UNREACHABLE。

---

## 1. 修复方案：四层架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: VerifyAgent sentiment 保留修复（P0 修复 — v1.1 新增）   │
│  ├─ 修改 verify_agent.py _parse_verification_result()           │
│  │   保留字段列表新增: sentiment, causality_strength,            │
│  │   causality_note                                             │
│  └─ 根因: LLM 验证输出不产 sentiment → 合并时丢失 →              │
│           ReportAgent 全部按 neutral 计算                        │
├─────────────────────────────────────────────────────────────────┤
│ Layer 2: CounterAgent 级联去极性化（P0 修正 — v1.1）              │
│  ├─ 修改 counter_agent.py _build_cascade_prompt():              │
│  │   移除极性规则 → 改为纯三遍扫描（不区分 positive/negative）     │
│  ├─ 修改 _hardcoded_polarity_cascade() → 重命名为                │
│  │   _hardcoded_cascade()，去掉极性判断                          │
│  └─ 所有 DISPUTED 一律 → OVERTURNED → 下游 UNREACHABLE           │
├─────────────────────────────────────────────────────────────────┤
│ Layer 3: Hypothesize 链结构完整性约束（P1 修复）                   │
│  ├─ 修改 hypothesize_prompt.md：新增"链结构完整性"规则             │
│  └─ 修改 hypothesize_agent.py：_validate_chain_completeness()    │
├─────────────────────────────────────────────────────────────────┤
│ Layer 4: SIGNAL_MAP 补全 + 双重折扣移除（P2 修复）                 │
│  └─ 修改 report_agent.py：10 种组合全覆盖 + 移除 0.5× 惩罚        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Layer 1: VerifyAgent sentiment 保留修复（v1.1 新增）

### 2.1 问题

`verify_agent.py` 的 `_parse_verification_result()` 在合并 LLM 验证输出与原始假设时，保留字段列表缺少 `sentiment`、`causality_strength`、`causality_note`。LLM 验证 prompt 不要求返回 sentiment（sentiment 是假设的固有属性），导致合并后这些字段全部丢失。

ReportAgent 中：
```python
sentiment = h.get("sentiment", "neutral")  # 全部兜底为 neutral
```

结果：所有假设按 neutral 计算 → 信号被系统性压低（本次 AI 行业：2.86 → 0.65）。

### 2.2 修复

**文件**: `backend/app/strategies/prosperity/agents/verify_agent.py`（L447-449）

**修改前**：
```python
for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
            "sources", "time_horizon", "key_indicators", "investment_implication",
            "wiki_path", "verification_needed", "tier"):
```

**修改后**：
```python
for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
            "sources", "time_horizon", "key_indicators", "investment_implication",
            "wiki_path", "verification_needed", "tier",
            "sentiment", "causality_strength", "causality_note"):
```

### 2.3 影响

修复后 sentiment 正确传递到 CounterAgent → ReportAgent，信号从 0.65 → ~2.86，「弱景气」→「景气」。

### 2.4 不需要更新测试

`sentiment` 是 HypothesizeAgent 产出的字段，现有测试 mock 数据中已包含。修复后只是不再丢失，不影响测试断言。

---

## 3. Layer 2: CounterAgent 级联去极性化

### 3.1 状态机修正（v1.1 去极性化）

**当前（v1.0 — 极性感知，已废弃）**：
```
DISPUTED + positive → OVERTURNED → 下游 UNREACHABLE
DISPUTED + negative → 保活（risk_denied）
```

**修正后（v1.1 — 纯机械三遍扫描）**：
```
VerifyAgent 产出                    CounterAgent 三遍扫描
───────────────                    ─────────────────────

DISPUTED  ─────────────────→   ① DISPUTED → OVERTURNED ⚰️
                                  （不区分 positive/negative，一律推翻）
                               ② 上游 OVERTURNED → 下游 UNREACHABLE
                                  （级联传播，不区分极性）
                               ③ PARTIAL → 降级置信度
                                  （不切断链）

UNVERIFIED ────────────────→   不操作, 留给 TrackAgent

另: corrected_statement 存在 → 修正 sentiment（保留 original_sentiment）
```

**去极性化理由**：
- 被证伪的前提（不论 sentiment）→ 下游不可达 —— 逻辑完整性不因方向改变
- "负向被证伪 = 利好"不应从错误推理中榨取，真正利好应由正向假设的 confirmed 捕获
- 实际数据中 HypothesizeAgent 极少产出 negative 假设，极性规则几乎无实战受益者

### 3.2 修改 `counter_agent.py` — LLM prompt 去极性化

**修改 `_build_cascade_prompt()` 中的级联规则**：

**修改前（v1.0 — 有极性规则）**：
```
1. positive + disputed → 切断下游
2. negative + disputed → 保持活跃
3. partial → 降级置信度
...
```

**修改后（v1.1 — 三遍扫描）**：
```python
return f"""你是投资研究级联分析专家。以下是「{industry_name}」行业经过数据交叉验证后的假设链。

## 任务一：级联裁决

根据每条假设的完整五维验证结果，判断其与上下游的级联关系。

### 级联规则（必须严格遵守）

1. **disputed → overturned**：被数据证伪的假设，不论 sentiment，一律标记 overturned
2. **overturned / unreachable → 切断下游**：被推翻的假设，其下游自动 unreachable
3. **partial → 降级置信度**：数据不充分，不切断链，只降 confidence
4. **confirmed → 正常传递**
5. **参考 corrected_statement**：如果 LLM 验证给出了修正版陈述，级联时以修正版为判断依据

## 任务二：sentiment 修正

如果某条假设的 corrected_statement 非空，判断修正后的陈述是否改变 sentiment：
（规则同上，不变）
"""
```

### 3.3 修改硬编码降级 `_hardcoded_polarity_cascade()` → `_hardcoded_cascade()`

去掉 polarity 判断。硬编码降级做三件事：
1. corrected_statement 关键词 sentiment 修正（不变）
2. disputed → overturned（统一，不区分 polarity）
3. overturned → 下游 unreachable（级联传播）

### 3.4 修改 `coordinator.py`

**位置 1: PIPELINE_STEPS（第 35-43 行）**

```python
PIPELINE_STEPS = [
    "search",
    "learn",
    "hypothesize",
    "verify",
    "counter",      # 新增：Phase 3.5 LLM 语义级联裁决
    "screening",
    "report",
    "done",
]
```

**位置 2: Phase 3 → Phase 3.5 插入（第 262 行后）**

在 `_p("3/5 verify", "done", ...)` 之后、`_p("4/5 screening", "start", ...)` 之前插入：

```python
            # Phase 3.5: CounterAgent — LLM 语义级联裁决
            _p("3.5/5 counter", "start", "LLM semantic cascade...")
            self.update_step(session_id, "counter")
            verified_hypotheses = verification.get("hypotheses", [])
            cascade_result = self._run_counter_agent(
                industry_name, session_id, verified_hypotheses
            )
            verification["hypotheses"] = cascade_result
            # 重新统计（unreachable 可能增加或减少）
            cascade_statuses = {}
            for h in cascade_result:
                s = h.get("status", "unverified")
                cascade_statuses[s] = cascade_statuses.get(s, 0) + 1
            unreachable_count = cascade_statuses.get("unreachable", 0)
            overturned_count = cascade_statuses.get("overturned", 0)
            _p("3.5/5 counter", "done",
               f"cascade applied (overturned={overturned_count}, unreachable={unreachable_count})")
```

**位置 3: 新增方法（在 `_run_verify_agent` 后面）**

```python
    def _run_counter_agent(
        self, industry_name: str, session_id: int, verified_hypotheses: list[dict]
    ) -> list[dict]:
        """Phase 3.5: CounterAgent LLM 语义级联裁决"""
        from app.strategies.prosperity.agents.counter_agent import CounterAgent
        agent = CounterAgent(self.data_dir, self.rules_dir)
        return agent.cascade(industry_name, session_id, verified_hypotheses)
```

**同时修改 Step 3/4/5 的打印编号**：`3/5` → `3/6`, `4/5` → `4/6`, `5/5` → `5/6`（因为新增了 counter 步骤），或者将打印从 `X/5` 改为 `X/6`。

建议改为非硬编码格式：
```python
_p("3/6 verify", ...)
_p("4/6 counter", ...)
_p("5/6 screening", ...)
_p("6/6 report", ...)
```

### 3.5 不删除 `verify_agent._cascade_safety_net`

原因：作为**第三级降级**。当 CounterAgent LLM 调用失败 + 硬编码规则也失败时，原安全网仍然生效。

更精确的处理：
- CounterAgent 替代了 `_cascade_safety_net` 的角色
- 保留 `_cascade_safety_net` 代码不动（最小化改动），但因为它只在 `_verify_single_chain` 流程中调用，而 CounterAgent 在 Coordinator 层调用——两者时序上是 CounterAgent 在前，`_cascade_safety_net` 在后
- 需要确认 `_cascade_safety_net` 不会被重复执行破坏 CounterAgent 的判决

**处理方案**：在 `verify_agent.py` 中，`_verify_chains()` 方法的级联调用处增加判断——如果 hypotheses 已包含 `cascade_note` 或 `original_sentiment` 等 CounterAgent 标注字段，跳过 `_cascade_safety_net`。

---

## 4. Layer 3: Hypothesize 链结构完整性约束

### 4.1 修改 `hypothesize_prompt.md`

在「关键规则」部分（第 110 行区域），新增规则 8：

```markdown
8. **链结构完整性**：每条 L0 必须至少产生 1 条 L1（可从多条 L0 合并导出），
   每条 L1 必须至少产生 1 条 L2，每条 L2 必须至少产生 1 条 L3。
   不允许出现"死胡同"推理链——如果某条 L1 确实无法推导出 L2，
   说明它不适合作为独立推理链，应合并到其他链条或删除。
```

### 4.2 修改 `hypothesize_agent.py`

在 `_parse_hypotheses()` 方法返回 hypotheses 前（第 281 行 `return hypotheses` 之前），加入验证调用：

```python
        # v0.10.0: 链结构完整性验证（警告不阻断）
        self._validate_chain_completeness(hypotheses, industry_name)

        return hypotheses
```

新增方法：

```python
    def _validate_chain_completeness(
        self, hypotheses: list[dict], industry_name: str
    ) -> None:
        """验证推理链结构完整性。

        警告不阻断——LLM 产出后仅打日志，让用户决定是否重跑。
        """
        by_id = {h.get("id", ""): h for h in hypotheses}

        # 收集 L1 和 L2
        l1_items = [h for h in hypotheses if h.get("chain_level") == 1]
        l2_items = [h for h in hypotheses if h.get("chain_level") == 2]

        # 构建反向索引：哪些下游引用了该 id
        children_map: dict[str, list[str]] = {}
        for h in hypotheses:
            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]
            for up_id in derives:
                children_map.setdefault(up_id, []).append(h.get("id", "?"))

        # 检查 L1 → L2
        for h in l1_items:
            h_id = h.get("id", "")
            if h_id not in children_map:
                logger.warning(
                    f"Dead-end chain: L1 '{h_id}' ({h.get('title','')}) "
                    f"has no L2 downstream. Industry: {industry_name}. "
                    f"Its signal will be wasted in prosperity rating."
                )

        # 检查 L2 → L3
        for h in l2_items:
            h_id = h.get("id", "")
            if h_id not in children_map:
                logger.warning(
                    f"Dead-end chain: L2 '{h_id}' ({h.get('title','')}) "
                    f"has no L3 downstream. Industry: {industry_name}."
                )
```

---

## 5. Layer 4: SIGNAL_MAP 补全

### 5.1 修改 `report_agent.py`（第 44-52 行）

**修改前**：
```python
SIGNAL_MAP = {
    ("positive", "confirmed"): 1.0,
    ("positive", "disputed"): -0.5,
    ("negative", "confirmed"): -1.0,
    ("negative", "disputed"): 0.5,
    ("neutral", "confirmed"): 0.3,
}
DEFAULT_SIGNAL = 0.0
```

**修改后**（10 种组合全覆盖）：
```python
SIGNAL_MAP = {
    # (sentiment, status) → signal_value
    ("positive", "confirmed"): 1.0,
    ("positive", "partial"): 0.6,       # 新增：部分验证的正向信号
    ("positive", "disputed"): -0.5,
    ("positive", "unverified"): 0.3,     # 新增：待验证的正向信号（折扣）
    ("negative", "confirmed"): -1.0,
    ("negative", "partial"): -0.5,      # 新增：部分验证的负向信号
    ("negative", "disputed"): 0.5,
    ("negative", "unverified"): -0.3,    # 新增：待验证的负向信号（折扣）
    ("neutral", "confirmed"): 0.3,
    ("neutral", "partial"): 0.1,        # 中性+部分 → 微弱信号
    ("neutral", "disputed"): -0.2,
    ("neutral", "unverified"): 0.0,
}
```

### 5.2 移除双重折扣（第 116-118 行）

**删除**：
```python
            # unverified/partial → 0.5×
            if status in ("unverified", "partial"):
                signal *= 0.5
```

原因：折扣已内嵌到 SIGNAL_MAP 中（如 `(positive, partial): 0.6` 相比 `(positive, confirmed): 1.0` 已是 60% 折扣，再乘 0.5 会变成 30%，过重）。

---

## 6. 受影响的文件汇总

| 文件 | 操作 | 估计行数 | 风险等级 |
|------|------|---------|---------|
| **Layer 1**: `agents/verify_agent.py` | 修改（保留字段 +3） | ~3 | **极低** |
| **Layer 2**: `agents/counter_agent.py` | 修改（prompt 去极性 + 硬编码去极性） | ~20 | 低 |
| `coordinator.py` | 修改 | ~40 | 低（插入新步骤，下游不变） |
| `hypothesize_prompt.md` | 修改（+1 规则） | ~5 | 极低（prompt 补充） |
| `hypothesize_agent.py` | 修改（+验证方法） | ~25 | 极低（只打日志） |
| `report_agent.py` | 修改（SIGNAL_MAP + 删折扣） | ~10 | 中（改变信号值） |
| `verify_agent.py` | 修改（跳过安全网条件） | ~5 | 低 |
| **合计** | | **~108 行** | |

### 不受影响

- `search_agent.py`, `learning_agent.py`, `screening_agent.py`, `track_agent.py`
- `tools/*`（`purity_scorer.py`, `stock_screener.py`, `industry_metrics.py` 等）
- 前端、API、数据库模型
- 龟龟策略

---

## 7. 实施步骤

### 步骤 1: 验证环境准备

```bash
cd backend
pytest tests/ -q --tb=short   # 确认当前全部通过
```

### 步骤 2: Layer 1 — VerifyAgent sentiment 保留修复（P0，最低风险）

1. 修改 `verify_agent.py` L447-449：保留字段列表加 `"sentiment"`, `"causality_strength"`, `"causality_note"`
2. `pytest tests/` → 确认通过（sentiment 在 mock 数据中已存在，只不再丢失）

### 步骤 3: Layer 2 — CounterAgent 去极化

1. 修改 `counter_agent.py` `_build_cascade_prompt()`：去掉极性规则，改为三遍扫描
2. 修改 `_hardcoded_polarity_cascade()` → `_hardcoded_cascade()`：去掉 polarity 判断
3. `pytest tests/` → 确认通过

### 步骤 4: Layer 4 — SIGNAL_MAP 补全（最低风险先做）

1. 修改 `report_agent.py`：SIGNAL_MAP 从 5 项扩展到 10 项
2. 删除第 116-118 行双重折扣
3. 更新测试预期值（如有）
4. `pytest tests/` → 确认通过

### 步骤 5: Layer 3 — 链结构完整性约束

1. 修改 `hypothesize_prompt.md`：新增规则 8
2. 修改 `hypothesize_agent.py`：新增 `_validate_chain_completeness()`
3. 在 `_parse_hypotheses()` 返回前调用
4. `pytest tests/` → 确认通过

### 步骤 6: 验证 — 人工智能行业重跑

```bash
cd backend
python -m app.strategies.prosperity.coordinator --industry 人工智能 --force
```

验证点：
- [ ] CounterAgent 日志：三遍扫描（非极性），disputed → overturned → cascade
- [ ] sentiment 正确传递到 ReportAgent（不再是全部 neutral）
- [ ] 评级从「弱景气」→「景气」（因为 sentiment 从 neutral 恢复为 positive）
- [ ] H0-2 仍被 overturned（硬数据证伪 400%），下游级联 unreachable
- [ ] SIGNAL_MAP 新组合产生非零信号值

### 步骤 7: 版本号 + 文档闭环

1. `config.py` / `pyproject.toml` 版本号 → v0.11.0
2. 更新 `CHANGELOG.md`（v0.11.0 条目）
3. 追加 `.codebuddy/memory/2026-07-03.md`
4. `git commit`

---

## 8. 测试计划

### 8.1 需要新增的测试

| 编号 | 测试文件 | 测试用例 | 预期 |
|------|---------|---------|------|
| T1 | `test_counter_agent.py` | `test_disputed_always_overturned_regardless_of_sentiment` | positive/negative/neutral 的 disputed 全部 → overturned |
| T2 | `test_counter_agent.py` | `test_overturned_cascades_to_downstream` | 下级联传递正确 |
| T3 | `test_counter_agent.py` | `test_sentiment_override_from_corrected_statement` | sentiment 被修正 + original_sentiment 保留 |
| T4 | `test_counter_agent.py` | `test_hardcoded_fallback_when_llm_fails` | 硬编码三遍扫描生效，不抛异常 |
| T5 | `test_counter_agent.py` | `test_partial_downgrades_confidence` | confidence 降低，status 不变 |
| T6 | `test_hypothesize_agent.py` | `test_dead_end_chain_warning` | L1 无 L2 时产生 warning 日志 |
| T7 | `test_report_agent.py` | `test_signal_map_coverage` | 新组合 (positive, partial) 返回 0.6 而非 0.0 |
| T8 | `test_report_agent.py` | `test_no_double_penalty_for_partial` | partial 信号不再被 0.5× |
| T9 | `test_verify_agent.py` | `test_sentiment_retained_after_merge` | sentiment/causality 字段在合并后不丢失 |
| T10 | `test_prosperity_coordinator.py` | `test_counter_agent_integration` | Pipeline 在 counter 步骤正常流转 |

### 8.2 需更新的现有测试

| 文件 | 原因 |
|------|------|
| `test_report_agent.py` | SIGNAL_MAP 信号值变化 → 评级阈值边界测试需重新校准 |
| `test_prosperity_coordinator.py` | PIPELINE_STEPS 新增 "counter" → 步骤数断言更新 |

---

## 9. 回滚方案

如果 CounterAgent 引入不稳定：

1. **一键绕过**：在 `config.py` 增加 `PROSPERITY_COUNTER_ENABLED = True`，设置为 `False` 时跳过 Phase 3.5，回退到 `_cascade_safety_net` 行为
2. **LLM 降级**：CounterAgent LLM 调用失败 → 自动降级到硬编码三遍扫描 → 若也失败 → 原 `_cascade_safety_net` 仍在
3. **Layer 1 (sentiment) 不回滚**：独立于 CounterAgent，影响范围仅 verify_agent.py 3 行代码

---

## 10. 状态机规范（v1.1 去极性化后终态）

### 10.1 状态定义

| Status | 设置者 | 含义 | 下游处理 |
|--------|--------|------|---------|
| **pending** | HypothesizeAgent | 未验证初始态 | → VerifyAgent |
| **confirmed** | VerifyAgent (LLM) | 多数据源交叉验证通过 | → CounterAgent（可能 sentiment 修正）→ ReportAgent 参与评级 |
| **partial** | VerifyAgent (LLM) | 部分支撑，数据不充分 | → CounterAgent（降级置信度）→ ReportAgent 参与评级（打折） |
| **disputed** | VerifyAgent (LLM) | 发现反驳证据 | → CounterAgent：不论 polarity 一律 → overturned |
| **unverified** | VerifyAgent (LLM) | 无法判断 | → CounterAgent 不操作 → TrackAgent → ReportAgent（打折） |
| **overturned** | CounterAgent | 经三遍扫描确认推翻（不区分极性） | → ReportAgent 排除 → **唯一触发下游级联的状态** |
| **unreachable** | CounterAgent 级联 | 上游 overturned → 下游不可达 | → ReportAgent 排除 → TrackAgent 排除 |

### 10.2 状态流转图

```
pending ──→ confirmed ──→ (CounterAgent: 可能修正 sentiment)
         ├─→ partial   ──→ (CounterAgent: 降级置信度)
         ├─→ disputed  ──→ (CounterAgent: 不论极性 → overturned)
         └─→ unverified ──→ (CounterAgent: 不操作)

overturned ──→ 下游 unreachable（唯一级联路径，不区分极性）
unreachable ──→ 排除评级 + 排除跟踪

TrackAgent 可跟踪: {confirmed, partial, disputed, unverified}
TrackAgent 排除:   {pending, overturned, unreachable}

ReportAgent 参与:  {confirmed, partial, unverified}
ReportAgent 排除:  {overturned, unreachable, disputed}
```

### 10.3 Watchlist 跟踪规则

| Status | 进入 Watchlist? | 原因 |
|--------|----------------|------|
| confirmed ✅ | 是 | 证实 → 跟踪确认趋势延续 |
| partial ✅ | 是 | 部分证实 → 跟踪补全数据 |
| disputed ❌ | 否 | 已被推翻（disputed→overturned），不留痕 |
| unverified ✅ | 是 | 无法判断 → 跟踪获取数据 |
| pending ❌ | 否 | 未验证 |
| overturned ❌ | 否 | 已推翻 |
| unreachable ❌ | 否 | 链已断裂 |

---

## 11. 附录：关键设计决策

1. **CounterAgent 必须读五维语义**：仅用 `status+polarity` = 重复硬编码错误。LLM 需要看到的完整 context 包括 reason/corrected_statement/causality_strength 才能做出语义级联判断。

2. **Sentiment 修正用方案 B 而非方案 A**：方案 A（打折）= 上下游都要感知修正逻辑。方案 B（直接修正 sentiment）= 下游 SIGNAL_MAP 自动消费，零感知。更优雅。

3. **三级降级保底**：LLM → 硬编码三遍扫描 → 原安全网。确保任何一层失败不影响 Pipeline 运行。

4. **不删 verify_agent._cascade_safety_net**：保留作为最终安全网。But 需要确保它不会覆盖 CounterAgent 的判决。

5. **Layer 3 (Hypothesize) 只警告不阻断**：链结构完整性的约束是 prompt 层的（soft constraint），不是代码层的（hard constraint）。

6. **去极性化（v1.1 新增）**：sentiment 不影响逻辑完整性。被证伪的前提 → 下游不可达，不论"方向对我是否有利"。真正的正向信号应从正向假设的 confirmed 捕获，而非负向假设被推翻后的间接利好。七层架构中 HypothesizeAgent 极少产出 negative 假设，极性规则几乎无实战受益者。

7. **VerifyAgent sentiment 保留（v1.1 新增）**：sentiment 是假设的固有方向属性，HypothesizeAgent 生成时已确定。LLM 验证 prompt 不要求返回 sentiment，但代码合并时**必须保留原始值**——否则 ReportAgent 全部按 neutral 计算，信号被系统性压低（AI 行业证据：0.65→2.86）。

8. **与 Spec 的关系**：本计划是对 Spec §2.3、§2.4 的修正 + 增强。v1.1 将 CounterAgent 从极性感知改回纯机械三遍扫描，与 Spec §2.4 原始定义一致。
