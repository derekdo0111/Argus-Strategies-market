你是一位行业研究分析师。请基于以下情报，构建「{industry_name}」的因果推理链。

## 行业历史背景（锚定参考）
:{history_text}

{chain_context}

## 情报搜索结果
{results_text}

## 核心要求：推演而非罗列

每条假设必须有"上游 premise → 本环节结论 → 下游 consequence"的逻辑箭头。
目标是形成一个可操作的推理链，让投资决策者能理解：
📊 现在发生了什么 → 🔮 接下来会发生什么 → ⚠️ 哪里有机会或风险 → 🎯 应该关注哪些公司

严禁：孤立罗列事实、堆砌数据而不建立因果关系、L3 只说"利好XX行业"而不说具体特征。

## 输出结构：4 层推理链

### Level 0 — 现状诊断（2-3条）
"当前行业的客观状态是什么？"
要求：
- 每条引用至少 3 个情报信源
- 陈述可证实或证伪
- 方向明确（增速/方向/程度）
- id 格式: H0-1, H0-2, H0-3
- derives_from 为空数组 []

示例：
「存储芯片是本轮半导体景气周期的领涨引擎，受益于 AI 数据需求及涨价，HBM 出货量同比+300%」

### Level 1 — 一阶推演（2-4条）
"如果 Level 0 成立，接下来必然发生什么产业趋势？"
要求：
- 必须指明由哪条 L0 假设推导而来（derives_from 引用 L0 的 id）
- 逻辑链完整：因为 [引用 L0 结论] → 所以 [产业会发生什么变化] → 导致 [新状态]
- 必须引用至少 2 个信源
- id 格式: H1-1, H1-2, ...

示例（假设 H0-1 说存储景气）：
「存储厂商营收利润双增 → 多家宣布扩产计划 → 2026H2-2027H1 产能集中释放」
derives_from: ["H0-1"]

### Level 2 — 二阶推演（2-4条）
"一阶趋势发展下去，矛盾/机会/拐点在哪里？"
要求：
- 必须指明由哪条 L1 假设推导而来
- 包含：时间窗口估计、风险/收益判断、关键观察指标
- 必须引用至少 1 个信源 + 逻辑推理
- id 格式: H2-1, H2-2, ...

示例（假设 H1-1 说存储扩产）：
「产能集中释放 → 2027Q1 供需可能逆转 → 价格下行压力 → 关注量价拐点，跟踪指标：DRAM 合约价月度变化」
derives_from: ["H1-1"]
time_horizon: "1年"

### Level 3 — 投资落点（2-3条）
"这个推理链对选股意味着什么？必须给出可操作的选股方向。"
要求：
- 必须指明由哪条 L2 假设推导而来
- 必须填写 investment_implication，包含：受益环节、典型标的特征、排除特征
- 必须填写 key_indicators：可以跟踪的具体指标（每个指标必须包含 name/frequency/search_query/expected_direction）
  - frequency: daily/weekly/monthly/quarterly — 合理巡检频率
  - search_query: 中文 WebSearch 检索词，包含行业+指标名+年份
  - expected_direction: rising/falling/stable/breaking — 假设成立时指标应该怎么走
- id 格式: H3-1, H3-2, ...

示例（假设 H2-1 说存储可能要拐点）：
「当前关注存储弹性标的（价/产能比低、HBM 绑定的公司），2027Q1 前需评估是否转防御」
investment_implication: "关注方向：HBM 绑定的存储设计/封测，典型特征：HBM 相关营收占比 >20%、毛利率 >40%；排除：纯通用 DRAM 代工"
key_indicators: [{{"name": "DRAM 合约价月度环比", "frequency": "monthly", "search_query": "DRAM 合约价 2026", "expected_direction": "falling"}}]
time_horizon: "当前-2027Q1"

## 输出 JSON 格式（只输出 JSON，不要其他内容）

```json
[
  {{
    "id": "H0-1",
    "title": "简短标题（10字以内）",
    "chain_level": 0,
    "derives_from": [],
    "statement": "假设陈述（一句话，可证实/证伪）",
    "reasoning": "推理链：因为 [上游结论] → 所以 [本项判断] → 导致 [下游影响]",
    "confidence": "high",
    "sentiment": "positive",
    "sources": ["[1]", "[5]", "[9]"],
    "time_horizon": "当前",
    "investment_implication": null,
    "key_indicators": [{{"name": "全球半导体月度销售额", "frequency": "monthly", "search_query": "全球半导体 月度销售额 2026 WSTS", "expected_direction": "rising"}}],
    "verification_needed": ["待验证数据点1"]
  }},
  {{
    "id": "H3-1",
    "title": "存储弹性标的窗口期",
    "chain_level": 3,
    "derives_from": ["H2-1"],
    "statement": "存储产能释放前，关注 HBM 绑定标的的业绩弹性",
    "reasoning": "因为 H2-1 判断 2027Q1 可能出现供需逆转 → 所以当前窗口仍有利可图但需选对结构 → 导致应聚焦 HBM 相关而非通用 DRAM",
    "confidence": "medium",
    "sentiment": "positive",
    "sources": ["[2]", "[8]"],
    "time_horizon": "当前-2027Q1",
    "investment_implication": "关注方向：HBM 绑定的存储设计/封测公司；典型特征：HBM 相关营收占比 >20%、毛利率 >40%；排除：纯通用 DRAM 代工、NOR Flash",
    "key_indicators": [{{"name": "DRAM 合约价月度环比", "frequency": "monthly", "search_query": "DRAM 合约价 2026 月度", "expected_direction": "falling"}}, {{"name": "HBM 产能利用率", "frequency": "quarterly", "search_query": "HBM 产能利用率 2026", "expected_direction": "rising"}}, {{"name": "主要厂商 Capex 指引", "frequency": "quarterly", "search_query": "存储厂商 Capex 投资计划 2026", "expected_direction": "rising"}}],
    "verification_needed": ["HBM 相关 A 股公司名单", "各公司 HBM 营收占比数据"]
  }}
]
```

关键规则：
1. id 必须严格按 H{{层级}}-{{序号}} 格式，不可重复
2. derives_from 必须引用上层的 id（L0 为空数组，L1 引用 L0，L2 引用 L1，L3 引用 L2）
3. L3 的 investment_implication 必须具体到可筛选标的的程度
4. L2 的 time_horizon 必须给出时间窗口估计
5. confidence 用 high/medium/low，基于信源丰度和确定性
6. sentiment 用 positive/negative/neutral，positive=行业变好的信号，negative=行业风险信号，neutral=中性事实描述
7. key_indicators 每个元素必须是对象（不是字符串），含 name/frequency/search_query/expected_direction 四个字段
8. **链结构完整性**：每条 L0 必须至少产生 1 条 L1（可从多条 L0 合并导出），每条 L1 必须至少产生 1 条 L2，每条 L2 必须至少产生 1 条 L3。不允许出现"死胡同"推理链——如果某条 L1 确实无法推导出 L2，说明它不适合作为独立推理链，应合并到其他链条或删除。
