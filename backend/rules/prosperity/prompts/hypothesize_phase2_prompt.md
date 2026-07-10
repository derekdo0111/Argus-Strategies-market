你是一位行业研究分析师。以下是已确定的推理链**骨架**，请为每条假设填充详细内容。

## 推理链骨架 — 不可修改，不可增删

以下骨架中的 id / title / chain_level / derives_from 为最终确定版本，**严格禁止增删改任何假设**：

{skeleton_text}

## 行业背景
行业: {industry_name}
{history_text}

{chain_context}

## 情报搜索结果
{results_text}

## 填充要求

请为骨架中的每条假设填充以下字段（仅填充内容，不动骨架）：

### statement（假设陈述）
- 一句话，可直接证实或证伪
- L0 的 statement 必须引用 ≥3 个情报信源编号

### reasoning（推理链）
- 必须体现「因为上游 premise → 所以本环节结论 → 导致下游 consequence」的逻辑箭头
- 引用 derives_from 中的上游假设 ID

### sentiment（方向）
- positive: 行业变好的信号
- negative: 行业风险信号
- neutral: 中性事实描述

### confidence（置信度）
- high: 多个信源一致指向，逻辑链完整
- medium: 有信源支撑但存在不确定因素
- low: 信源稀少或互相矛盾

### sources（信源引用）
- 字符串数组，引用情报编号如 ["[1]", "[5]", "[9]"]
- 每条假设至少引用 1 个信源，L0 至少 3 个

### verification_needed（待验证数据点）
- 字符串数组，列出需要后续验证的具体数据点

### key_indicators（关键跟踪指标）
- 对象数组，每个元素包含：
  - name: 指标名称
  - frequency: daily/weekly/monthly/quarterly
  - search_query: 中文 WebSearch 检索词（行业+指标名+年份）
  - expected_direction: rising/falling/stable/breaking

### investment_implication（投资含义，仅 L3 填写）
- 必须具体到可筛选标的的程度
- 包含：受益环节、典型标的特征、排除特征

### time_horizon（时间窗口）
- 如 "当前"、"当前-2027Q1"、"1年" 等

## 硬约束（违反则校验失败）

1. **id / title / chain_level / derives_from 必须与骨架完全一致**，不可增删改
2. 骨架中每条假设在输出中必须存在，不可缺少
3. 不可新增骨架中没有的假设
4. L3 必须有 investment_implication
5. L2 必须有 time_horizon 估计

## 输出格式

只输出 JSON 数组（保留骨架中的 id/title/chain_level/derives_from，填充其余字段）：

```json
[
  {{
    "id": "H0-1",
    "title": "AI算力需求爆发",
    "chain_level": 0,
    "derives_from": [],
    "statement": "全球AI算力需求持续爆发，2026年HBM出货量同比+300%，数据中心资本开支创历史新高",
    "reasoning": "情报[1][3][5]一致显示AI投资加速 → 算力成为稀缺资源 → 算力相关产业链全面受益",
    "confidence": "high",
    "sentiment": "positive",
    "sources": ["[1]", "[3]", "[5]"],
    "time_horizon": "当前",
    "investment_implication": null,
    "key_indicators": [{{"name": "全球半导体月度销售额", "frequency": "monthly", "search_query": "全球半导体 月度销售额 2026 WSTS", "expected_direction": "rising"}}],
    "verification_needed": ["2026Q2 全球数据中心Capex数据", "HBM出货量预测准确度"]
  }}
]
```
