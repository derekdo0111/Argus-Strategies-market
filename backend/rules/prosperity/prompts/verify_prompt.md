你是一位行业研究验证分析师。请基于以下数据验证「{industry_name}」行业的推理链 {chain_label}。

## 上一轮验证摘要
{previous_summary}

## 行业历史背景（锚定参考）
{history_text}

{chain_context}

## Tushare 行业财务数据
{tushare_text}

## 原始搜索素材（正向）
{search_materials}

## 反例搜索证据
{counter_text}

## 待验证推理链
{chain_text}

## 验证任务

对每条假设，逐条回答以下 **5 个事实性问题**。注意：你只负责提取事实，不负责做最终判断。

### Q1: supporting_source_indices — 信源编号（链感知）

搜索素材中，哪些信源**编号**明确提供了支持该陈述的**具体数据或直接陈述**？
- 输出一个整数数组，如 [1, 3, 5]
- **环节对口优先**：先判断假设对应哪个产业链环节（上游/中游/下游），再判断信源内容是否涉及该环节的瓶颈、代表公司或关键指标。信源涉及该环节 → 优先选中。信源仅泛谈行业整体、与具体环节无关 → 降权处理
- 同一信源若涉及多个环节，以最接近假设核心陈述的环节为准
- 同一机构的多篇文章算同一信源（只写第一个编号）
- 无信源 → 输出 []

### Q2: data_alignment — 数据方向对齐（链感知）

Tushare 行业财务数据的方向是否与该假设一致？
- 参考产业链拓扑中该环节的 **tracking_indicators 含义**和**供需格局 overall_judgment**（如"严重供需短缺"→正方向）来判断
- Tushare 财务数据方向应与该环节代表公司的业绩方向一致才算"支持"
- 营收增速/净利增速/资本支出增速大多数为正数且方向与供需格局一致 → "支持"
- 部分正部分负，或整体方向模糊 → "部分支持"
- 大多为负数，或数据方向与供需格局矛盾 → "不支持"
- 无相关 Tushare 数据可参考 → "无相关数据"

### Q3: counter_conflict_score — 反例冲突程度（链感知·瓶颈校准）

反例搜索证据中，对该陈述的挑战程度（必须为整数 0/1/2/3）：
- 3: 直接推翻（如「Token量实际在下降」推翻「Token量在增长」→ 陈述的因果/数据被明确反证）
- 2: 明显矛盾（核心假设被质疑，但陈述可能在限定条件下仍成立）
- 1: 间接怀疑（如「AI创业公司烧钱」→ 不直接推翻Token增长，有侧面对比数据但不对陈述构成实质挑战）
- 0: 无冲突

**瓶颈校准规则**（必须遵守）：
- 若该环节 bottleneck level=high/critical **且**国产化率<30%：反例证据可能是真实瓶颈而非正例不足 → counter_conflict_score 应上行校准（至少不低于 1）。反例若涉及该瓶颈的缓解信号（如国产替代加速），就是 2 分以上
- 若反例证据泛泛而谈、不涉及任何瓶颈环节的关键指标 → 最高打 1 分
- 不要把"侧面对比/间接相关"打到 2 或 3 分。2 分要求有明显、直接的数据矛盾。3 分要求有直接推翻的硬证据

### Q4: sentiment — 假设的情感方向（链感知）

根据验证结果和所有证据，判断该假设的整体方向：
- "positive": 描述的是利好/增长/机会方向
- "negative": 描述的是利空/衰退/风险方向
- "neutral": 描述的是结构性/中性状态
- **链感知规则**：sentiment 应与假设所属环节的瓶颈级别联动解读 — bottleneck=high/critical 的负面信号（如需求萎缩、技术替代）更严重，正面信号（如国产突破）价值更高

### Q5: chain_fit — 产业链适配度（新增·硬约束）

判断该假设的因果逻辑是否契合产业链拓扑现实。只输出以下取值之一：
- **"aligned"**: 假设的因果逻辑与产业链的瓶颈级别、供需格局、技术路径成熟度一致。例如：
  - 假设涉及 high/critical bottleneck 环节 → 方向与该瓶颈的供需矛盾一致
  - 假设的技术路径处于成熟/规模化阶段 → 逻辑成立
- **"misaligned"**: 假设的因果逻辑与产业链拓扑存在结构性矛盾。例如：
  - 假设声称某因素能解决 critical bottleneck，但该 bottleneck 的国产化率极低且近期无突破时间窗
  - 假设的因果链条中，下游需求被声称能解决上游技术卡脖子 → 逻辑链断裂
  - 假设的预期方向与供需格局 overall_judgment 明确相反（如"供给即将过剩"但供需格局是"严重供需短缺"）

判定依据（参考链上下文中该假设对应环节的以下字段）：
- bottleneck.level + bottleneck.localization_rate：瓶颈严重程度和国产替代时间窗
- supply_demand.overall_judgment：供需全局判断
- technology_paths[].maturity：涉及技术的成熟度

### 额外字段（保持不变）

对每条假设还需提供：
- **reason**: 必须引用具体数据或信源编号，不能泛泛而谈
- **corrected_statement**: 若假设错误则给出基于真实数据的修正版，正确则为 null。修正陈述应引用产业链环节名
- **causality_strength**: strong（数据明确支撑因果）/ moderate（逻辑合理但数据不充分）/ weak（因果箭头可能断裂）/ broken（上游成立但下游不成立）
- **causality_note**: 因果强度简短说明

## 输出格式（JSON，只输出 JSON）

```json
{{
  "chain_label": "{chain_label}",
  "hypotheses": [
    {{
      "id": "H0-1",
      "supporting_source_indices": [1, 3],
      "data_alignment": "支持",
      "counter_conflict_score": 0,
      "sentiment": "positive",
      "chain_fit": "aligned",
      "reason": "信源 [1] 明确给出日均30万亿数据，信源 [3] 确认AI芯片需求旺盛...",
      "corrected_statement": null,
      "causality_strength": "strong",
      "causality_note": "上游L0成立且搜索素材数据明确支撑因果箭头"
    }}
  ]
}}
```

## 关键规则
1. Tushare 数据是硬证据，反例搜索是软证据——两者矛盾时偏向硬证据
2. 不确定时 Q1/Q2/Q3/Q4/Q5 宁可给低/保守，不要高估
3. 不要输出 status 或 confidence 字段（由后续代码确定性规则合成）
4. Q3 counter_conflict_score 必须是整数 0/1/2/3 之一
5. Q1 supporting_source_indices 必须是整数数组，不是字符串
6. Q5 chain_fit 必须严格为 "aligned" 或 "misaligned" 之一，不得输出其他值
