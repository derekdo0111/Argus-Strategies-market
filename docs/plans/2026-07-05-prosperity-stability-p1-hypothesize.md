# 高景气策略 P1 稳定性增强 — HypothesizeAgent 实施计划

> 版本: v1.0 | 日期: 2026-07-05 | 状态: **设计中**
>
> 来源: Brainstorming → 收敛性实验分析 → Spec → 本计划
>
> 关联 Spec: `docs/specs/2026-07-05-prosperity-stability-p1-hypothesize.md`
>
> 目标版本: v0.21.0

---

## 0. 实施概要

| 维度 | 说明 |
|------|------|
| **目标** | 消除 HypothesizeAgent 假设数量不稳定（12≠14）和链条凭空出现/消失 |
| **方案** | 两阶段分离：Phase 1 3 轮投票定骨架 → Phase 2 1 轮强约束填充 |
| **范围** | **仅 HypothesizeAgent**（不改调用接口） |
| **改动文件** | 4 个核心文件 + 4 个文档文件 |
| **LLM 调用** | 1× → 4×（Phase 1 并行 3 + Phase 2 串行 1），耗时 45-55s（+50%） |
| **下游影响** | **零** — `form_hypotheses()` 返回格式不变，字段值域不变 |
| **回滚难度** | 低 — 全在 hypothesize_agent.py 内部，配置开关可降级为单轮 |
| **依赖** | 无外部依赖。无协调器改动 |

---

## 1. 实施步骤（7 步）

### 步骤 1: 新建 Phase 1 prompt 模板

**文件**: `backend/rules/prosperity/prompts/hypothesize_phase1_prompt.md`（新建）

**内容概要**：极简 prompt，只要求 4 字段输出。详见 Spec §2.2.1。

**风险**: 低。Prompt 短（~40 行 vs 当前 118 行），输出结构简单。

**验收**: 单独用 LLM 测试，确认 3 轮输出 JSON 可解析、ID 命名规范。

---

### 步骤 2: 新建 Phase 2 prompt 模板

**文件**: `backend/rules/prosperity/prompts/hypothesize_phase2_prompt.md`（新建）

**内容概要**：带 `{skeleton_text}` 占位符，强调"不可增删改"。详见 Spec §2.3.1。

**风险**: 低。在 Phase 1 之后测试。

**验收**: 以一组骨架作为输入，确认 LLM 不增删改 id/title/derives_from。

---

### 步骤 3: 重构 hypothesize_agent.py

**文件**: `backend/app/strategies/prosperity/agents/hypothesize_agent.py`

**主要变更**：

#### 3a: `form_hypotheses()` — 入口分流

```python
def form_hypotheses(self, industry_name, session_id, search_result, history):
    rounds = getattr(settings, "PROSPERITY_HYPOTHESIZE_ROUNDS", 3)
    
    if rounds <= 1:
        # 降级模式：单轮
        return self._form_single_round(industry_name, session_id, search_result, history)
    
    # Phase 1: 骨架 (3 轮并行 + 投票)
    skeleton = self._phase1_skeleton(industry_name, search_result, history)
    
    # Phase 2: 填充 (1 轮强约束)
    hypotheses = self._phase2_fill(industry_name, skeleton, search_result, history)
    
    # 后续写入 wiki + DB 不变
    ...
```

#### 3b: 新增 `_phase1_skeleton()` — 3 轮并行 + 投票

```python
def _phase1_skeleton(self, industry_name, search_result, history):
    """Phase 1: 3 轮 LLM 并行 → ID+title 双重匹配投票 → 链完整性回填"""
    prompt_func = self._build_phase1_prompt
    timeout = getattr(settings, "PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT", 25)
    
    rounds = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(self._call_llm_phase1, prompt_func(...)) for _ in range(3)]
        for f in futures:
            try:
                result = f.result(timeout=timeout)
                rounds.append(result)
            except Exception:
                logger.warning("Phase 1 round timeout or error")
    
    if not rounds:
        return self._fallback_skeleton(industry_name, search_result, history)
    
    skeleton = self._aggregate_skeletons(rounds)  # ≥2/3 规则 + ID+title 双重匹配
    
    if not skeleton:
        skeleton = rounds[0]  # 降级兜底
    
    skeleton = self._fix_chain_completeness(skeleton, all_rounds=rounds)
    return skeleton
```

#### 3c: 新增 `_phase2_fill()` — 1 轮强约束 + 校验重试

```python
def _phase2_fill(self, industry_name, skeleton, search_result, history):
    """Phase 2: 1 轮 LLM 填充 + 骨架校验 + 最多 2 次重试"""
    for attempt in range(3):
        prompt = self._build_phase2_prompt(industry_name, skeleton, search_result, history)
        llm_output = self._call_llm(prompt)  # 复用现有 LLM 调用方法
        hypotheses = self._parse_hypotheses(llm_output, industry_name)
        if self._validate_fill_output(hypotheses, skeleton):
            return hypotheses
        logger.warning(f"Phase 2 skeleton validation failed, attempt {attempt + 1}/3")
    return []
```

#### 3d: 新增 `_aggregate_skeletons()` — 投票逻辑

详见 Spec §2.2.2。

#### 3e: 新增 `_fix_chain_completeness()` — 回填缺失下游

详见 Spec §2.2.3。

#### 3f: 新增 `_validate_fill_output()` — 骨架校验

详见 Spec §2.3.2。

**风险**: 中高。核心逻辑重写，需充分测试。

**验收**: 单元测试覆盖全部新增方法 + 集成测试用「人工智能」实验数据跑 3 轮。

---

### 步骤 4: 修改 config.py + .env

**文件**: `backend/app/core/config.py`

```python
# HypothesizeAgent 稳定性增强
PROSPERITY_HYPOTHESIZE_ROUNDS: int = 3         # Phase 1 轮数
PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT: int = 25  # Phase 1 单轮超时秒数
```

**文件**: `backend/.env` / `.env.example`

```bash
# HypothesizeAgent
PROSPERITY_HYPOTHESIZE_ROUNDS=3
PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT=25
```

**风险**: 极低。

**验收**: 设置 round=1 降级模式，确认走单轮路径。

---

### 步骤 5: 新增单元测试 + 集成测试

**文件**: `backend/tests/test_hypothesize_agent.py`（新建）

测试用例：

| 测试 | 类型 | 覆盖 |
|------|------|------|
| `test_aggregate_skeletons_normal` | 单元 | 3 轮各有 12 条 → 投票产出 12 条（全部 3/3） |
| `test_aggregate_skeletons_partial` | 单元 | 第 1 轮无 H2-4，后 2 轮有 → 2/3 → 保留 |
| `test_aggregate_skeletons_diverged` | 单元 | 3 轮完全不同 → 降级取第一轮 |
| `test_fix_chain_completeness` | 单元 | L2 保留但 L3 缺失 → 回填 |
| `test_validate_fill_output_pass` | 单元 | Phase 2 输出与骨架一致 → 通过 |
| `test_validate_fill_output_fail_id` | 单元 | Phase 2 多了假设 → 失败 |
| `test_phase1_phase2_integration` | 集成 | 用「人工智能」搜索缓存 → 跑完整两阶段 → 假设数稳定 |

**风险**: 低。

**验收**: `pytest tests/test_hypothesize_agent.py -v` 全绿。

---

### 步骤 6: 更新文档

| 文件 | 操作 | 说明 |
|------|------|------|
| `CHANGELOG.md` | 修改 | 追加 v0.21.0 条目 |
| `docs/specs/2026-06-29-prosperity-strategy-design.md` | 修改 | §2.2 增强备注 |
| `backend/pyproject.toml` | 修改 | 版本 0.12.0 → 0.13.0 |
| `.codebuddy/memory/2026-07-05.md` | 修改 | 追加日志 |

**风险**: 极低。

---

### 步骤 7: 收敛性验证

**脚本**: `scripts/stability_compare.py`（复用 v0.20 的验证脚本，扩展 HypothesizeAgent 指标）

**方法**：
1. 冻结全部输入（Tavily 缓存 14/14 + Tushare 数据一致 + history 一致）
2. 跑 3 次 `--force` pipeline
3. 对比：
   - 假设总数（目标：3 次 ≤1 条差异）
   - 假设 ID 集合（目标：3 次完全一致）
   - 下游输出差异（股池、评级）
4. 产出 `experiment_metrics.yaml` + `convergence_report.md`

**目标指标**：

| 指标 | v0.20 基准 | v0.21 目标 |
|------|-----------|-----------|
| 假设数量差异 | ±2 (12≠14) | **0** |
| 假设 ID 集合差异 | +2 条国产替代链 | **0** |
| 股池数量差异 | 0→23 (±∞) | **≤5** |
| 评级差异 | 高景气→景气 | **≤1 级** |

**风险**: 中。需完整跑一次 AI pipeline。

---

## 2. 时间线估计

| 步骤 | 估计耗时 | 备注 |
|------|:---:|------|
| 1+2: Prompt 模板 | 0.5h | 两个新模板，从现有模板剪裁 |
| 3: 重写 agent | 3h | 核心重构，新增 5 个方法 |
| 4: 配置 | 0.25h | 加 2 行配置 |
| 5: 测试 | 1.5h | 新单元测试 + 集成测试 |
| 6: 文档 | 0.5h | CHANGELOG + spec 备注 + 版本号 |
| 7: 收敛性验证 | 0.5h | 跑 3 次 pipeline + 对比 |
| **总计** | **~6h** | 风险缓冲 1h → 7h |

---

## 3. 回滚方案

| 场景 | 操作 |
|------|------|
| Phase 1 3 轮全部超时 | 配置 `PROSPERITY_HYPOTHESIZE_ROUNDS=1` 降级为单轮 |
| Phase 2 骨架校验全失败 | 代码自动返回空，不阻塞 pipeline |
| 收敛性不达标 | 回滚 hypothesize_agent.py 到 v0.20，保留新测试 |
| 生产环境性能不可接受 | 设置 `PROSPERITY_HYPOTHESIZE_ROUNDS=1` 降级 |

---

## 4. 后续工作

| 优先级 | 工作 | 前置条件 |
|:---:|------|------|
| P2 | CounterAgent 软衰减（防 overturned 过度） | 本 Spec 实施后，评估残余差异决定规模 |
| P3 | ScreeningAgent unreachable 防御 | P2 之后 |
| — | 收敛性实验 v0.21 | 本 Spec 实施完跑 |
