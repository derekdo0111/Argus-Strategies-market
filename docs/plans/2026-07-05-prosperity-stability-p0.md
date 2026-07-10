# 高景气策略 P0 稳定性增强 — 实施计划

> 版本: v1.0 | 日期: 2026-07-05 | 状态: **已实施**
>
> 来源: 收敛性实验 → Brainstorming → Spec → 本计划
>
> 关联 Spec: `docs/specs/2026-07-05-prosperity-stability-p0.md`
>
> 目标版本: v0.20.0

---

## 0. 实施概要

| 维度 | 说明 |
|------|------|
| **目标** | 消除 VerifyAgent LLM 输出的单轮随机性（42 差异 → 预估 ≤15） |
| **方案** | 3 轮并行 LLM 调用 → 字段级聚合（Self-Consistency） |
| **范围** | **仅 VerifyAgent**（Plan A） |
| **改动文件** | 3 个核心文件 + 4 个文档文件 |
| **LLM 调用** | 1× → 3×（并行，耗时≈1×） |
| **下游影响** | **零** — status/sentiment 值域不变，接口不变 |
| **回滚难度** | 低 — 全在 verify_agent.py 内部，不改接口 |

---

## 1. 实施步骤（6 步）

### 步骤 1: 修改 verify_prompt.md（prompt 模板）

**文件**: `backend/rules/prosperity/prompts/verify_prompt.md`

**变更内容**:

#### 1a: Q1 格式变更

修改前（L25-30）:
```
### Q1: source_count — 信源数量

搜索素材中，有几个**独立信源**明确提供了支持该陈述的**具体数据或直接陈述**？
- 只计数直接陈述该事实的信源（如「日均Token调用突破30万亿」），不计算间接推理或泛泛而谈
- 同一机构的多篇文章算同一信源
- 回答一个整数: 3 / 2 / 1 / 0
```

修改后:
```
### Q1: supporting_source_indices — 信源编号

搜索素材中，哪些信源**编号**明确提供了支持该陈述的**具体数据或直接陈述**？
- 输出一个整数数组，如 [1, 3, 5]
- 只包含直接陈述该事实的信源编号（不计算间接推理或泛泛而谈）
- 同一机构的多篇文章算同一信源（只写第一个编号）
- 无信源 → 输出 []
```

#### 1b: Q3 格式变更

修改前（L40-45）:
```
### Q3: counter_conflict — 反例直接冲突

反例搜索证据中，是否有**直接推翻**该陈述的证据？
- 必须是直接推翻（如「Token调用量实际在下降」推翻「Token量在增长」）
- 间接怀疑不算（如「AI创业公司烧钱」不推翻「Token量在增长」）
- 回答: "yes" 或 "no"
```

修改后:
```
### Q3: counter_conflict_score — 反例冲突程度

反例搜索证据中，对该陈述的挑战程度：
- 3: 直接推翻（如「Token量实际在下降」推翻「Token量在增长」）
- 2: 明显矛盾（核心假设被质疑，但不完全推翻）
- 1: 间接怀疑（如「AI创业公司烧钱」→ 不直接推翻Token增长）
- 0: 无冲突
```

#### 1c: 新增 sentiment 字段

在「额外字段」（L47-53）新增:
```
### sentiment — 假设的情感方向（新增）

根据验证结果和所有证据，判断该假设的整体方向：
- "positive": 描述的是利好/增长/机会方向
- "negative": 描述的是利空/衰退/风险方向
- "neutral": 描述的是结构性/中性状态
```

#### 1d: 更新输出格式示例

JSON 示例中：
```
      "source_count": 2,              → 删除，替换为
      "supporting_source_indices": [1, 3],
      "counter_conflict": "no",       → "counter_conflict_score": 0,
      "data_alignment": "支持",       → 不变
```

---

### 步骤 2: 修改 verify_agent.py（核心逻辑）

**文件**: `backend/app/strategies/prosperity/agents/verify_agent.py`

#### 2a: 提取独立的 LLM 调用方法

当前 `_verify_chain_with_llm` 中 LLM 调用内嵌在方法体内（~50 行）。提取为 `_call_verify_llm(prompt)` 方法，返回原始 LLM 响应文本。

```python
def _call_verify_llm(self, prompt: str) -> Optional[str]:
    """单次 LLM 验证调用，含超时重试。返回响应文本或 None。"""
    api_key = getattr(settings, "LLM_API_KEY", "")
    if not api_key:
        return None
    
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{settings.LLM_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "你是一位行业研究验证分析师。只输出要求的 JSON 格式，不要其他内容。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=180,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            logger.warning(f"Verify LLM timeout (attempt {attempt+1}/2)")
        except Exception as e:
            logger.error(f"Verify LLM error (attempt {attempt+1}/2): {e}")
    return None
```

#### 2b: 新增 `_aggregate_rounds` 方法

```python
def _aggregate_rounds(self, rounds_raw: list[str], chain: list[dict]) -> dict:
    """对 3 轮 LLM 输出做字段级聚合，合成最终验证结果。
    
    Args:
        rounds_raw: 每轮的 LLM 原始响应文本
        chain: 原始假设链（用于字段保留和兜底）
    
    Returns:
        聚合后的验证结果，格式与当前 _parse_verification_result 返回一致
    """
    # Step 1: 逐轮解析
    parsed_rounds = []
    for raw in rounds_raw:
        if raw:
            parsed = self._parse_verification_raw(raw, chain)
            if parsed:
                parsed_rounds.append(parsed)
    
    # Step 2: 对每条假设做字段级聚合
    by_id = {h.get("id"): h for h in chain}
    aggregated_hyps = []
    
    for orig_h in chain:
        h_id = orig_h.get("id", "")
        
        # 收集各轮中该假设的输出
        rounds_for_h = []
        for pr in parsed_rounds:
            for vh in pr.get("hypotheses", []):
                if vh.get("id") == h_id:
                    rounds_for_h.append(vh)
        
        if not rounds_for_h:
            # 兜底：所有轮都失败
            aggregated_hyps.append({**orig_h, "status": "unverified", "reason": "LLM 多轮调用全部失败"})
            continue
        
        # Q1: 交集 → source_count
        all_indices = []
        for vh in rounds_for_h:
            indices = vh.get("supporting_source_indices", [])
            if isinstance(indices, list):
                all_indices.append(set(indices))
        if all_indices:
            common = all_indices[0]
            for s in all_indices[1:]:
                common = common & s
            source_count = len(common)
        else:
            source_count = 0
        
        # Q2: 众数 → data_alignment
        from collections import Counter
        da_values = [vh.get("data_alignment", "无相关数据") for vh in rounds_for_h]
        data_alignment = Counter(da_values).most_common(1)[0][0]
        
        # Q3: MAX → counter_conflict
        cc_values = [
            int(vh.get("counter_conflict_score", vh.get("counter_conflict", 0) == "yes" and 3 or 0))
            for vh in rounds_for_h
        ]
        cc_score = max(cc_values) if cc_values else 0
        counter_conflict = "yes" if cc_score >= 2 else "no"
        
        # sentiment: 众数
        sent_values = [vh.get("sentiment", "neutral") for vh in rounds_for_h]
        sentiment = Counter(sent_values).most_common(1)[0][0]
        
        # 其他字段取第一轮
        base = dict(rounds_for_h[0])
        
        # 确定性合成 status + confidence
        base["source_count"] = source_count
        base["data_alignment"] = data_alignment
        base["counter_conflict"] = counter_conflict
        base["status"] = _synthesize_status(source_count, data_alignment, counter_conflict)
        base["confidence"] = _synthesize_confidence(source_count, data_alignment, counter_conflict)
        base["verified_sentiment"] = sentiment
        
        # 保留原始字段
        if h_id in by_id:
            orig = by_id[h_id]
            for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
                        "sources", "time_horizon", "key_indicators", "investment_implication",
                        "wiki_path", "verification_needed", "tier",
                        "sentiment", "causality_strength", "causality_note"):
                if key in orig and key not in base:
                    base[key] = orig[key]
        
        aggregated_hyps.append(base)
    
    # 聚合链级字段
    chain_label = rounds_for_h[0].get("chain_label", "") if rounds_for_h else ""
    return {
        "chain_label": chain_label,
        "hypotheses": aggregated_hyps,
    }
```

#### 2c: 新增 `_parse_verification_raw` 方法

将当前 `_parse_verification_result` 中 JSON 解析部分提取出来（不含确定性合成和字段合并）：

```python
def _parse_verification_raw(self, llm_output: str, chain: list[dict]) -> Optional[dict]:
    """解析 LLM 原始响应为 JSON（不含后处理）。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
    json_str = match.group(1) if match else llm_output
    
    try:
        result = json.loads(json_str)
        return result
    except json.JSONDecodeError:
        arr_match = re.search(r"\{[\s\S]*\}", json_str)
        if arr_match:
            try:
                return json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                pass
        return None
```

#### 2d: 修改 `_verify_chain_with_llm`

将单次 LLM 调用改为 3 轮并行：

```python
def _verify_chain_with_llm(self, ...) -> dict:
    """调用 LLM 验证一条推理链（3 轮并行 + 字段级聚合）。"""
    api_key = getattr(settings, "LLM_API_KEY", "")
    if not api_key:
        return {"hypotheses": [{**h, "status": "unverified", ...} for h in chain]}
    
    # 构建 prompt（不变）
    tushare_text = self._format_tushare_data(industry_data)
    counter_text = self._format_counter_evidence(counter_evidence)
    chain_text = ...
    
    prompt = self.verify_template.format(
        industry_name=industry_name,
        chain_label=chain_label,
        previous_summary=previous_summary if previous_summary else "（首条链路，无前序摘要）",
        history_text=history_text if history_text else "（无历史记录，首次研究）",
        tushare_text=tushare_text,
        search_materials=search_materials[:3000],
        counter_text=counter_text,
        chain_text=chain_text,
    )
    
    # 3 轮并行调用
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(self._call_verify_llm, prompt) for _ in range(3)]
        raw_outputs = [f.result() for f in as_completed(futures)]
    
    # 字段级聚合
    result = self._aggregate_rounds(raw_outputs, chain)
    if result and result.get("hypotheses"):
        return result
    
    # 兜底：全部失败
    return {"hypotheses": [{**h, "status": "unverified", "reason": "LLM 3轮调用全部失败",
                              "causality_strength": "moderate", "causality_note": ""}
                             for h in chain]}
```

#### 2e: 修改 `_parse_verification_result`（保留向后兼容）

```python
def _parse_verification_result(self, llm_output: str, original_chain: list[dict]) -> dict:
    """解析 LLM 验证输出，确定性合成 status + confidence（兼容旧格式）。"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
    json_str = match.group(1) if match else llm_output

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        arr_match = re.search(r"\{[\s\S]*\}", json_str)
        if arr_match:
            try:
                result = json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                return {"hypotheses": [{**h, "status": "unverified", "reason": "JSON 解析失败"} for h in original_chain]}
        else:
            return {"hypotheses": [{**h, "status": "unverified", "reason": "JSON 解析失败"} for h in original_chain]}

    verified_hyps = result.get("hypotheses", [])
    by_id = {h.get("id"): h for h in original_chain}
    for vh in verified_hyps:
        h_id = vh.get("id", "")
        if h_id in by_id:
            orig = by_id[h_id]
            for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
                        "sources", "time_horizon", "key_indicators", "investment_implication",
                        "wiki_path", "verification_needed", "tier",
                        "sentiment", "causality_strength", "causality_note"):
                if key in orig and key not in vh:
                    vh[key] = orig[key]

        # v0.20: 兼容新旧两种输入格式
        # 新格式: supporting_source_indices + counter_conflict_score
        # 旧格式: source_count + counter_conflict
        if "supporting_source_indices" in vh:
            indices = vh.get("supporting_source_indices", [])
            sc = len(indices) if isinstance(indices, list) else 0
        else:
            sc = vh.get("source_count", 0)
        
        if "counter_conflict_score" in vh:
            cc = "yes" if int(vh.get("counter_conflict_score", 0)) >= 2 else "no"
        else:
            cc = vh.get("counter_conflict", "no")
        
        da = vh.get("data_alignment", "无相关数据")

        vh["status"] = _synthesize_status(sc, da, cc)
        vh["confidence"] = _synthesize_confidence(sc, da, cc)

    return result
```

---

### 步骤 3: 修改测试文件

**文件**: `backend/tests/test_prosperity_coordinator.py`

#### 3a: 更新确定性合成测试

`TestV019DeterministicVerification` 中测试覆盖 `_synthesize_status` 和 `_synthesize_confidence`。这两个函数**规则不变**，测试不需要修改。

#### 3b: 新增多轮投票测试

新增 `TestV020MultiRoundVerify` 测试类：

| 编号 | 测试用例 | 预期 |
|------|---------|------|
| T1 | `test_q1_intersection_empty_when_no_consensus` | 3 轮 indices [1,2]/[3,4]/[5,6] → 交集空 → source_count=0 → unverified |
| T2 | `test_q1_intersection_keeps_consensus` | 3 轮 indices [1,2,3]/[1,3,5]/[1,3] → 交集 [1,3] → source_count=2 → confirmed |
| T3 | `test_q1_filters_hallucination` | 2 轮 [1,2] + 1 轮 [1,2,3,4,5,6] → 交集 [1,2] → 幻觉编号 3-6 被过滤 |
| T4 | `test_q2_mode_filters_noise` | 3 轮 "支持"/"无相关数据"/"支持" → 众数 "支持" |
| T5 | `test_q3_max_triggers_at_2` | 3 轮 score 0/2/1 → MAX=2 → counter_conflict=yes → disputed |
| T6 | `test_q3_max_no_trigger_at_1` | 3 轮 score 1/0/1 → MAX=1 → counter_conflict=no → partial（source_count=0 时 unverified） |
| T7 | `test_q3_max_triggers_at_3` | 3 轮 score 3/0/1 → MAX=3 → counter_conflict=yes |
| T8 | `test_sentiment_mode` | 3 轮 positive/neutral/positive → 众数 positive |
| T9 | `test_sentiment_3way_tiebreak` | 3 轮 positive/negative/neutral → 任意取第一个（不崩溃） |
| T10 | `test_aggregate_returns_unverified_on_all_failure` | 3 轮全部失败 → status=unverified |
| T11 | `test_2rounds_consensus_treats_as_3round` | 2 轮 indices [1,2]/[1,2] → source_count=2（实际 3 轮中可能有一轮失败，逻辑不变） |

---

### 步骤 4: 版本号 + 文档闭环

#### 4a: `backend/app/core/config.py`
```python
APP_VERSION = "0.20.0"
```

#### 4b: `backend/pyproject.toml`
```toml
version = "0.12.0"
```

#### 4c: 更新 `docs/specs/2026-06-29-prosperity-strategy-design.md`
- 版本号: v0.12.3 → v0.12.4
- §2.3 VerifyAgent: 新增备注「v0.20 增强：3 轮并行 LLM + 字段级投票聚合」

---

### 步骤 5: 验证

```bash
cd backend

# 1. 跑测试
pytest tests/ -v --tb=short

# 2. 重跑「人工智能」验证稳定性
python scripts/run_prosperity_ne.py --industry 人工智能 --force 2>&1 | Out-File -FilePath verify_3rounds_run1.txt -Encoding utf8
python scripts/run_prosperity_ne.py --industry 人工智能 --force 2>&1 | Out-File -FilePath verify_3rounds_run2.txt -Encoding utf8

# 3. 对比差异
python scripts/compare_runs.py verify_3rounds_run1.txt verify_3rounds_run2.txt

# 4. 确认 pytest 全部通过
pytest tests/ -q
```

**验证点**：
- [ ] 3 轮并行调用不增加总耗时（±10% 以内）
- [ ] confirmed/partial/disputed/unverified 数量在两轮之间几乎一致（差异 ≤2 条）
- [ ] 股池数量在两轮之间一致（差异 ≤3 只）
- [ ] signal_strength 在两轮之间偏差 ≤10%
- [ ] 零回归（pytest 全部通过）

---

### 步骤 6: CHANGELOG

更新 `CHANGELOG.md` 添加 v0.20.0 条目。

---

## 2. 受影响的文件汇总

| 文件 | 操作 | 估计行数 | 风险 |
|------|------|---------|------|
| `rules/prosperity/prompts/verify_prompt.md` | 修改（Q1/Q3 格式 + sentiment 新增） | ~30 | **中** |
| `agents/verify_agent.py` | 修改（3 轮并行 + 聚合 + 格式兼容） | ~120 | **中高** |
| `tests/test_prosperity_coordinator.py` | 新增测试类 | ~80 | 低 |
| `docs/specs/2026-07-05-prosperity-stability-p0.md` | **新建** | — | — |
| `docs/plans/2026-07-05-prosperity-stability-p0.md` | **新建（本文件）** | — | — |
| `docs/specs/2026-06-29-prosperity-strategy-design.md` | 修改（版本号 + §2.3 备注） | ~5 | 极低 |
| `CHANGELOG.md` | 新增条目 | ~20 | 极低 |
| `backend/app/core/config.py` | 版本号 | 1 | 极低 |
| `backend/pyproject.toml` | 版本号 | 1 | 极低 |

### 不受影响

- `counter_agent.py` — Plan A 不动
- `coordinator.py` — 调用接口不变
- `report_agent.py` — 消费格式不变
- `hypothesize_agent.py` / `search_agent.py` / `learning_agent.py` / `track_agent.py`
- `screening_agent.py`
- `tools/*`
- 前端
- 龟龟策略

---

## 3. 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 3 轮并行超时 | 低 | 中（某条链全部失败 → unverified） | 单轮 timeout=180s，并行 3 轮 ≤180s |
| DeepSeek API 限流 | 低 | 中（3 倍调用量触发限流） | 当前 12 链 × 3 轮 = 36 次/次运行，远低于限流 |
| 聚合逻辑 bug | 低 | 高（status 系统性错误） | 新增 11 个测试覆盖所有聚合路径 |
| 旧格式 backward compat | 中 | 低（_parse_verification_result 兼容新旧） | 旧格式仍可用 source_count + counter_conflict |
| prompt 格式变更导致 LLM 不适应 | 中 | 高（全部 unverified） | 新 prompt 只改了输出字段名，语义不变 |
| CounterAgent 输入质量下降 | 极低 | 中（多轮投票理应更稳定，不会更差） | N/A |

---

## 4. 回滚方案

如果多轮投票引入新问题：

1. **配置开关**：在 `config.py` 加 `PROSPERITY_VERIFY_ROUNDS = 3`，设为 1 即回退
2. **代码兼容**：`_parse_verification_result` 保留对旧格式的兼容
3. **prompt 兼容**：LLM 如果对 `supporting_source_indices` 不适应，可从 `source_count` 兜底

---

## 5. 设计决策附录

1. **Q3 用 MAX 不用 median**：反例冲突是安检逻辑，一条强反例就值得触发
2. **Q1 用交集不用 union**：LLM 易多数不会漏数，交集过滤幻觉
3. **sentiment 新增 verified_sentiment**：不覆盖原始 sentiment
4. **其他字段取第一轮**：reason/corrected/causality 不影响 status 合成
5. **Plan A 不改 CounterAgent**：保持改动范围最小
6. **3 轮并行用 ThreadPoolExecutor**：简化实现，asyncio 在同步 requests 下无优势

---

## 6. 下一步（P1，本次不实施）

- CounterAgent 多轮投票（如需）
- HypothesizeAgent sentiment 稳定性（当前 8/12 链不一致）
- 搜索结果稳定性（Tavily API 非确定性，需要缓存层）
