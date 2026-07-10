# Changelog

All notable changes to Investment Strategy project.

## v1.2.2 (2026-07-10) — 高景气策略 Mockup → React 前端合并

### 前端重构
- **ProsperityMindmap.tsx + .module.css**: Mockup HTML 拆为 React 组件，含摘要卡片、知识图谱、L0-L3 四层推理链（12张假设卡片，展开/收起）
- **ProsperityStockPanel.tsx + .module.css**: 股票面板（上/中/下游 Tab × 18 只 + SVG 六边形雷达图 + 点击联动）
- **prosperity-types.ts + prosperity-data.ts**: 类型定义 + Mock 数据（后续接后端 API 替换）
- **Layout.tsx**: `poolComponents` 映射替换 `ProsperityHypothesisBoard → ProsperityMindmap`，`reportComponents` 映射替换 `ProsperityReportViewer → ProsperityStockPanel`
- **index.css**: 新增 `--l0/--l1/--l2/--l3` 四色层级变量

### 联动效果
- 左侧边栏切到「高景气策略」→ 中栏显示脑图推演看板 → 右栏显示股票面板
- 点击任意股票 → 右栏底部弹出该股六维雷达图
- 点击推理卡片 → 展开显示假设陈述/推理链/验证诊断/跟踪指标
- 色系与全局设计系统完全统一（CSS 变量复用）

### 待保留旧文件
- `HypothesisBoard.tsx` / `ReportViewer.tsx` 不再被引用，暂留备查

## v1.2.1 (2026-07-10) — VerifyAgent 冲突阈值修复 + ReportAgent 级联修正展示

### Bug 1: 弱冲突多轮一致错判为 strong → overtuned
- **问题**: H0-2（HBM产能结构性短缺）3轮 LLM 均打 2分（"有矛盾但不推翻"），但 `_aggregate_rounds()` 规则 `≥2轮≥2分 → strong` 导致错判为 overturned → 级联拉下 H1-1/H1-3 unreachable → 评级从高景气掉到景气
- **修复**: 只保留 `≥1轮≥3分 且 ≥2轮有冲突` → strong。3轮全2分 → weak（weak_disputed，不切链）
- **影响**: 弱反例（score=2）不再被聚合升级为 overtuned，仅 multi-round score=3 的一致性才算 strong

### Bug 2: CounterAgent 修正信息未出现在最终报告
- **问题**: CounterAgent 做 sentiment 修正（positive→negative）和级联裁决后，报告中看不到任何追溯痕迹
- **修复**: `_render_report()` "验证诊断"区块新增两个子项：
  - `original_sentiment` 存在且不同于 `sentiment` → 展示 `{old} → {new}` 方向变更
  - `causality_note` 含 "CounterAgent" → 提取展示级联裁决原因
- **影响**: 用户可在报告中看到每一条假设的 CounterAgent 修正痕迹

### 改动文件
- `verify_agent.py`: `_aggregate_rounds()` 冲突阈值收紧
- `report_agent.py`: `_render_report()` +CounterAgent 修正追溯
- `CHANGELOG.md`, `pyproject.toml`: 版本号 1.2.0 → 1.2.1

### 测试
- 208/208 ✅ | 版本: v1.2.0 → v1.2.1

## v1.2.0 (2026-07-10) — ScreeningAgent v2：从穷举分类改为精选推荐

### 动机
- v1.1.0 LLM 一次性处理 201 只股票 → 超时 → 全走程序化兜底 → 假设命中全空 → 股池退化为纯财务排名
- 用户要的是"15-20 只精选龙头、覆盖上下游"，不是"50 只无标注清单"

### 架构变化
- **旧**: Stage 1 LLM 一次全部分类+标记 → Stage 2 打分 → Stage 3 财务
- **新**: Stage 1 程序化预筛+分段+全量财务预排 → Stage 2 LLM 分段精选（每段挑 5-8 只）→ Stage 3 打分+分段排名
- 候选池 = 财务预排 top 18/段 + 代表公司强制豁免（防止战略重要股被财务排掉）
- purity_estimate 从 LLM 猜测 → 程序化营收比例计算

### 重写：screening_agent.py
- Stage 1: `_programmatic_prescreen()` 精细化关键词分类（下游排他：模组/SSD/分销优先归 downstream）
- Stage 1: `_financial_prerank()` 全量财务预排名 → 候选池
- Stage 2: `_llm_select_batched()` 每段独立 LLM 调用，从 18-25 只候选挑 6 只
- Stage 3: 程序化三维打分（仅精选股）
- 新增 `_extract_rep_companies()` — YAML 代表公司→ts_code 映射
- 新增 `_compute_purity()` — 主营业营收比例程序化计算
- 删旧 `_llm_classify_and_match()`（一次塞 201 只的超时方案）
- `timeout` 接通 `PROSPERITY_SCREENING_LLM_TIMEOUT`

### 重写：screening_direction_prompt.md
- 任务从「分类到环节 + 标记命中 + 估计纯度」→「从候选池挑选 top K 只最匹配假设的股票」
- 输出从 201 条 JSON → 每段 5-8 条 {ts_code, positive_hits, negative_hits, selection_reason}

### 修改
- `screening_scorer.py`: score_stock_pool 输出 +`selection_reason`
- `report_agent.py`: 股池表格 +「挑选理由」列
- `config.py`: `PROSPERITY_SCREENING_BATCH_SIZE` → `PROSPERITY_SCREENING_TOP_PER_SEGMENT=6`

### 测试
- 208/208 ✅ | 版本: v1.1.0 → v1.2.0

### 改动文件
- 重写: `screening_agent.py` (~380行→~450行), `screening_direction_prompt.md`
- 修改: `screening_scorer.py` (+1字段), `report_agent.py` (+1列), `config.py` (1配置), `pyproject.toml`, `test_prosperity_coordinator.py` (2测试适配)

---

## v1.1.0 (2026-07-09) — 假设树感知分赛道筛选 + 验证诊断展示（Phase 7）

### 动机
- 股池 170 只混在一张表按纯度分排名，分销商排第一、锂电设备混进存储芯池——读者分不清核心标的
- 合成报告看不到修正陈述和因果链强度——验证环节的核心发现被丢弃
- L3 投资含义写了筛选标准但 ScreeningAgent 完全不消费
- LLM 方向匹配任务模糊（打分 0~1）→ 超时/随机，方向分全部 0.50

### 新建：screening_scorer.py
- `hypothesis_weight(h)` — 单条假设有效评分权重
  - `causality_strength == "broken"` → 0.0（因果链断裂·不参与评分）
  - `overturned / unreachable` → 0.0
  - 有 `corrected_statement` → 基础权重 × 0.5
  - 正常：STATUS_WEIGHT × LAYER_WEIGHT × CAUSALITY_DISCOUNT
- `hypothesis_direction(h)` — 考虑修正陈述反转的实际方向
- `format_hypothesis_tree()` — 假设树 → LLM prompt 摘要（分组正/负/中性，broken 标注"不参与判断"）
- `score_stock_pool()` — 三维打分：景气适配 Σ(正面命中×权重)、风险暴露 Σ(负面命中×权重)、质量 (ROE+毛利+增速)/3
  - 综合 = 景气适配 × 0.5 - 风险暴露 × 0.3 + 质量 × 0.2

### 重写：screening_agent.py（v1.0.5 → v1.1.0）
- **旧**: 4 阶段（LLM方向匹配 → 纯度 → 财务 → 一张大表排名）
- **新**: 3 阶段
  - Stage 1: `_llm_classify_and_match()` — LLM 单次调用：分类到环节(upstream/mid/downstream) + 标记命中了哪些假设 + 关联占比估计(0~1)
  - Stage 2: 程序化三维打分（消费 `screening_scorer.hypothesis_weight()`）
  - Stage 3: 财务拉取（仅存活股票）→ 分赛道排名
- 删旧 4 阶段逻辑：`_llm_direction_match()` → 替换为 `_llm_classify_and_match()`
- 删旧 `_compute_purity()` 阶段（纯度判断合并到 Stage 1 LLM 中）
- 新增 `_programmatic_classify()` — LLM 不可用时确定性关键词兜底
- 输出新增 `segments` 字段：`{upstream: [...], mid: [...], downstream: [...]}`

### 重写：screening_direction_prompt.md
- 任务从「给每只股票打分 0~1」→「分类到环节 + 标记命中了哪些假设 + 关联占比估计」
- 输入从仅 L3 假设 → 完整假设树摘要（正面/负面/中性分组 + 权重标注）
- 输出从 `{score, matched_l3, reason}` → `{segment, positive_hits, negative_hits, purity_estimate, excluded, exclude_reason}`

### 修改：report_agent.py
- 每条假设渲染段推理链后新增「验证诊断」小节：
  - 因果链强度（✅/⚠️/🔍/⚡）+ broken 标注"不参与选股评分"
  - 修正陈述（corrected_statement）
  - 验证说明（reason, 限 200 字）
- 股池从一张大表 → 三张分段独立表格（📦 上游设备与材料 / 📦 中游设计与制造 / 📦 下游模组与应用）
  - 列名从「纯度分/方向分/ROE/毛利率/营收增速/匹配方向」→「景气适配/风险暴露/质量/综合/ROE/毛利率/营收增速/命中假设」

### 设计决策
- **LLM 不能省但任务要换**：关键词匹配不能跨行业通用 → LLM 从「打分裁判」降级为「分类+标注记分员」
- **purity_estimate 三层折扣**：混血公司（18% 关联）不被硬排除但景气适配 × 0.18 → 自然下沉
- **broken 假设不参与评分**：H2-1「远期产能过剩隐忧」因果链断裂 → weight=0，不扣高资本开支股票的分
- **分赛道展示**：用户看到上游设备 vs 中游制造 vs 下游模组三张独立的表，各自排名

### 测试
- 208/208 ✅ 零回归 | 版本: v1.0.5 → v1.1.0
- 修复 2 个旧测试（方向分/纯度分 → 景气适配/命中假设）

### 改动文件
- 新建: `tools/screening_scorer.py` (~190行)
- 重写: `agents/screening_agent.py` (~530行, 4阶段→3阶段)
- 重写: `prompts/screening_direction_prompt.md` (~85行)
- 修改: `agents/report_agent.py` (+~40行 诊断 + ~20行 分段表)
- 修改: `tests/test_prosperity_coordinator.py` (2 测试适配)
- 修改: `pyproject.toml`, `CHANGELOG.md`

---

## v1.0.5 (2026-07-09) — ScreeningAgent 消费 chain_model（Phase 6）

### 动机
- ScreeningAgent 签名已预留 `chain_model=None`，但 `_llm_direction_match()` 未注入
- LLM 方向匹配只看「搜索片段 + L3 陈述」判断股票归属，缺乏产业链上下文
- 代表公司/环节分类/瓶颈级别等信息有助于校准方向匹配精度

### 改动：screening_agent.py
- 新增 `_format_chain_context()`：从 YAML 提取 3 块方向匹配专属上下文
  - 代表公司表格（正例锚点 + 瓶颈级别 + 国产化率）
  - 环节描述（股票分类参考）
  - 方向匹配使用规则（代表公司锚定 / 环节分类 / 瓶颈校准）
- 修改 `_llm_direction_match()`：新增 `chain_model=None` 参数 → 注入 `{chain_context}`
- 修改 `screen()` Stage 1：透传 `chain_model` 到方向匹配
- 头注释 + class docstring：v0.18 → v0.19

### 改动：screening_direction_prompt.md
- 搜索素材和成分股列表之间插入 `{chain_context}` 占位符
- 新增 1 条链感知规则：股票是产业链代表公司 → 默认 0.8~1.0
- 新增瓶颈校准规则：bottleneck=high → 方向分可上调 0.1

### 不动
- `_compute_purity()` — 确定性关键词路径，无 LLM
- `purity_scorer.py` — 主路径确定性代码，LLM 回退路径 <1% 不值得扩接口

### 设计决策
- `_format_chain_context()` 自包含（与 Hypothesize/Verify/Counter 同模式，各 Agent 独立实现）
- 只改 Stage 1 方向匹配，不碰 Stage 2 纯度打分（边际收益低，不值得调 3 个函数签名）
- chain_model=None 时返回占位文本，零影响

### 测试
- 208/208 ✅ 零回归 | 版本: v1.0.4 → v1.0.5

---

## v1.0.4 (2026-07-09) — CounterAgent 消费 chain_model + prompt 模板化（Phase 5）

### 动机
- CounterAgent 签名已预留 `chain_model=None`，但 `_build_cascade_prompt()` 未注入
- prompt 全部内嵌在代码（~90 行硬编码），无独立模板文件
- LLM 做级联裁决时看不到产业链全貌 → 推翻门槛/disputed分类/sentiment校准无依据

### 改动：counter_agent.py
- 新增 `_load_templates()`：加载 `counter_cascade_prompt.md` 模板
- 新增 `_format_chain_context()`：从 YAML 提取 6 块级联裁决专属上下文
  - 产业链环节瓶颈视图（表格：瓶颈级别 + 国产化率 + 瓶颈说明）
  - 全局瓶颈汇总
  - 供需格局（disputed 分类参考：供需短缺→程度变化，产能过剩→方向反转）
  - 技术路径成熟度（sentiment 校准：工程验证≠规模化）
  - 级联裁决使用规则（推翻门槛、disputed分类、sentiment校准、跨环节依赖）
- 修改 `_build_cascade_prompt()`：从硬编码迁移到模板 `.format()` + `{chain_context}` 注入
- 新增 `_build_fallback_prompt()`：模板文件缺失时的内嵌降级
- 修改 `_llm_cascade`：接收 `chain_model` → `_format_chain_context()` → 注入 prompt
- 修改 `cascade()`：透传 `chain_model` 到 `_llm_cascade()`

### 改动：新增 counter_cascade_prompt.md
- `rules/prosperity/prompts/counter_cascade_prompt.md`：~110 行模板
- 继承原 v2.1 全部硬编码规则 + 新增 `{chain_context}` 占位符 + 链感知裁决指引

### 设计决策
- CounterAgent 不适合做 VerifyAgent 式算术化拆分（级联裁决本质是全局链级语义判断，不可逐假设原子化）
- 不新增程序化规则 — LLM 仍然做语义法官，但上下文从「盲人摸象」升级为「产业链全景地图」
- 模板降级：`counter_cascade_prompt.md` 不可用时 fallback 到 `_build_fallback_prompt()`（与原逻辑等价）

### 测试
- 208/208 ✅ 零回归 | 版本: v1.0.3 → v1.0.4

---

## v1.0.3 (2026-07-09) — VerifyAgent Q5 链适配度深度重构（Phase 4）

### 动机
- v1.0.2 仅在 verify_prompt.md 中插入 `{chain_context}` 占位符，Q1-Q4 判定规则仍未链感知
- chain_context 作为"使用规则"附在 prompt 末尾，LLM 大概率忽略
- 产业链拓扑从"参考书"升级为"评分标准"

### 改动：verify_prompt.md（Q1-Q5 全量链感知重写）
- **Q1 信源对口**：先判断假设对应环节 → 只算涉及该环节 bottleneck/代表公司/关键指标的信源
- **Q2 数据对齐**：参考 tracking_indicators.meaning + supply_demand.overall_judgment（如"严重供需短缺"→正方向）
- **Q3 瓶颈校准**：bottleneck level=high/critical + 国产化率<30% → 反例至少 1 分；反例不涉瓶颈 → 最高 1 分
- **Q4 情感联动**：sentiment 与 bottleneck level 联动（high/critical 的负面信号更严重）
- **Q5 chain_fit（新增）**：independent dimension — aligned / misaligned，判定假设是否契合产业链拓扑现实

### 改动：verify_agent.py
- `_synthesize_confidence()`：+chain_fit ±1 级修正（aligned→升一级, misaligned→降一级）
- `_synthesize_status()`：chain_fit **不影响** status（避免旧知识惩罚新信息）
- `_aggregate_rounds()`：Q5 众数聚合 + 传入合成函数
- `_parse_verification_result()`：单轮路径支持 chain_fit
- `_format_chain_context()`：使用规则升级为 Q5 体系

### 设计决策
- chain_fit 只改 confidence 不改 status（brainstorming 结论：Q5 misaligned 可能是"新信息"而非"逻辑错误"）
- Q5 2 档 aligned/misaligned（非 3 档）减少 LLM 自由度
- Q4 砍掉"信号放大效应"（不可操作化），改为 bottleneck 联动
- Q2 不依赖 tracking_indicators.expected_direction（该字段不存在），改用 meaning 文本 + overall_judgment

### 测试
- 208/208 ✅ 零回归 | 版本: v1.0.2 → v1.0.3

---

## v1.0.2 (2026-07-09) — VerifyAgent 消费 chain_model（Phase 3）

### 动机
- VerifyAgent 签名已预留 `chain_model=None`，但验证 prompt 中未注入产业链拓扑
- 导致 LLM 验证信源/数据/反例时缺乏环节锚点：不知道假设对应哪个产业链环节、该环节的瓶颈级别/国产化率/跟踪指标
- 反例搜索词生成也无法定向搜索 bottleneck 环节的薄弱点

### 改动
- **`verify_agent.py`**：
  - 新增 `_format_chain_context(chain_model)` → YAML 转 prompt 友好文本（与 HypothesizeAgent 同逻辑，各 Agent 自包含）
  - `chain_model` 串入 `_verify_chain_with_llm()` 和 `_generate_counter_queries()` → prompt 注入产业链拓扑
  - `chain_model=None` 时返回空字符串，零影响
- **`verify_prompt.md`**：新增 `{chain_context}` 占位符（位在历史上下文之后、Tushare 数据之前）
- **`counter_query_prompt.md`**：新增 `{chain_context}` 占位符 + 优先搜索 bottleneck 环节的指引

### 效果
- Q1 信源计数：LLM 知道假设对应哪个环节，判断信源是否「对口」
- Q2 数据对齐：参考 `tracking_indicators` 的巡检频率和方向预期
- Q3 反例冲突：结合 bottleneck 的国产化率/瓶颈级别校准打分（如国产化率<30% 的真瓶颈 ≠ 正例不足）
- 反例搜索词：可定向搜索 bottleneck 环节的薄弱点（如"刻蚀设备 国产化率 瓶颈"）

### 测试
- 204/204 ✅ 零回归 | 版本: v1.0.1 → v1.0.2

---

## v1.0.1 (2026-07-09) — HypothesizeAgent 消费 chain_model（Phase 2）

### 动机
- HypothesizeAgent 签名已预留 `chain_model=None`，但 3 个 prompt builder 均未注入产业链拓扑
- 导致假设生成完全依赖搜索片段，无法利用已验证的产业链结构（环节/瓶颈/代表公司/跟踪指标）

### 改动
- **`hypothesize_agent.py`**：
  - 新增 `_format_chain_context(chain_model)` → YAML 转 prompt 友好文本（7 大板块：产业链结构/瓶颈视图/供需格局/技术路径/跟踪指标/使用规则）
  - `chain_model` 串入 `_form_single_round` / `_phase1_skeleton` / `_phase2_fill` → 所有 `_build_*_prompt()` 消费
  - `chain_model=None` 时返回空字符串，零影响
- **`hypothesize_prompt.md`**：新增 `{chain_context}` 占位符
- **`hypothesize_phase1_prompt.md`**：新增 `{chain_context}` 占位符
- **`hypothesize_phase2_prompt.md`**：新增 `{chain_context}` 占位符

### 效果
- 假设的 L3 投资落点锚定 `representative_companies`
- L0 核心命题围绕供需矛盾展开（不再孤立引用新闻片段）
- 瓶颈环节（high/critical）获得更多假设覆盖
- `key_indicators` 优先参考 `tracking_indicators` 中已验证指标

### 测试
- 204/204 ✅ 零回归 | 版本: v1.0.0 → v1.0.1

---

## v1.0.0 (2026-07-09) — Wiki-Centric 架构 v1.0 Phase 0+1

### 动机
- wiki 被当成流水线末端「归档输出」，LearningAgent 生成的完整产业图谱（价值链/瓶颈/跟踪指标）无 agent 消费
- CounterAgent 做上下游级联裁决，却不知道产业链拓扑结构（连 `history` 参数都没有）
- 需要把 wiki 从「尾气」升级为所有 agent 共用的「中枢知识库」

### Phase 0 — YAML Schema + LearningAgent 扩写
- **`data/prosperity/wiki/industries/存储芯片.yaml`**（新增）：样本 YAML，含 chain.segments（上游/中游/下游含瓶颈标注）、bottlenecks、supply_demand、technology_paths、tracking_indicators
- **`learning_prompt.md`**：新增 §8 YAML 输出要求（产业链结构化数据）
- **`learning_agent.py`**：`learn()` 返回 `Tuple[str, Optional[dict]]` → (markdown, yaml_dict)；新增 `_extract_yaml()` 解析 LLM 输出中的 ` ```yaml ` 块
- **`coordinator.py` `_run_learning_agent()`**：同步写入 `{name}.yaml` 伴生文件

### Phase 1 — Coordinator `_load_chain_model()` + Agent 签名预留
- **`coordinator.py`**：新增 `_load_chain_model()` → 加载 `industries/{name}.yaml`；管道注入 `chain_model` 到 4 个 agent
- **`hypothesize_agent.py`**：`form_hypotheses()` 签名新增 `chain_model=None`（Phase 2 消费）
- **`verify_agent.py`**：`verify()` 签名新增 `chain_model=None`
- **`counter_agent.py`**：`cascade()` 签名新增 `history=None, chain_model=None`（**修复：Counter 之前没 history**）
- **`screening_agent.py`**：`screen()` 签名新增 `chain_model=None`

### 文档
- **Spec**: `docs/specs/2026-06-29-prosperity-strategy-design.md` → v0.24，新增 §11 Wiki-Centric 架构
- **Plan**: `docs/plans/2026-07-09-prosperity-wiki-centric.md`（新增）
- **SCHEMA**: `data/prosperity/SCHEMA.md` 不变（YAML 协议在 Spec §11 定义）

### 测试
- 204/204 ✅ 零回归 | 版本: v0.23.7 → v1.0.0

### 后续（Phase 2+，另案讨论）
- HypothesizeAgent / VerifyAgent / CounterAgent 如何消费 YAML 构建分析飞轮
- ScreeningAgent 消费 YAML → 多桶输出 + 角色标签

---

## v0.23.7 (2026-07-08) — resolve() 精确命中修复

### 修复
- **`concept_index.py`**: `resolve()` 不再对多个匹配概念求并集。精确命中（score=100）只用那一个概念，模糊匹配只用最佳匹配。修复"人工智能"→ AI智能体+AIGC概念并集导致 1074 只而非预期的 1060 只的 bug。

## v0.23.6 (2026-07-08) — 成分股超限交互式子板块推荐

### 动机
- `screening_agent.py` 硬截断 `[:50]` 丢掉了 55% 的成分股（如"人工智能"111→50），且截断无序不等于"最好的50只"
- 不能用财务预筛替代（会误杀景气早期优质标的），也不能无上限全量（LLM 成本可控）
- 设计决策：超限时交互式推荐子板块，让用户决定聚焦方向

### 新增
- **`concept_index.py`**: 新增 `suggest_subconcepts(main_name)` — rapidfuzz 搜索子概念 + 成分股数过滤 + 排除自身
- **`coordinator.py`**: 新增 `check_industry_size(industry_name)` — 预检成分股数，超阈值返回子板块推荐列表
- **`config.py`**: 新增 `PROSPERITY_SCREENING_THRESHOLD: int = 50`（触发阈值）
- **`run_prosperity_ai.py`**: 重构为完整 CLI 工具，`--force-full` 跳过交互，支持交互式子板块选择

### 修改
- **`screening_agent.py`**: 删除硬截断 `[:50]`，超限由上游 coordinator 处理

### 测试
- 待跑 | 版本: v0.23.5 → v0.23.6



## v0.23.5 (2026-07-08) — ConceptIndex：概念板块本地索引 + rapidfuzz 模糊搜索

### 动机
- `get_industry_ts_codes()` 的 5 层信源中，信源4（ths_index → ths_member）每次查询都需逐个拉取概念板块列表 + 用 `str.contains()` 做简陋模糊匹配
- 按名称找概念板块是高频操作（行业分类匹配、verify_agent 反例搜索），但缺乏一个预建的全量索引
- 设计决策：ConceptIndex 是基础设施组件（类似 `tushare_client.py`），不属于 Wiki 研究内容

### 新增
- **`concept_index.py`** (`tools/concept_index.py`): 核心模块，3 个对外函数
  - `build(force)`: 从 Tushare `ths_index(type=N)` 全量拉取概念板块列表 → 写入 `data/concept_index.yaml`（24h TTL）
  - `search(name, threshold, limit)`: rapidfuzz `WRatio` 模糊搜索，中文友好（如 "新能源" → "新能源汽车" 90%）
  - `resolve(name)`: 一键搜索 + 获取成分股（`ths_member`），替代原信源4 的逐次查询
- **`data/concept_index.yaml`**: 409 个概念板块的全量索引缓存
- **依赖**: `rapidfuzz` (pyproject.toml)

### 修改
- **`industry_metrics.py`**: `get_industry_ts_codes()` 新增信源0 — ConceptIndex rapidfuzz 优先（最快路径）
- **`pyproject.toml`**: +rapidfuzz ^3.14.0

### 测试
- 204/204 ✅ | 版本: v0.23.4 → v0.23.5

## v0.23.4 (2026-07-08) — VerifyAgent + TrackAgent 全部升级 Bocha 主搜索

### 动机
- VerifyAgent 和 TrackAgent 仍硬编码直接调 Tavily，Bocha Key 配置后依然报 Tavily 错误
- 至此 Prosperity 的所有 4 个 Agent + 1 个 Tool 全部完成 Bocha 为主、Tavily 为备的搜索引擎架构

### 改动文件
- **`verify_agent.py`**:
  - `__init__`: 新增 `bocha_api_key`
  - 新增 `_detect_engine()`: Bocha > Tavily > none
  - 新增 `_bocha_search()`: 调用 Bocha Web Search API
  - 新增 `_tavily_counter_search()`: Tavily 降级备用
  - `_execute_counter_searches()`: 引擎分发取代硬编码 Tavily
- **`track_agent.py`**:
  - `__init__`: 新增 `bocha_api_key`
  - 新增 `_detect_engine()`: Bocha > Tavily > none
  - 新增 `_web_search()`: 引擎分发入口
  - 新增 `_bocha_search()`: 调用 Bocha Web Search API
  - `_tavily_search()`: 降级为备用
  - `_check_single()`: `_tavily_search` → `_web_search`

### 架构总结
| Agent/Tool | v0.23.3 | v0.23.4 |
|-----------|---------|---------|
| search_agent | ✅ Bocha | ✅ Bocha |
| concept_builder | ✅ Bocha | ✅ Bocha |
| verify_agent | ❌ Tavily | ✅ Bocha |
| track_agent | ❌ Tavily | ✅ Bocha |
| hypothesize_agent | N/A | N/A |
| report_agent | N/A | N/A |

### 副作用
- 全部 4 处 Tavily 硬编码已收敛到降级路径，Bocha Key 配置后全网搜索走 Bocha

## v0.23.3 (2026-07-08) — 概念板块构建器升级 Bocha 主搜索

### 动机
- 「人工智能」概念板块漏掉兆易创新(603986.SH)等关键标的：`concept_builder` 仍硬编码用 Tavily，未跟随 v0.23 SearchAgent 的 Bocha 升级
- Tavily 搜索结果只有 8000 字符的 LLM 提取窗口，兆易创新可能被截断在上下文外
- Bocha 中文覆盖更优，summary 字段可达数千字，应作为概念板块构建的主搜索引擎

### 改动文件
- **`concept_builder.py`**:
  - 新增 `_detect_engine()`: Bocha > Tavily > none
  - 新增 `_bocha_search()`: 调用 Bocha Web Search API (`/v1/web-search`)，与 SearchAgent 对齐参数 (`freshness=oneYear`, `summary=True`)
  - `search_concept_stocks()`: 引擎分发取代硬编码 `_tavily_search()`，Bocha 失败自动降级 Tavily
  - 更新 docstring: "Tavily only" → "Bocha 主搜索 + Tavily 备用"

### 副作用
- 删除 `data/prosperity/concept_boards/人工智能.yaml`（旧 Tavily 缓存），下次运行自动用 Bocha 重建

### 测试
- 204/204 ✅


## v0.23.2 (2026-07-08) — 纯度分全 0 Bug 修复

### 动机
- 所有股票纯度分（purity_score）全为 0.00%
- 根因：`investment_implication` 字段实际是 dict（如 `{'受益环节': 'GPU/ASIC...', '典型标的特征': '...'}`），而 `_extract_l3_keywords()` 中 `re.split()` 期望它是 str → TypeError
- 异常被 `_compute_purity()` 的 `except Exception` 静默吞掉 → 全返回 0

### 改动文件
- **`purity_scorer.py`**:
  - 新增 `_flatten_field()`: 安全处理 dict/str/None 三种类型，dict 时拼接 values 为字符串
  - `_extract_l3_keywords()`: 三字段均通过 `_flatten_field()` 转换后再 `re.split()`
  - `_llm_match_fallback()`: 投资含义使用 `_flatten_field()` 避免 ugly dict repr
- **`screening_agent.py`**:
  - 新增 `_flatten_implication()`: 同上功能本地版本
  - `_llm_direction_match()`: 投资含义使用 `_flatten_implication()` 转换
  - `_compute_purity()`: 异常处理新增 `traceback.format_exc()` 日志（不再静默吞堆栈）

### 测试
- 204/204 ✅

## v0.23.1 (2026-07-08) — CounterAgent 安全网：防止 partial/unverified 被误杀

### 动机
- 「人工智能」行业：CounterAgent LLM 将 3 条 partial/unverified 假设误判为 overturned →
  级联屠杀导致 L2/L3 全部 unreachable → 股池 = 0（行业「景气」却说不出哪个股票好）
- 根因：LLM prompt 未区分「数据不充分」(partial) 和「被证伪」(overturned)
- 修复方向：让 prompt 精确区分 + 代码层安全网兜底

### 改动文件
- **`counter_agent.py`**: 
  - `_build_cascade_prompt()`: 新增「绝对禁止」章节——partial/unverified 绝不 overturned；disputed 区分强反例(方向反转)vs 弱反例(程度变化)
  - `_apply_cascade()`: 代码层安全网——即使 LLM 不听话，partial/unverified 强行 downgrade_confidence
  - `_hardcoded_cascade()`: LLM 失败兜底改用方向反转关键词(缩减/转负/萎缩)判定 disputed→overturned
  - 超时从硬编码 120s → `settings.PROSPERITY_COUNTER_TIMEOUT`
- **`config.py`**: 新增 `PROSPERITY_COUNTER_TIMEOUT: int = 120`；版本 0.23.0→0.23.1
- **`docs/specs/2026-06-29-prosperity-strategy-design.md`**: v0.22→v0.23
- **`pyproject.toml`**: 0.22.0→0.23.1

### 效果预期
- partial/unverified 绝不再被 overturned（有 LLM prompt + 代码安全网双重保护）
- disputed 仅在被确凿方向反转时才 overturned
- 「人工智能」股池预期从 0 → 15-25 只
- 级联仍正常工作（真正被证伪的仍切断）

## v0.23.0 (2026-07-08) — Bocha 中文搜索 + 截断解除 ✅ 已实施

### 动机
- 上一轮 brainstorming 分析：67% 零信源率，Tavily 中文覆盖弱占 30% 责任，截断 3000 字符占 20%
- Bocha 免费替代：中文搜索覆盖更优 + 返回详细摘要(summary 字段)，无需截断
- 先止血（免费措施），再评估要不要上付费数据

### 改动文件
- **`config.py`**: 新增 `BOCHA_API_KEY` 配置项；版本号 0.21→0.23
- **`.env` / `.env.example`**: 新增 `BOCHA_API_KEY=`，Tavily 标记为备用
- **`search_agent.py`**: 新增 `_bocha_search()` 方法（端点 `POST /v1/web-search`，Bearer 认证）；`_detect_engine()` 自动选择 Bocha > Tavily；内容截断 500→10000 字符 (`MAX_CONTENT_CHARS`)
- **`hypothesize_agent.py`**: `_build_search_results_text()` 新情报解除 300 字截断，旧情报保持 500 字摘要

### 使用方式
1. 在 https://open.bochaai.com/dashboard 获取 API Key
2. 填入 `.env` 的 `BOCHA_API_KEY=`
3. 自动生效 — SearchAgent 会优先使用 Bocha，未配置时回退 Tavily

### 效果预期
- 中文搜索结果质量 ↑（Bocha 中文语料库 > Tavily）
- LLM 可看到的素材长度 ↑（10x+），减少"数据不在素材中"的 unverified
- 零信源率预期从 67%→40%（配合解除截断）

## v0.22.0 (2026-07-07) — 精确分类级联：强反例推翻 vs 弱反例降级 ✅ 已实施

### 动机
- 「人工智能」行业 12 条假设仅 1 条是真正强反例(H1-2)，却因级联误杀导致 8 条 unreachable
- 根因：Q3 counter_conflict 使用布尔 yes/no，弱反例(单轮 LLM 打 2 分)与强反例同等待遇 → disputed → overturned → 级联整链崩溃
- 方案：Q3 三级分级(none/weak/strong) + 多轮一致原则 + weak_disputed 降级不切链

### 改动文件
- **`verify_agent.py`**: Q3 聚合从布尔升级为三级分级(多轮一致原则)；`_synthesize_status` 入参从 `counter_conflict: str` → `conflict_level: str`；新增 `weak_disputed` 状态(降级不切链)；`_cascade_safety_net` 切断集合移除 disputed
- **`counter_agent.py`**: LLM 级联 prompt 更新为 v0.22 规则；`_hardcoded_cascade` 切断集合从 `{overturned, unreachable, disputed}` 收敛为 `{overturned, unreachable}`
- **`verify_prompt.md`**: Q3 评分说明增加分级指南，强调不要把"侧面对比"打到 2/3 分
- **`report_agent.py`**: SIGNAL_MAP 新增 weak_disputed 映射(positive+weak_disputed=0.3)；status_map 新增 🟡 emoji
- **`coordinator.py`**: CounterAgent 日志补充 weak_disputed 统计
- **`docs/specs/2026-06-29-prosperity-strategy-design.md`**: Spec 更新至 v0.22
- **`tests/test_prosperity_coordinator.py`**: 测试适配 v0.22 新参数/新状态

### 效果
- 仅 `strong` 反例(≥2 轮 LLM 一致) → overturned → 切断下游
- `weak` 反例(单轮孤立) → weak_disputed → 降级不切，靠 SIGNAL_MAP + causality_discount=0.4 自然稀释
- 预期：「人工智能」12 条假设中 11 条保持活跃，仅 H1-2 被推翻

## v0.21.2 (2026-07-06) — LLM 超时快速失败机制 ✅ 已实施

### 动机
- 07-05 收敛性实验 3 次全超时，每轮等待 7.5 分钟才退出——纯粹浪费 22+ 分钟
- 根因：(1) `_call_llm_phase1` 硬编码 30s 超时无视 `.env` 配置；(2) 超时被 `_call_llm` 吞掉返回 `"[]"`，触发多层 fallback 重试链
- 方案：超时 → 抛异常 → 不 fallback → 直接终止

### 改动文件
- **`hypothesize_agent.py`**:
  - 新增 `LLMUnavailableError` 异常类
  - `_call_llm`: Timeout/ConnectionError → `raise LLMUnavailableError`（不再吞异常返回 `"[]"`）
  - `_call_llm_phase1`: 硬编码 `30` → `getattr(settings, "PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT", 30)`（与 `.env` 对齐）
  - `_phase1_skeleton`: 全轮超时时 `raise LLMUnavailableError`（不再 fallback 到 120s 单轮）
  - `_phase2_fill`: 超时时 `raise LLMUnavailableError`（不再重试 3×60s）
  - `form_hypotheses`: Phase 2 LLM 不可用时 propagate 异常（不再 fallback 到单轮）
- **`convergence_experiment.py`**:
  - `run_pipeline_with_patches`: 捕获 `LLMUnavailableError`，返回 `{"status": "failed"}`
  - `main()`: 每个 Run 后检查 `status == "failed"`，立即终止整个实验
- **`.env`**: `LLM_MODEL` 从 `deepseek-v4-pro-202606` 切换为 `deepseek-v4-flash`（更快更稳定）

### 效果
| 场景 | 修改前 | 修改后 |
|------|--------|--------|
| Phase 1 全超时 | 30s + 120s fallback + 3×60s 重试 + 120s fallback = **~450s** | **上限 45s 后立即退出** |
| Phase 2 超时 | 3×60s + 120s fallback = **~300s** | **60s 后立即退出** |

---

## v0.21.1 (2026-07-05) — 分段验证工具 ✅ 已实施

### 动机
- 收敛性实验每次 10+ 分钟全流程重跑，改一个 Agent 也要等全部步骤
- 需要改哪段验哪段的能力，节省 70-90% 验证时间

### 新增文件
- **`backend/app/strategies/prosperity/tools/checkpoint.py`** — CheckpointStore 类，管道中间状态 YAML 持久化
  - `save(step, **kwargs)` / `load(step)` / `load_deepcopy(step)` 
  - `missing_dependencies(step)` / `all_checkpoints_exist()` / `list_checkpoints()`
- **`scripts/segmented_verify.py`** — 分段验证 CLI，支持 record + replay
  - `--record`：全流程跑一次，拦截 Tavily + counter query LLM 调用并缓存，每步后存 checkpoint
  - `--step {hypothesize|verify|counter|screening|report} --runs N`：从 checkpoint 加载上游数据，仅重放目标 Agent N 次，mock 磁盘/DB 写入，对比稳定性
  - `--all`：一键验证全部 5 段

### 设计特点
- **Record**: 逐步执行 pipeline + 拦截 Tavily（`_tavily_cache.yaml`）+ 拦截 counter query LLM（`_counter_queries_cache.yaml`）
- **Replay**: 从缓存回放外部依赖（零 Tavily 调用），从 checkpoint 注入上游数据，仅重放目标 Agent 的 LLM 调用
- **Mock**: DB session + wiki 文件写入全部 mock，不污染生产数据
- **对比**: 5 个步骤各有专用指标提取函数 + `compare_metrics()` 差异检测
- **时间节省**: hypothesize ~80%, verify ~70%, counter ~90%, screening ~80%, report ~90%

### 用法
```bash
python scripts/segmented_verify.py --industry 人工智能 --record --force
python scripts/segmented_verify.py --industry 人工智能 --step verify --runs 3
python scripts/segmented_verify.py --industry 人工智能 --all --runs 3
```

### 改动文件
- `checkpoint.py` (新), `segmented_verify.py` (新), CHANGELOG.md

---

## v0.21.0 (2026-07-05) — P1 HypothesizeAgent 两阶段稳定性增强 ✅ 已实施

### 背景
- P0 修复 VerifyAgent 后，收敛性实验揭示第二大波动源：HypothesizeAgent 单次 LLM 调用产出 12≠14 条假设
- 根因：LLM 一次调用同时产出"树结构"和"叶子内容"，结构+内容耦合放大随机性
- 设计策略：两阶段分离 — Phase 1 3 轮投票定骨架 → Phase 2 1 轮强约束填充

### 设计 Spec
- `docs/specs/2026-07-05-prosperity-stability-p1-hypothesize.md` — P1 HypothesizeAgent 两阶段 Spec
- `docs/plans/2026-07-05-prosperity-stability-p1-hypothesize.md` — 实施计划

### 实施变更

#### Phase 1: 骨架生成（3 轮投票）
- 极简 prompt（4 字段 vs 当前 12 字段）→ 短 prompt 更高稳定性
- ID + title 双重匹配投票 → 防止同 ID 不同概念
- ≥2/3 规则保留假设 → 既过滤噪音又保留共识
- 链完整性回填 → 防止投票破坏因果链
- 三轮全分歧降级兜底 → 取第一轮

#### Phase 2: 内容填充（1 轮强约束）
- 骨架文本"不可增删改"约束 → 防止 LLM 创造性破坏
- 程序化校验（ID 集合 + derives_from 比对）+ 最多 2 次重试
- 仅 1 轮（下游 VerifyAgent 会覆盖 sentiment/confidence/sources）

### 改动文件
- `rules/prosperity/prompts/hypothesize_phase1_prompt.md` — **新建** Phase 1 骨架 prompt (~45 行)
- `rules/prosperity/prompts/hypothesize_phase2_prompt.md` — **新建** Phase 2 填充 prompt (~68 行)
- `agents/hypothesize_agent.py` — 重构为两阶段架构，新增 8 个方法，净增 ~100 行
- `core/config.py` / `.env` / `.env.example` — 新增 PROSPERITY_HYPOTHESIZE_ROUNDS / PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT
- `tests/test_hypothesize_agent.py` — **新建** 21 个单元测试（投票/回填/校验/降级）

### 边界
- **仅 HypothesizeAgent**（不改 coordinator 调用接口）
- 下游零影响：`form_hypotheses()` 返回格式不变，字段值域不变
- LLM 调用: 1× → 4×（Phase 1 并行 3 + Phase 2 串行 1），耗时 +50%
- 配置开关：`PROSPERITY_HYPOTHESIZE_ROUNDS=3`（可降级为 1 轮）
- `tests/test_hypothesize_agent.py` — **新建** 单元测试 + 集成测试
- `docs/specs/2026-07-05-prosperity-stability-p1-hypothesize.md` — **新建**
- `docs/plans/2026-07-05-prosperity-stability-p1-hypothesize.md` — **新建**
- `pyproject.toml` / `CHANGELOG.md` — 版本号

### 不受影响
- `coordinator.py`, `verify_agent.py`, `counter_agent.py`, `report_agent.py`
- `screening_agent.py`, `search_agent.py`, `learning_agent.py`, `track_agent.py`
- `tools/*`, 前端, 龟龟策略

---

## v0.20.0 (2026-07-05) — P0 VerifyAgent 多轮投票稳定性增强

### 背景
- 收敛性实验（`data/prosperity/raw/人工智能/convergence_report.md`）证实：temperature=0 下 3 次运行仍有 42 处差异，股池 ±40%，信号 ±18%
- 根因：VerifyAgent LLM 单次调用的 Q1/Q2/Q3/sentiment 输出不稳定（60% 差异来源）
- 设计策略：Self-Consistency — 3 轮并行 LLM 调用 → 字段级聚合

### 设计 Spec
- `docs/specs/2026-07-05-prosperity-stability-p0.md` — P0 稳定性增强 Spec
- `docs/plans/2026-07-05-prosperity-stability-p0.md` — 实施计划

### 核心变更

#### Layer 1: verify_prompt.md 输出格式重写
- Q1: `source_count: int` → `supporting_source_indices: [int]`（LLM 输出信源编号数组，代码做交集计数）
- Q3: `counter_conflict: "yes"/"no"` → `counter_conflict_score: 0/1/2/3`（分级取代二元，消除随机 flip）
- 新增：sentiment 字段输出（3 轮众数，写入 `verified_sentiment`）

#### Layer 2: verify_agent.py 3 轮并行 + 字段级聚合
- 新增 `_call_verify_llm()`: 独立 LLM 调用方法（含超时重试）
- 新增 `_aggregate_rounds()`: 字段级聚合逻辑
  - Q1: 3 轮交集 → source_count
  - Q2: 3 轮众数 → data_alignment
  - Q3: 3 轮 MAX，≥2 → counter_conflict=yes
  - sentiment: 3 轮众数 → verified_sentiment
- 新增 `_parse_verification_raw()`: 纯 JSON 解析（不含合成）
- 修改 `_verify_chain_with_llm()`: 单次 LLM → ThreadPoolExecutor 3 轮并行
- 修改 `_parse_verification_result()`: 兼容新旧两种输入格式
- `_synthesize_status()` / `_synthesize_confidence()`: 规则不变

### 边界
- **仅 VerifyAgent**（Plan A），CounterAgent 不改
- 下游零影响：status/sentiment 值域不变，接口不变
- LLM 调用: 1× → 3×（并行，耗时 ≈1×），成本 +0.02 元/次

### 改动文件
- `rules/prosperity/prompts/verify_prompt.md` — 输出格式重写 (~30 行)
- `agents/verify_agent.py` — 3 轮并行 + 聚合 + 兼容 (~150 行)
- `tests/test_prosperity_coordinator.py` — 新增集成测试 (~80 行)
- `docs/specs/2026-07-05-prosperity-stability-p0.md` — **新建**
- `docs/plans/2026-07-05-prosperity-stability-p0.md` — **新建**
- `docs/specs/2026-06-29-prosperity-strategy-design.md` — §2.3 增强备注
- `config.py` / `pyproject.toml` / `CHANGELOG.md` — 版本号

### 不受影响
- `counter_agent.py`, `coordinator.py`, `report_agent.py`, `hypothesize_agent.py`
- `screening_agent.py`, `search_agent.py`, `learning_agent.py`, `track_agent.py`
- `tools/*`, 前端, 龟龟策略

---

## v0.19.1 (2026-07-04) — P0 wiki 锚定 + P1 搜索防覆盖

### 背景
- Brainstorming 诊断发现 VerifyAgent **完全没吃到 wiki 历史上下文**，而 HypothesizeAgent 吃到了
- 同一日两次运行互相覆盖搜索结果文件（文件名只有日期，无 session_id）

### 变更

#### P0: VerifyAgent wiki 历史锚定
- **verify_prompt.md**：新增 `{history_text}` 占位符（「行业历史背景」章节，位于「上一轮验证摘要」之后）
- **verify_agent.py**：
  - 新增 `_build_history_context()` — 与 HypothesizeAgent 同源的 wiki 锚定文本构建
  - `verify()` 中预构建 `history_text`，传入 `_verify_chain_with_llm()`
  - `_verify_chain_with_llm()` 新增 `history_text` 参数（默认空字符串，向后兼容）

#### P1: 搜索文件名加 session_id
- **search_agent.py**：文件名格式从 `01_search_{date}.yaml` → `01_search_{date}_s{session_id}.yaml`
- 同一日内多次运行不再互相覆盖搜索结果

### 测试
- **179/179** 全部通过（零回归）

---

## v0.19.0 (2026-07-04) — LLM 确定性验证 + 纯度分去 LLM 化

### 背景
- Brainstorming 诊断发现两个 P0 稳定性问题：
  1. **验证结果跳动**：同一行业两次跑，confirmed ↔ partial 随机切换
  2. **纯度分跳动**：寒武纪 1% → 25%，LLM 业务线匹配结果不可复现
- 根因：全链路 LLM 非确定性级联放大（Tavily × 2 + LLM × 7~15 次）
- 核心策略：压缩 LLM 自由度 — 从「全局判断者」降级为「信息提取者」

### 设计 Spec
- `docs/specs/2026-07-04-llm-deterministic-verification.md` — 完整设计文档

### 变更

#### Layer 1: VerifyAgent 输出原子化
- **verify_prompt.md**：输出格式去 `status` / `confidence`，新增 `source_count` / `data_alignment` / `counter_conflict` 三个事实字段
  - Q1 source_count: 独立信源数量（计数判断，极低方差）
  - Q2 data_alignment: Tushare 数据方向对齐（方向判断，低方差）
  - Q3 counter_conflict: 反例直接冲突（二元判断，极低方差）
- **verify_agent.py**：新增两个确定性合成函数
  - `_synthesize_status()`: 3 个中间变量 → status（16 种组合全覆盖）
  - `_synthesize_confidence()`: 3 个中间变量 → confidence（high/medium/low）
  - `_parse_verification_result()` 解析后自动回填 status + confidence

#### Layer 2: 纯度分去 LLM 化
- **purity_scorer.py**：
  - `match_business_to_l3()` 改为**确定性关键词匹配**为主（零 LLM 调用）
  - 新增 `_extract_l3_keywords()`: 从 L3 investment_implication 动态提取关键词（停用词过滤 + 滑动窗口）
  - LLM 匹配降级为回退（仅关键词语法零匹配时触发）
  - 新增 `_llm_match_fallback()`: 原 LLM 匹配逻辑迁移

### 测试
- 新增 `TestV019DeterministicVerification`: 16 个 status 合成组合 + 确定性验证
- 新增 `TestV019DeterministicPurity`: 8 个关键词提取/匹配/确定性测试
- **179/179** 全部通过 (152 → 179, +27 新增, 零回归)

### 改动文件
- `rules/prosperity/prompts/verify_prompt.md` — 输出格式重写 (~40 行变更)
- `agents/verify_agent.py` — +`_synthesize_status` + `_synthesize_confidence` + 解析回填 (~+70 行)
- `tools/purity_scorer.py` — 去 LLM 化，关键词提取为主 (~+120 行)
- `tests/test_prosperity_coordinator.py` — +2 测试类 27 测试 (~+140 行)
- `config.py` — 版本 0.18.6 → 0.19.0
- `pyproject.toml` — 版本 0.10.0 → 0.11.0
- `docs/specs/2026-07-04-llm-deterministic-verification.md` — 新建设计 Spec

---

## v0.18.9 (2026-07-03) — Pipeline 输出修复 + LLM 超时增强

### 修复
- **Step 编号修正**: coordinator.py 搜索/假设/report 步标签从 `1/5`、`2/5`、`5/5` 改为 `1/6`、`2/6`、`6/6`（与新增 CounterAgent 后的 6 步总数一致）
- **临时脚本字段名**: `_run_ai_temp.py` 中 `total_signal` → `signal_strength`（匹配 report_agent 实际返回字段）
- **LLM 超时耐受**: verify_agent timeout 120→180s，counter_agent timeout 60→120s，各加一次重试

---

## v0.18.8 (2026-07-03) — CounterAgent 去极化 + VerifyAgent sentiment 保留修复

### 背景
- Brainstorming 全链路分析发现 **VerifyAgent 合并时丢弃了 sentiment 字段**，导致 ReportAgent 全部按 neutral 计算
  - AI 行业证据：信号 2.86 → 0.65，评级「景气」→「弱景气」
- 同时发现 CounterAgent 的极性规则（positive+disputed→切 / negative+disputed→保活）在逻辑上是错误的：
  - 被证伪的前提→下游不可达，不应因"方向对我有利"而保活
  - 真正的正向信号应来自正向假设的 confirmed，不来自错误推理的间接利好
  - 实际数据中 HypothesizeAgent 极少产出 negative 假设（AI 行业 0/12）

### Spec/Plan 更新
- **Spec v0.12.3** (`docs/specs/2026-06-29-prosperity-strategy-design.md`):
  - §2.3: VerifyAgent 字段保留规则（sentiment/causality/causality_note）
  - §2.4: CounterAgent 去极性化 → 纯机械三遍扫描（DISPUTED→OVERTURNED→级联 UNREACHABLE，不区分 polarity）
  - 新增设计决策 #10（去极化理由）+ #11（sentiment 保留理由）
- **Plan v1.1** (`docs/plans/2026-07-03-prosperity-cascade-fix.md`):
  - Layer 1 新增：VerifyAgent sentiment 保留修复
  - Layer 2 改为：CounterAgent 级联去极性化
  - 状态机/流转图/测试计划同步更新

### 代码变更（待实施）
- `verify_agent.py` L447-449：保留字段加 `"sentiment"`, `"causality_strength"`, `"causality_note"`（+3 行）
- `counter_agent.py` `_build_cascade_prompt()`：去掉极性规则，改为三遍扫描
- `counter_agent.py` `_hardcoded_polarity_cascade()` → `_hardcoded_cascade()`：去掉 polarity 判断

---

## v0.18.7 (2026-07-03) — CounterAgent LLM debug 输出增强

### CounterAgent 解析失败诊断增强
- `_llm_cascade()` 解析失败时：
  - 日志增加 `prompt_len`、`content_len`、`finish_reason` 信息
  - 保存 `_debug_counter_output.json`（含 prompt_preview、raw_output、finish_reason）
- 新增 `_save_debug_output()` 方法（沿用 HypothesizeAgent 的 debug 模式）
- Next：下次跑任意行业时捕获 LLM 原始 JSON，根据实际格式修解析器

---

## v0.18.6 (2026-07-03) — CounterAgent 语义级联复原 + 链结构完整性修复

### 背景
- Brainstorming 会话发现 3 个结构化 bug：
  1. **P0**: Chain A 的 H3-1 被错误标记 unreachable — `_cascade_safety_net` 多项式检查 disputed 不看 sentiment，负向风险被否认反被切
  2. **P1**: Chain C 终止于 L1 无 L2/L3 — HypothesizePrompt 只约束数量不约束结构
  3. **P2**: SIGNAL_MAP 5/9 覆盖 → 缺失组合信号零化
- 根因：CounterAgent（Spec §2.4）被删除后，LLM 五维语义被硬编码剥夺

### 实现

**Layer 1: CounterAgent 语义级联复原（P0 修复）**
- 新建 `counter_agent.py`（~280 行）：LLM 语义级联裁决 + sentiment 修正（方案 B）
  - 读五维语义（status/sentiment/reason/causality/corrected_statement）
  - 极性感知级联：positive+disputed→切 / negative+disputed→保活
  - 基于 `corrected_statement` 修正 sentiment（下游零感知）
  - 三级降级：LLM → 硬编码极性规则 → 原 `_cascade_safety_net`
- `coordinator.py`：PIPELINE_STEPS 新增 `"counter"`，Phase 3.5 插入
- `verify_agent.py`：新增 `skip_cascade` 参数，避免双重级联

**Layer 2: 链结构完整性约束（P1 修复）**
- `hypothesize_prompt.md`：新增规则 8 — 每条 L1 必须有 L2，L2 必须有 L3
- `hypothesize_agent.py`：新增 `_validate_chain_completeness()` 方法（警告不阻断）

**Layer 3: SIGNAL_MAP 补全（P2 修复）**
- `report_agent.py`：SIGNAL_MAP 从 5 项扩展到 10 项全覆盖
- 移除 `unverified/partial → 0.5×` 双重折扣（已内嵌）
- 评级排除 `overturned` 状态

### 核心状态机修正
```
修复前: DISPUTED → _cascade_safety_net → 无差别切下游
修复后: DISPUTED → CounterAgent LLM → positive→overturned→切 / negative→保活
```

### 改动文件
- `agents/counter_agent.py` — **新建**
- `coordinator.py` — PIPELINE_STEPS + Phase 3.5 + `_run_counter_agent()`
- `verify_agent.py` — `skip_cascade` 参数
- `hypothesize_prompt.md` — 规则 8 链结构完整性
- `hypothesize_agent.py` — `_validate_chain_completeness()`
- `report_agent.py` — SIGNAL_MAP 10 种全覆盖 + 移除双重折扣 + 排除 overturned
- `config.py` — 版本 0.18.5 → 0.18.6
- `pyproject.toml` — 版本 0.9.9 → 0.10.0
- `docs/plans/2026-07-03-prosperity-cascade-fix.md` — 实施计划

### 测试: 待验证

---

## v0.18.5 (2026-07-02) — Learning Agent 产业学习层实现

### 背景
- LLM 三处波动源（HypothesizeAgent/VerifyAgent/ScreeningAgent）从上游往下游级联放大
- 根因：Pipeline 缺少结构化知识背景（Search → Hypothesize 跳过了"学习"步骤）
- Brainstorming → Spec 设计 → 本次实现

### 实现
- **LearningAgent** (`learning_agent.py`): 从搜索素材构建产业图谱 7 节（价值链/供需/技术路径/政策/瓶颈/跟踪指标/不确定区域）
- **Prompt 模板**: `rules/prosperity/prompts/learning_prompt.md` — 独立文件，便于调优
- **Coordinator 集成**: Phase 1.5（Search → **Learn** → Hypothesize），静默执行
  - 首次研究 → LLM 生成产业图谱 → 写入 `wiki/industries/{name}.md` 的 `## 产业图谱` 节
  - 后续研究 → 检测已存在图谱 → 自动跳过
- **下游零改动**: HypothesizeAgent 的 `_load_history()` 自动消费 wiki 页面中的产业图谱

### 改动文件
- `backend/app/strategies/prosperity/agents/learning_agent.py` — **新增**
- `backend/rules/prosperity/prompts/learning_prompt.md` — **新增**
- `backend/app/strategies/prosperity/coordinator.py` — 集成 `_run_learning_agent()`
- `backend/app/core/config.py` — 版本 0.18.4 → 0.18.5
- `backend/pyproject.toml` — 版本 0.9.8 → 0.9.9
- `backend/tests/test_prosperity_coordinator.py` — +7 测试
- `docs/specs/2026-07-02-industry-learning-agent.md` — 设计 Spec

### 测试: 152/152 ✅

---

## v0.18.4 (2026-07-02) — 方向分作为股池第二参考指标展示

### 问题
- 方向分在 `screening_agent.py` Stage 1 已算出来，并参与 tuple sort 打破平局，但 **最终报告表格里没有显示**
- 用户无法直观解释：为什么 purity=0 但方向匹配度高的股票（如哈焊华通）排在 purity=0 的其他股票前面
- `score_detail` 里只写了 `purity` / `direction_annotation` / `finance_reference`，没有 `direction_score`

### 改进
- `screening_agent.py`: `score_detail` 新增 `direction_score` 字段（0.00~1.00，保留 3 位小数），与顶层 `direction_score` 保持一致
- `report_agent.py`: 股池表格新增**方向分**列，格式化为 `0.00~1.00`
- 最终表格列顺序：排名 | 股票 | 纯度分 | 方向分 | ROE | 毛利率 | 营收增速 | 匹配方向

### 设计原则
- **方向分不混入 `final_score`**：排名核心仍是物理纯度（相关业务收入占比），方向分只作为独立参考列展示
- 这样既保留 v0.18.3 的 tuple sort 意图，又让用户一眼看到「搜索证据强度」这一第二参考维度

### 效果
- 哈焊华通：纯度 15.29% 排第 2，方向分 0.95 → 搜索证据强
- 联创光电：纯度 5.05% 排第 6，方向分 0.40 → 证据弱，排名靠后合理

### 改动文件
- `backend/app/core/config.py`
- `backend/app/strategies/prosperity/agents/screening_agent.py`
- `backend/app/strategies/prosperity/agents/report_agent.py`
- `backend/tests/test_prosperity_coordinator.py`

### 测试
- 145/145 pytest ✅

---

## v0.18.3 (2026-07-02) — 选股信号质量感知融合

### 问题
- **信息割裂**: ScreeningAgent 的 Stage 1（方向匹配，有搜索上下文）与 Stage 2（纯度打分，无搜索上下文）不共享素材 → 哈焊华通等股票方向分高但纯度分为 0
- **概念入口过松**: 雪人集团（制冷）、王子新材（包装）等非相关股票通过搜索引擎自建概念进入股池
- **H3-3 规避方向无负向信号**: 纯概念炒作匹配到规避方向后未在排名中惩罚
- **零区随机**: purity=0 的 22 只股票（65%）随机排列，方向置信度被丢弃

### 改进
- **概念构建加相关性门** (`concept_builder.py`): LLM 提取 prompt 新增 `relevant` 字段，`_cross_validate` 后过滤 `relevant: false` 的股票
- **L3 极性标注** (`screening_agent.py`): 新增 `_detect_polarity()`，prompt 为 L3 方向加 `[✅ 推荐方向]` / `[⚠️ 规避方向]` tag；匹配到规避方向 score 降至 0.0~0.2
- **搜索上下文注入纯度打分** (`purity_scorer.py` + `screening_agent.py`): 新增 `_build_search_context_for_purity()`，从搜索素材中提取公司上下文注入 purity prompt；`screen()` 将 `search_result` 透传至 `_compute_purity()`
- **Tuple sort 排名 + 硬过滤** (`screening_agent.py`): `sort(key=(purity_score, direction_score))`；移除 `matched_l3=null + purity=0` 的完全无关股票

### 效果（可控核聚变）
- 排名 1~12: 纯度 > 0 的股票不受影响
- 排名 13~22: purity=0 但 direction > 0 的股票按方向分有序排列（如哈焊华通）
- 排名 23~34: 完全无关股票被硬过滤移除

### 改动文件
- `backend/app/strategies/prosperity/tools/concept_builder.py`
- `backend/app/strategies/prosperity/agents/screening_agent.py`
- `backend/app/strategies/prosperity/tools/purity_scorer.py`

---

## v0.18.2 (2026-07-02) — 方向匹配允许 null（不强制全覆盖）

### Bug
- LLM 方向匹配提示词强制"覆盖所有成分股" → 每只股票都被分配了一个 L3 方向
- 中钨高新(硬质合金)、王子新材(包装)、浙能电力(火电) 等明显不相关的股票被强行归类

### 修复
- `screening_agent.py` `_llm_direction_match()`: 
  - 新增规则「完全不匹配任何 L3 方向 → score: 0.0, matched_l3: null」
  - 输出示例增加 null 条目，提示词明确「不要强行给每只股票分配 L3 方向」
  - Stage 4 融合 `direction_annotation`: `"-"` → `"不匹配"`
- `purity_scorer.py` `match_business_to_l3()`: 输出示例同步增加 null 条目

### 改动文件
- `backend/app/strategies/prosperity/agents/screening_agent.py`
- `backend/app/strategies/prosperity/tools/purity_scorer.py`

---

## v0.18.1 (2026-07-02) — Bugfix: fina_indicator 字段名纠正

### Bug
- `tushare_client.get_fina_indicator()` 使用错误字段名：`revenue_yoy` / `net_profit_yoy`
- Tushare 正确字段名是 `or_yoy`(营业收入同比) / `netprofit_yoy`(归母净利同比)
- 免费层不认识错误字段名 → 静默忽略 → 34只股票 YAML 中 `revenue_yoy` / `net_profit_yoy` 全为 null
- **finance_score 的 70% 权重（营收增速+利润增速）实际用假值 0 计算百分位**

### 修复
- `tushare_client.py`: API fields 改正确 + `or_yoy→revenue_yoy` / `netprofit_yoy→net_profit_yoy` rename
- 下游代码（stock_screener/industry_metrics/report_agent）**零改动**，内部变量名不变

---

## v0.18.0 (2026-07-02) — 股池筛选：业务纯度排名

**v0.18.0 补丁 (2026-07-02)**：`fina_mainbz_vip`(5000积分) → `fina_mainbz`(500积分)，2000积分足够

### 问题
- **业务纯度盲区**：方向和财务分都看公司整体，不区分子业务。永鼎股份超导仅占营收 16%，但因光纤 AI 增速+卖房收益，财务分行业第一，LLM 方向分也被券商研报"光环效应"带高 → 排名虚高第一
- **一次性损益污染**：利润增速因子被卖房等非经常性收益污染（永鼎 ~2.5 亿卖房 → profit_yoy +226%）
- **动量绝对值分档**：与营收增速/ROE 等其他因子的行业内百分位排名不一致，无区分度

### 设计
筛选阶段回答「跟投资方向多大关系」，不是「公司好不好」：
- **排名依据**：业务纯度分 = 相关业务收入 / 总收入（fina_mainbz_vip + LLM 匹配）
- **方向分**：降为标注（matched_l3），不参与排名
- **财务分**：保留 4 因子百分位（去动量），仅作为参考列展示
- **报告表格**：排名 | 股票 | 纯度分 | ROE | 毛利率 | 营收增速 | 匹配方向

### 新增
- `tools/purity_scorer.py` — 批量拉取 fina_mainbz_vip + LLM 业务线匹配 + 纯度分计算
- `tushare_client.py` — `get_fina_mainbz()` 方法
- 7 个新测试（TestV018PurityScreening）

### 修改
- `stock_screener.py` — 移除动量因子，权重重分配（营收35/利润35/ROE20/质量10），新增 `raw_indicators` 输出
- `screening_agent.py` — 4 阶段流程：方向标注 → 纯度打分 → 财务参考 → 纯度排名
- `report_agent.py` — 股池表格列改为纯度分/ROE/毛利率/营收增速
- `config.py` — 删除 `PROSPERITY_DIRECTION_WEIGHT` / `PROSPERITY_FINANCE_WEIGHT`
- `.env` — 清理旧权重配置

### 预期效果（可控核聚变）
| 旧排名 | 股票 | 旧总分 | → | 新排名 | 纯度分 |
|--------|------|--------|---|--------|--------|
| 1 | 永鼎股份 | 81.8 | → | 4+ | 0.16 |
| 3 | 西部超导 | 64.3 | → | 1 | ~0.55 |
| 4 | 国光电气 | 58.5 | → | 2 | ~0.40 |
| 2 | 合锻智能 | 72.9 | → | 3 | ~0.30 |

### 改动文件
- `backend/app/services/tushare_client.py` — +get_fina_mainbz()
- `backend/app/strategies/prosperity/tools/purity_scorer.py` — 新文件
- `backend/app/strategies/prosperity/tools/stock_screener.py` — 去动量/调权重
- `backend/app/strategies/prosperity/agents/screening_agent.py` — 融合改纯度排名
- `backend/app/strategies/prosperity/agents/report_agent.py` — 表格列更新
- `backend/app/core/config.py` — 版本号 + 删旧权重
- `backend/.env` — 清理旧权重
- `backend/tests/test_prosperity_coordinator.py` — 更新/新增测试

## v0.17.4 (2026-07-01) — regenerate_screening.py 报告数据源修复

### Bug: 独立刷新脚本生成报告陈述/推理链为空 + Mermaid 图节点 ID 不匹配

- **根因 1**: `load_verified_hypotheses()` 只从 DB 查询，DB `Hypothesis` 表没有 `statement`/`reasoning` 列 → 报告全部为空
- **根因 2**: 节点 ID 用 DB 自增 ID（`H0-50`），但 `derives_from` 存的 wiki ID（`H0-1`）→ Mermaid 箭头指向不存在的节点
- **根因 3**: `for title, db in db_data.items()` 中循环变量 `db` 覆盖了外层 session `db` → `db.close()` AttributeError

### 修复
- `load_verified_hypotheses()` 新增三步合并:
  1. DB 获取验证状态/置信度/因果强度
  2. 解析 `wiki/hypotheses/{行业}-*.md` 获取陈述/推理链/wiki ID/上游/时间窗口/跟踪指标/投资含义
  3. 按标题匹配合并，mermaid 节点 ID 统一使用 wiki ID
- 循环变量 `db` → `d` 消除遮蔽

### 验证
- 可控核聚变: 12/12 条假设陈述/推理链完整，Mermaid 图 10 条箭头全部匹配，评级弱景气(1.20)

### 改动文件
- `scripts/regenerate_screening.py` — load_verified_hypotheses() 重写 (+~90行)

## v0.17.3 (2026-07-01) — Agent max_tokens 统一 + 股池全量展示 + 独立刷新脚本

### max_tokens 全局统一
- 6 个 Agent 各自写死 max_tokens（500/1024/4096/8192/8000），config.py 的 `LLM_MAX_TOKENS=32768` 从未被使用
- **修复**: 全部改为 `settings.LLM_MAX_TOKENS`，以后改 `.env` 即可全局生效
- **影响**: screening_agent 方向匹配从 4096→32768，34 只成分股 LLM 输出不再被截断

### 股池全量展示
- report_agent 写死 `[:10]` 只展示 Top 10 → 改为全量 `stock_pool`
- 标题 `Top 10` → `共 {N} 只`

### 新增独立刷新脚本
- `scripts/regenerate_screening.py [行业名]`：加载已有 search + verified hypotheses，单独重跑 Screening → Report
- 不用跑全流程即可刷新股池和报告
- 可控核聚变验证：34 只全部成功匹配 L3 方向 + 财务分正常化

### 改动文件
- `screening_agent.py`, `hypothesize_agent.py`, `verify_agent.py`(2处), `track_agent.py`, `concept_builder.py` — max_tokens → settings.LLM_MAX_TOKENS
- `report_agent.py` — Top 10 → 全量
- 新增 `scripts/regenerate_screening.py`

## v0.17.2 (2026-07-01) — 财务分归一化 Bug 修复

### Bug: 财务分被错误除以 100 → 50/50 融合变成 99/1

- **根因**: `screening_agent.py` 第 90 行 `s.get("score_total", 0) / 100.0` 假设 `score_total` 是 0~100，但 `stock_screener.py` 实际返回 0~1（权重 sum=1.0，每个子因子 0~1）
- **影响**: 财务分被压 100 倍（0.5→0.005），融合中几乎不做贡献，所有股票总分差异仅由 LLM 方向契合度决定
- **修复**: 
  - `screening_agent.py`: `/ 100.0` 删除，直接用 `s.get("score_total", 0)`
  - `stock_screener.py`: `min(total, 100)` → `round(total, 4)`（total 天然 0~1，钳顶 100 无意义）
- **效果**: 中等股票总分从 ~25 → ~50，财务维度重新参与排名
- **测试**: 138/138 ✅

## v0.17.1 (2026-07-01) — Bug Fixes

### Watchlist 巡检三项 Bug 修复 + Seed Run 验证

**Bug 1** — hypothesize_agent.py f-string `{` `}` 未转义 → pipeline 崩溃
- L3 示例 `key_indicators: [{"name": ...}]` 在 f-string 中被解释为 format specifier → ValueError
- 修复: 第 227 行 `{`→`{{`、`}`→`}}`

**Bug 2** — `_filter_due` 只看时间不检查 `last_value` → 永远 0 巡检
- 旧 watchlist 有 `last_updated`（extract_tracking 写入当天）但 `last_value: None`
- frequency=monthly(30天) → `0 >= 30` = False → 不认为到期 → 全部跳过
- 修复: `last_value is None && last_value_text is empty` → 视为首次巡检

**Bug 3** — extract_tracking 覆盖 pre_check 灌入的 `last_value`
- pipeline 末尾 extract_tracking 全量重写 watchlist → 把刚巡检来的值盖回 `None`
- 修复: 新增 `_merge_with_existing()` → 保留已有巡检值

### 改动: track_agent.py, hypothesize_agent.py | 测试: 138/138 ✅ | pyproject: v0.9.3

## v0.17.0 (2026-07-01) — Implemented

### Watchlist 巡检系统 — 全自动研究触发器

**动机**: watchlist 是"备忘录"而非"巡检系统"——`check_watchlist()` 只判断日期到期，不获取指标数据，`last_value` 永远为 `None`。升级为全自动研究触发器（路径 C）。

**设计 Spec**: `docs/specs/2026-07-01-watchlist-inspection-system.md`

**核心变更**:

1. **HypothesizeAgent: key_indicators string[] → object[]** — 每个指标新增 `name`/`frequency`/`search_query`/`expected_direction` 四个字段，LLM 一次性生成检索方向
2. **TrackAgent.check_industry()** — 新增行业级巡检入口：Tavily 搜索 → LLM 提取值 → 触发判定 → 更新 YAML + 同步 SQLite
3. **触发判定规则** — 数值变化超 20% 阈值 OR 方向反转 → 标记 triggered
4. **跟踪范围过滤** — 只跟踪 confirmed/partial/unverified/disputed，排除 unreachable/overturned
5. **YAML 权威源 + SQLite 查询缓存** — 单向同步，消除双写不一致
6. **coordinator.py pre_check** — pipeline 开头（search 前）自动调用 TrackAgent.check_industry()

**数据库变更**:
- `tracking_items` 表: +indicator_name, +frequency, +last_value, +last_value_text, +search_query, +expected_direction, +history_json（7 列）
- 新增 `migrate_v4()` 迁移函数

**改动文件**: hypothesize_agent.py, track_agent.py(重写), coordinator.py, models.py, report_agent.py
**新增文件**: docs/specs/2026-07-01-watchlist-inspection-system.md
**测试**: 138/138 ✅
**版本**: v0.16.0 → v0.17.0 | pyproject: v0.9.1 → v0.9.2

## v0.16.0 (2026-07-01) — Implemented

### 高景气策略核心增强

**动机**: 投资决策质量缺陷分析揭示了两个致命缺陷——①验证环节是"伪验证"（纯代码 3 条 if-else，LLM 从未参与）、②股池与推理链完全脱节（L3 选股方向未用到评分中）。根源是整条 6 Agent 管道只有 HypothesizeAgent 用到了 LLM。

**设计 Spec**: `docs/specs/2026-07-01-prosperity-strategy-v16-enhancement.md`

**核心变更**:

1. **VerifyAgent LLM 完全重构** — LLM 串行验证推理链（Tushare 数据 + 搜索素材 + 反例搜索 → status/reason/corrected/causality_strength），替代 3 条 if-else 伪验证
2. **新增 ScreeningAgent** — LLM 方向匹配（基于 L3 investment_implication） + 代码财务打分 50/50 融合
3. **HypothesizeAgent +sentiment** — positive/negative/neutral 方向标注
4. **ReportAgent 评级重构** — 从计数改为加权信号聚合（sentiment × 层级权重 × causality 折扣）
5. **VerifyAgent 反例搜索** — LLM 自动生成反例搜索词 → Tavily 执行 → 喂入验证
6. **CounterAgent 移除** — 合并进 VerifyAgent，管道 6→5 Agent

**管道**: Search → Hypothesize → Verify → Screening → Report → Track（5 Agent）
**LLM 调用**: 1 次 → (推理链条数 + 2) 次

**数据库变更**:
- `hypotheses` 表: +sentiment, +causality_strength, +causality_note
- `stock_pools` 表: +direction_score, +finance_score, +matched_l3, +matched_reason
- 新增 `migrate_v3()` 迁移函数

**配置新增**: `PROSPERITY_DIRECTION_WEIGHT`, `PROSPERITY_FINANCE_WEIGHT` (默认各 0.5)

**改动文件**: coordinator.py, verify_agent.py(重写), screening_agent.py(新增), hypothesize_agent.py, report_agent.py, api.py, models.py, config.py, .env, test_prosperity_coordinator.py
**删除文件**: agents/counter_agent.py
**测试**: 35/35 prosperity ✅ + 37/37 spec compliance ✅
**版本**: v0.15.0 → v0.16.0 | pyproject: v0.9.0 → v0.9.1

### DISPUTED/OVERTURNED 语义精化 (2026-07-01)

**问题**: 旧设计中 disputed 语义模糊（同时表示"证据不足"和"已证伪"），多个活跃文件中级联规则不一致。

**新语义**:
- `disputed` → **证据不足**，不触发级联（不标记下游 UNREACHABLE）
- `overturned` → **已证伪**，触发下游 UNREACHABLE

**文档修正** (8 文件):
- `data/prosperity/SCHEMA.md` — 补 OVERTURNED 状态、区分反推语义、修正 emoji
- `docs/CONTEXT.md` — 级联规则 DISPUTED → OVERTURNED
- `docs/specs/2026-07-01-prosperity-strategy-v16-enhancement.md` — 状态枚举 + 级联规则 + CounterAgent 移除说明更新
- wiki/ + tracking/ + index.md + log.md — 生成物，下次 pipeline 自动更新
- `docs/specs/2026-06-29-*` — 历史 snapshot，不改

## v0.15.0 (2026-07-01) — Implemented

### 代理下线 + AKShare 替换为搜索引擎自建概念板块

**动机**: 代理服务器到期（2026-07-02），2000 积分直连已稳定。AKShare 作为概念板块兜底不稳定（爬虫），替换为搜索引擎自建方案。

**改动**:

#### 1. Tushare 客户端精简 (`tushare_client.py`)
- 删除代理两阶段重试逻辑（Stage 0 直连 → Stage 1 代理），简化为单次直连 + 重试
- 删除 `_PROXY_RATE_INTERVAL`、`_class_proxy_determined`、`_class_using_proxy`、`_proxy_url` 等代理状态
- `call()` 从 75 行降到 30 行，`__init__` 从 14 行降到 5 行
- 净减 ~100 行

#### 2. 搜索引擎自建概念板块 (`tools/concept_builder.py` — 新增)
- Tavily 搜索 → LLM 提取股票列表 → Tushare stock_basic 交叉验证 → YAML 缓存
- 零外部依赖，支持任何自定义概念（可控核聚变/固态电池/低空经济等）
- 首次查询 ~5s（搜索+LLM），后续缓存秒出
- 缓存目录: `data/prosperity/concept_boards/{theme}.yaml`

#### 3. 信源链路更新 (`industry_metrics.py`)
- 信源5: AKShare → `concept_builder.search_concept_stocks()`
- 删除 `_akshare_code_to_ts_code()` 函数
- docstring 从「AKShare 概念板块成分股（完全独立，无 token）」→「搜索引擎自建概念板块（Tavily + LLM + stock_basic 交叉验证，终极兜底）」
- batch_size: 10 → 30（直连上限更高）

#### 4. 代理配置全量清理
- `config.py`: 删除 `TUSHARE_PROXY_URL`
- `.env`: 删除代理段（7 行）
- `pyproject.toml`: 删除 `akshare` 依赖

#### 5. 清理过时代理脚本（8 个文件）
- 删除 `scripts/test_ths_slow.py`, `test_ths_debug.py`, `test_ths_single.py`, `test_ths_one.py`, `test_ths_deep.py`, `test_ths_all.py`, `test_ths_concepts.py`, `test_ths_union.py`

#### 6. 测试
- T20: AKShare mock → concept_builder mock

**最终信源链路**:
```
get_industry_ts_codes("可控核聚变")
  ├── ① stock_basic.industry     → 0 (无此名)
  ├── ② index_classify SW2021    → 0 (无此名)
  ├── ③ concept_detail           → 0 (无权限/无此板块)
  ├── ④ ths_index → ths_member   → 0 (无权限/无此板块)
  └── ⑤ 搜索引擎自建             → ✅ (Tavily+LLM+stock_basic)
```

**改动文件**: tushare_client.py, industry_metrics.py, concept_builder.py(新增), config.py, .env, pyproject.toml, test_prosperity_coordinator.py, test_new_energy_pool.py
**删除文件**: 8 个 test_ths_*.py
**版本**: v0.14.7 → v0.15.0 | pyproject: v0.8.11 → v0.9.0

## v0.14.7 (2026-06-30)

### Wiki 增强第二阶段：验证锚定 + 索引修复

**背景**: Wiki 系统部分起作用（Search Agent URL 去重、HypothesizeAgent 历史锚定已生效），但 VerifyAgent 的 `_build_history_context()` 定义了却从未调用，验证环节是"盲"的。

**修复**:
- **VerifyAgent 历史锚定**: `verify()` 中构建 `previous_map`（title→上次状态），传入 `_verify_single()` 做 3 条锚定规则：
  1. 上次 CONFIRMED + 当前仍 CONFIRMED → 标注累积置信度
  2. 上次 CONFIRMED + 当前数据不支撑 → 拐点预警 DISPUTED
  3. 上次 DISPUTED/OVERTURNED → 标注连续存疑
- **wiki_indexer 索引修复**: `update_index()` 改为先按 category 分组再组内排序，消除重复分组标题

**不改动**: CounterAgent 的 wiki 历史接入——反推本质是内部逻辑一致性检查，历史对判断帮助有限，暂不接。

**改动文件**: verify_agent.py, wiki_indexer.py
**版本**: v0.14.6 → v0.14.7 | pyproject: v0.8.10 → v0.8.11

## v0.14.6 (2026-06-30)

### Tushare 代理限频修复 — 重试控频 + 空结果重试

**问题**: 代理限额 150次/分钟，但 `call()` 重试循环不走 `_rate_limit()`，3次重试在 3s 内连打代理可能超限。空结果（代理繁忙返回空 DataFrame）直接返回不重试。

**修复**:
- `call()` 每个 retry 前调用 `_rate_limit()`，重试不再突发打爆代理
- 空结果 `attempt < 1` 时重试一次（代理繁忙可能返回空 DataFrame）
- 移除 `_PROXY_RATE_INTERVAL` 的 "TEST-ONLY" 标记，正式化代理限频注释

**改动文件**: tushare_client.py
**版本**: v0.14.5 → v0.14.6 | pyproject: v0.8.9 → v0.8.10

## v0.14.5 (2026-06-30)

### 景气管道性能优化 — 批量 API + Progress 反馈

**诊断**: 景气管道 run_full_pipeline 跑 30 分钟无任何输出。根因三件套：
1. 每个 `TushareClient()` 新实例在必败直连上浪费 ~8s × N 次
2. `_fetch_batch_financials` 逐只调 API（200 只串行 = 5min+）
3. `run_full_pipeline` 零用户可见进度

**方案**:
- `tushare_client.py`: 类级别 `_class_using_proxy` / `_class_proxy_determined`，首次实例确定代理后所有后续实例跳过直连
- `industry_metrics.py`: `_fetch_batch_financials` 批量 API（逗号分隔 100 只/次，200 只 = 2 次调用 ~3s）；`_compute_acceleration` 复用缓存的 `_cached_fina_full` 不再二次拉取
- `coordinator.py`: `run_full_pipeline` 6 步均 `print` 时间戳 + 统计；`verify_agent` 拉数据/验证层级也输出进度
- `run_prosperity_ne.py`: logging 级别 INFO→WARNING 减少噪音，脚本输出时间戳

**改动文件**: tushare_client.py, industry_metrics.py, coordinator.py, verify_agent.py, run_prosperity_ne.py
**测试**: 133/133 ✅ | 版本: v0.14.4 → v0.14.5 | pyproject: v0.8.8 → v0.8.9

## v0.14.4 (2026-06-30)

### AKShare 概念板块兜底

**诊断**: 旧 token 直连 Tushare 下，"新能源"在信源①-④全部返回 0 只。原因是"新能源"是民间概念名，不在 Tushare stock_basic 105 个行业名或申万 L1/L2/L3 分类中。concept_detail 和 ths_index 旧 token 无权限。

**方案**: 信源⑤ — AKShare `stock_board_concept_cons_em("新能源")`，完全独立于 Tushare，无需任何 token。

**改动**:
- `industry_metrics.py`: 新增 `_akshare_code_to_ts_code()` 代码转换 + 信源 5 AKShare 概念板块兜底
- 测试新增 T20（AKShare 概念板块 mock + 代码格式转换验证）
- 版本: v0.8.7 → v0.8.8 / v0.14.3 → v0.14.4

**最终信源链路**:
```
get_industry_ts_codes("新能源")
  ├── ① stock_basic.industry     → 0 (无此名)
  ├── ② index_classify SW2021    → 0 (无此名)
  ├── ③ concept_detail           → 0 (无权限)
  ├── ④ ths_index → ths_member   → 0 (无权限)
  └── ⑤ AKShare concept_cons     → ✅ (免费/无token)
```

## v0.14.3 (2026-06-30)

### 概念股池多信源兜底

**动机**: `get_industry_ts_codes("新能源")` 返回 0 只股票。"新能源"是跨行业主题概念，不在标准行业分类（申万/Tushare stock_basic）中，导致 VerifyAgent 全链条 UNVERIFIED、评级错误落入兜底弱景气。

**方案**: 在现有两层匹配（`stock_basic.industry` + 申万 `index_classify`）之后追加两层概念兜底：
1. `concept_detail("新能源")` — Tushare 免费概念板块（0 积分）
2. `ths_index → ths_member` — 同花顺概念板块（6000 积分，通过 15000 积分代理访问）

**改动**:
- `tushare_client.py`: 新增 `get_concept_detail()`, `get_ths_index()`, `get_ths_member()` 三个方法
- `industry_metrics.py`: `get_industry_ts_codes()` 新增信源 3（concept_detail）和信源 4（同花顺概念）
- 测试新增 T17-T19（concept_detail 兜底 / 同花顺兜底 / 缓存跳过概念接口）

**测试**: 132 passed, 0 failed | 版本: v0.8.6 → v0.8.7 / v0.14.2 → v0.14.3

## v0.14.2 (2026-06-29)

### watchlist 拆分为每行业独立文件

**动机**: `watchlist.yaml` 随着行业增多会越来越长（当前 37 项/525行），当研究 ≥5 个行业时单文件难以维护。

**改动**:
- 数据文件从 `tracking/watchlist.yaml`（顶层 `{行业名: [指标列表]}`）拆为 `tracking/watchlist/{行业名}.yaml`（每行业一个文件）
- `_load_watchlist()` 改为遍历目录 `*.yaml`，文件名 stem 作为行业名，内容直接是 `[指标列表]`
- 新增 `_load_watchlist_legacy()` 保持对 v0.14.0/v0.14.1 旧格式的后向兼容
- `extract_tracking()` 写入目标从单个文件改为 `watchlist/{行业名}.yaml`
- `check_watchlist()` 逻辑不变（仍通过 `_load_watchlist` 获得 `{行业: [指标]}` dict）

**优势**:
- 单个行业文件独立可读，新增行业不需修改已有文件
- 内存表示 `{行业名: [指标列表]}` 不变，调用方零改动
- 完全后向兼容旧格式

**改动文件**: track_agent.py, test_prosperity_coordinator.py, watchlist.yaml→watchlist/电气设备.yaml
**测试**: 129/129 ✅

## v0.14.1 (2026-06-29)

### watchlist.yaml 按行业分组重构

**问题**: watchlist 所有行业指标混在扁平 `items` 列表，且 `_merge_indicators` 仅用指标名做 key，导致跨行业同名指标（如"营收增速"在半导体和电气设备）被错误合并。

**修复**:
- `_merge_indicators` key 从 `indicator` → `(indicator, industry)` 复合 key，修复跨行业误合并 bug
- `extract_tracking` 写入格式从 `{"items": [...]}` → `{行业名: [指标列表]}`，同行业替换不追加
- `_load_watchlist()` 新方法，兼容旧扁平格式自动迁移
- `check_watchlist` 遍历适配新格式，返回结果带 `_industry` 标注

**改动文件**: `track_agent.py`, `watchlist.yaml`（迁移 37条→1行业组）, `test_prosperity_coordinator.py`（+3条测试）
**测试**: 129/129 ✅ (126→129, +3 新增)
**版本**: v0.14.0 → v0.14.1 | pyproject.toml: v0.8.4 → v0.8.5

## v0.14.0 (2026-06-29)

### Wiki 智能增强 — 重复行业研究优化

**动机**: v0.13.2 暴露 wiki 系统架构问题 — 重复行业无冷却判断、搜索新旧混杂、仅 Hypothesize 读历史、评级行无限追加。

**方案**: 5 天冷却硬门控 + 全链历史锚定 + URL 去重新旧分流 + 评级行去重 + key_indicators 全量入 watchlist。

**关键决策**:
- `start_session(force=True)` 跳过冷却，CooldownError 异常通知调用方
- `IndustryHistory` 数据类 — Coordinator 预加载后逐级传入 6 Agent
- Search URL 去重 → 新结果 300 字 / 旧结果 100 字摘要
- 报告结构化截取 ~3000 字（L0-L3+股池，不含验证/反推）
- Verify/Counter 也注入历史上下文
- Track 全量假设 key_indicators 提取 + 按指标名合并去重
- 只取最近一次 session 历史假设
- 指标自动巡检触发逻辑本次不做（只铺管道）

**新增文件**: `industry_history.py`
**修改文件**: coordinator.py, search_agent.py, hypothesize_agent.py, verify_agent.py, counter_agent.py, report_agent.py, track_agent.py
**测试**: 23/23 prosperity ✅ | 126/126 全量 ✅ (118→126, +8 新增)
**版本**: v0.13.2 → v0.14.0 | pyproject.toml: v0.8.3 → v0.8.4

## v0.13.2 (2026-06-29)

### B: 景气打分系统 5 大 Bug 修复（P0+P1）

**Bug 1 — 5/6 打分维度失效（fina_indicator 字段不全）**
- `get_fina_indicator()` 新增 `revenue_yoy, net_profit_yoy, debt_to_assets` 字段（原先只拉 ROE/毛利率/流动比率，缺营收增速/利润增速）
- `UNIVERSAL_METRICS` 字段名修正：`gross_margin`→`grossprofit_margin`, `debt_ratio`→`debt_to_assets`（必须与 Tushare API 原始字段名一致）

**Bug 2 — quality_score 恒为 0（字段跨表+名称错误）**
- `_quality_score` 字段修正：`ocf`→`n_cashflow_act`, `capital_expend`→`c_pay_acq_const_fiolta`, `gross_margin`→`grossprofit_margin`
- `_get_stock_data()` 新增 `get_cashflow()` 调用，合并 fina_indicator + cashflow 两个表的数据

**Bug 1b — 百分位分只有 4 档离散**
- `_percentile_score` 从 P25/P50/P75 四档分桶改为 `bisect` 连续百分位排名
- `_compute_distribution` 新增 `sorted_values` 全量排序值返回

**Bug 3 — 股池无中文名**
- `score_stocks()` 新增 `name_map` 参数
- `get_stock_name_map()` 复用 stock_basic 缓存生成 `{ts_code: name}` 映射
- `report_agent._generate_stock_pool()` 传入 name_map

**Bug 4 — LLM 不可复现**
- `_call_llm` 的 `temperature`: 0.3 → 0.0（确定性输出）

**Bug 5 — hypothesize_agent 不引用 wiki 历史**
- `_build_prompt` 新增 `_load_wiki_history()` 锚定注入
- 读 `wiki/industries/{行业}.md` 最近 3 条评级 + 最近报告摘要（前 500 字）
- 因 Bug 5 先修，Tavily 搜索结果差异被历史锚点拉回，Bug 4 自然改善 ~80%

### 改动文件
- `tushare_client.py`（+3 字段）
- `stock_screener.py`（百分位连续化、quality 跨表修复、name_map）
- `industry_metrics.py`（字段名修正、sorted_values、get_stock_name_map）
- `hypothesize_agent.py`（wiki 历史锚定、temperature=0）
- `report_agent.py`（传入 name_map）

## v0.13.1 (2026-06-29)

### B1: Tushare 行业分类映射

- `industry_metrics.py` 新增 `get_industry_ts_codes()`：精确匹配（stock_basic 的 industry 字段）+ 申万分类（index_classify L1/L2/L3）双信源取并集 + 结果缓存
- `verify_agent.py` / `report_agent.py` 替换 `str.contains()` 模糊匹配为 `get_industry_ts_codes()` 统一调用
- 改动文件：`industry_metrics.py`（+110行）、`verify_agent.py`（-12/+5）、`report_agent.py`（-10/+5）

### D: acceleration stub 真实化

- `_compute_acceleration` 从占位 stub 改为拉取最近 2 期 `fina_indicator`，比较 `revenue_yoy[t]` vs `revenue_yoy[t-1]`
- 返回 `{ratio, accelerating, decelerating, flat, total}`
- 新增 `_safe_float()` 辅助函数

### A: API 4 分步端点完善

- 新增 `StepRequest` model（含 `industry` + `session_id`）
- `/hypothesize` / `/verify` / `/counter` / `/report` 四个端点从 400 stub 改为真实实现
- Coordinator 新增 `pipeline_cache` 暂存中间结果，支持分步调用时跨请求传递
- `/search` 端点同步存储结果到 cache
- 端点从 DB 回退加载（缓存失效时自动从 Hypothesis 表重建）

### C: 前端集成测试

- 新增 `tests/prosperity-components.test.tsx`：26 个测试用例
- **IndustrySelector**（8 tests）：渲染、空输入保护、disabled 状态、API 调成功/失败、Enter 键提交、loading 态
- **HypothesisBoard**（10 tests）：空状态、session 选择器、L0-L3 层级渲染、状态文字/emoji、derives_from 箭头、time_horizon、investment_implication、空假设、count badges
- **ReportViewer**（8 tests）：空状态、auto-load 最新报告、loading 态、报告加载失败、session 切换

## v0.13.0 (2026-06-29)

### 📋 SPEC 同步：v0.1.0 → v0.12.2

将高景气策略 SPEC 从原始三层平铺假设模型同步到实际 v0.12.2 因果推理链架构。

#### SPEC 更新（Phase A）

| 章节 | 更新内容 |
|------|---------|
| §2.2 | 三层平铺（核心→子→数据）→ **4层因果推理链** (L0→L3)，含强制字段（derives_from/chain_level/time_horizon/investment_implication） |
| §2.3 | 新增级联规则 + **UNREACHABLE 🚫** 状态（上游推翻→下游不可达） |
| §2.4 | 新增 CounterAgent **三遍扫描** 级联处理（DISPUTED→OVERTURNED→级联→降级） |
| §2.5 | 新增叙事体裁报告 + Mermaid 因果图 |
| §4 | 更新 hypotheses 表 v2 列 + 状态流转图（含不可达） |
| §10 | 新增 3 条 v2 设计决策（因果链选择/UNREACHABLE/叙事报告） |
| 版本号 | v0.1.0 → v0.12.2，状态「待实现」→「核心已实现」 |

#### 代码实现（Phase B）

| 文件 | 改动 |
|------|------|
| `tools/source_crawler.py` | **Stub → 真实实现**：SIA 半导体销售数据爬取（httpx+BeautifulSoup），新增信源路由分发 + SOURCE_HANDLERS 映射 |
| `tools/stock_screener.py` | **动量因子真实化**：`_momentum_stub` → `_momentum_score`，接入 Tushare daily 数据计算近 3/6 月收益率分档，含 in-memory 缓存 |
| `components/prosperity/IndustrySelector.tsx` | **新建**：行业输入 + 研究触发前端组件 |
| `components/prosperity/HypothesisBoard.tsx` | **新建**：4层因果推理链假设看板（L0-L3 分栏 + 状态 emoji + derives_from 箭头） |
| `components/prosperity/ReportViewer.tsx` | **新建**：综合报告渲染（react-markdown + 会话选择） |
| `components/Layout.tsx` | 组件映射表新增 prosperity 条目 |
| `pyproject.toml` | 新增 beautifulsoup4 依赖 |
| `tests/test_prosperity_coordinator.py` | 新增 8 个测试（source_crawler 5 + stock_screener 3） |

#### 文档同步

- `CONTEXT.md`：v0.10.0 → v0.13.0，策略状态从「设计中」→「运行中」，核心范式更新为 v2 因果推理链

## v0.12.2 (2026-06-29)

### 🧠 高景气策略 v2：4层因果推理链（HypothesizeAgent 重写）

用户核心诉求：假设不能是平铺的信息摘录，必须是「推演」而非「罗列」，
每条假设应有因果箭头，直到产生可操作的投资落点。

#### 改动文件（5 个 + 1 个迁移）

| 文件 | 改动 |
|------|------|
| `hypothesize_agent.py` | **重写** Prompt（L0现状→L1一阶→L2二阶→L3落点）+ 新 Markdown 模板（含推理链可视化、时间窗口、投资含义） |
| `verify_agent.py` | 新增级联规则：上游 DISPUTED/OVERTURNED → 下游自动 UNREACHABLE |
| `counter_agent.py` | 新增级联处理：上游推翻 → 连锁标记下游 unreachable |
| `report_agent.py` | 重写报告渲染：叙事体裁 + Mermaid 推理链图 + 按层级分章节 + 投资含义章节 |
| `models.py` | Hypothesis 新增 `chain_level`/`derives_from`/`time_horizon` 三列 + `migrate_v2()` |
| `coordinator.py` | 启动时自动执行 migrate_v2() |

#### 新推理结构

```
L0 现状诊断 (2-3条) → L1 一阶推演 (2-4条) → L2 二阶推演+拐点 (2-4条) → L3 投资落点 (2-3条)
```

每条假设强制要求：
- `id`: H{层级}-{序号} 格式
- `derives_from`: 引用上游假设 id
- `time_horizon`: L2/L3 必填时间窗口
- `investment_implication`: L3 必填可操作选股方向
- `key_indicators`: L3 必填跟踪指标

#### 新增状态

- `unreachable` 🚫：上游被推翻，本条不可达（不参与景气评级）

## v0.12.1 (2026-06-29)

### 🏗️ 高景气策略完整实现（13 Tasks Inline Execution）

从 writing-plans 直接推进到全量实现，13 个 Task 全部完成，110 测试全绿。

#### 实现产出
- **13 个文件新建**: coordinator + 6 Agent + 4 确定性工具 + api + models + 7 个基础文件
- **6 个规则文件**: source_registry + scoring_weights + semiconductor profile + 6 Skills
- **1 个测试文件**: 7 项集成测试 (coordinator/session/models/tools/agents/api/directories)
- **1 个注册项**: registry.py 新增 prosperity (inactive)

#### Task 明细
| # | Task | 核心产出 |
|---|------|---------|
| 1 | 脚手架 | 16 目录 + SCHEMA×2 + index/log/watchlist + registry + config |
| 2 | 数据模型 | 6 ORM 表 (Industry/ResearchSession/Hypothesis/IndustryMetrics/StockPool/TrackingItem) |
| 3 | 确定性工具 | industry_metrics (百分位聚合) + stock_screener (行业内排名) |
| 4 | 确定性工具 | wiki_indexer (索引/孤页/日志) + source_crawler (stub) |
| 5 | Coordinator | 会话管理 + 6 Agent 管道编排 |
| 6 | SearchAgent | Tavily 搜索 + 去重 + YAML 落盘 |
| 7 | HypothesizeAgent | LLM 三层假设 + wiki 页面 + DB 同步 |
| 8 | VerifyAgent | 多信源交叉验证 + Tushare 数据支撑 |
| 9 | CounterAgent | DISPUTED→OVERTURNED 推翻标注 |
| 10 | ReportAgent | 景气度判断 + 股池 Top20 + 行业页更新 |
| 11 | TrackAgent | 跟踪项提取 + yaml/DB 双写 |
| 12 | API+Skills | 9 端点 + 6 CodeBuddy Skills |
| 13 | 规则+测试 | 3 yaml profile + 7 integration tests |

#### Files Changed
- `backend/app/strategies/prosperity/` — **新建** 完整策略包 (15 文件)
- `backend/app/core/registry.py` — **修改** 新增 prosperity 注册项
- `backend/app/core/config.py` — **修改** 新增 3 个路径配置
- `data/prosperity/` — **新建** 数据目录 (7 子目录 + 4 文件)
- `backend/rules/prosperity/` — **新建** 规则配置 (3 文件)
- `backend/tests/test_prosperity_coordinator.py` — **新建** 7 集成测试

#### 测试
- 新增 7/7 全绿
- 全量 110/110 全绿，零回归

---

## v0.12.0 (2026-06-29)

### 📐 新高景气策略设计（brainstorming 产出）

**动机**: 用户希望新增一条与龟龟策略完全独立的高景气策略。经过 brainstorming 流程完成完整设计。

#### 设计产出
- **Spec 文档**: `docs/specs/2026-06-29-prosperity-strategy-design.md`（完整设计 Spec）
- **核心范式**: 假设驱动研究 — 输入行业 → 情报搜索 → 假设形成 → 交叉验证 → 反推修正 → 报告+股池 → 知识库沉淀
- **6 Agent 认知循环**: SearchAgent / HypothesizeAgent / VerifyAgent / CounterAgent / ReportAgent / TrackAgent
- **知识库**: 融合 Karpathy LLM Wiki 理念 — raw/ 只读 + wiki/ LLM 维护 + 假设页含推翻历史 + 跟踪项巡检
- **双形态**: CodeBuddy Skills（对话式）+ Web 管道式，共用同一套 Agent + 确定性脚本
- **打分公式**: 行业内百分位排名（非绝对阈值），消除行业间差异
- **数据库**: SQLite + SQLAlchemy ORM（可无缝迁移 PostgreSQL）
- **首个行业**: 半导体

#### 关键设计决策
1. ✅ 假设状态四态：CONFIRMED / PARTIAL / DISPUTED / UNVERIFIED
2. ✅ 假设不设硬上限，分层（核心判断 → 子假设 → 数据假设）
3. ✅ 渗透率等非财务数据优先 Tier 1 协会公开数据
4. ✅ 股池打分用行业内百分位，不写死阈值
5. ✅ 前端暂缓，先跑通 Agent + 后端
6. ✅ SQLite 零配置，上线换 PostgreSQL 一行连接字符串

#### Files Changed
- `docs/specs/2026-06-29-prosperity-strategy-design.md` — **新建** 完整设计 Spec
- `docs/CONTEXT.md` — v0.8.0→v0.10.0 + 高景气策略概览
- `CHANGELOG.md` — 本条目

---

## v0.11.1 (2026-06-29)

### 🧹 深度清理：高景气残留 + 临时文件
- 删除 `registry.py` 中注释的 prosperity 策略注册项（L49-62）
- 删除 `data/knowledge_graph/` 空目录树（entities/tracks/ / memory/）
- 删除 4 个 pytest 临时输出：`.pytest_output.txt`, `backend/test_full.txt`, `test_result1.txt`, `test_result2.txt`
- 删除 `backend/0.2.40` yfinance 残留空文件
- 删除根目录乱码文件名 `{v}')`





---

## v0.8.0 (2026-06-22)

### 🏗️ 架构重构：单策略 → 多策略平台

**目标**: 为未来更多策略提供干净的扩展底座，龟龟策略功能零退化。

#### 1. 策略注册表 `app/core/registry.py`
- 新增 `StrategyMeta` 数据类 + `STRATEGIES` 字典，策略元信息唯一真相来源
- `main.py` 遍历注册表自动挂载各策略 API 路由
- `api/strategies.py` 从注册表动态读取策略列表
- 加新策略：注册 1 行 + 新建 3 个目录 + 前端映射表 1 行 = 5 分钟

#### 2. 后端：龟龟代码自包含化
- `stocks.py` (400行) → `strategies/turtle/api.py` — 龟龟专属 API 端点
- `services/qrv_agent.py` → `strategies/turtle/qrv_agent.py`
- `services/data_summarizer.py` → `strategies/turtle/data_summarizer.py`
- `services/websearch_extractor.py` → `strategies/turtle/websearch_extractor.py`
- `services/` 只保留纯基础设施：`tushare_client.py` + `data_fetcher.py`
- API 路径：`/api/stocks/*` → `/api/turtle/*`

#### 3. 数据缓存：按策略隔离
- `data/stock_cache/turtle/` — 龟龟专属（42 个股 + pool.json + 全局文件）
- `config.py` 新增 `TURTLE_CACHE_DIR`
- 所有路径常量从 `settings.STOCK_CACHE_DIR` → `settings.TURTLE_CACHE_DIR`

#### 4. 前端：策略切换 + 组件分目录
- Sidebar 策略列表动态化：`GET /api/strategies` 替代硬编码数组
- Sidebar 点击切换策略 → `selectedStrategy` 状态 → Layout 组件映射表分发
- 组件目录重组：
  - `components/turtle/` — 龟龟股池 + 评分卡 + 报告（移入）
  - `components/` 根目录 — Layout/Sidebar/ResizablePanel（共享）
- API 路径全部更新为 `/api/turtle/*`

#### 5. 测试验证
- 98/98 pytest 全部通过
- 37/37 vitest 全部通过
- tsc --noEmit 零错误
- vite build 成功

### 影响
- 🟢 龟龟策略功能零退化：所有业务逻辑一行未改

---

## v0.7.14 (2026-06-22)

### Changed — 报告内容排版全面优化（结论突出 + 可读性 + 趋势可视化）

#### 1. 结论洞察框 (`blockquote` → `.insight`)
- LLM 输出的 `> 结论...` 引用块自动渲染为**左侧蓝色 3px 色条 + 浅蓝背景 + ⓘ 图标**的洞察框
- 结论文字更醒目，用户滚动时一眼看到关键判断

#### 2. 趋势箭头 → Pill Badge
- `▲ up` / `▼ down` / `─ stable` 纯文本 → **绿底/红底/灰底圆角药丸徽章**
- 中文字面化：`上升`/`下降`/`持平`/`快速增长`/`吃老本`/`收缩`
- 表格中趋势列可瞬间扫描

#### 3. 排版层级优化
- **正文**: 14→15px, line-height 1.6→1.72, `text-align: justify`
- **H3**: 16→17px, Weight 600→650, 新增顶部 1px 分隔线
- **H4**: 14→15px, Weight 600→650
- **Strong**: Weight 600→650
- **段落**: 新增 `.paragraph` margin-bottom 14px

#### 4. 表格优化
- **数字列右对齐**: 自动检测纯数字/百分比/亿/万 → `font-variant-numeric: tabular-nums` + 等宽字体
- **PASS/FAIL 徽章加强**: padding 2→3px, Weight 600→700, FAIL 行首列左侧 3px 红线指示
- **斑马纹**保留，hover 淡蓝高亮保留

#### 5. 超链接升级
- 下划线：dashed → solid (半透明蓝)
- 外部链接：新增 ↗ 箭头图标，hover 时向右上微移
- 内部引用链接无箭头，保持简洁

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — `mdComponents` 新增 `blockquote`/`p` 渲染器, `TdRenderer` 趋势升级 + 数字检测
- `frontend/src/components/ReportViewer.module.css` — ~100行变更 (insight/paragraph/trendBadge/tdNumeric/linkExternal/linkArrow)
- `frontend/package.json` — 0.7.13→0.7.14
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 37/37 vitest 全部通过
- ✅ TypeScript `tsc --noEmit` 零错误
- ✅ Vite build 成功

---

## v0.7.13 (2026-06-22)

### Changed — Argus 百眼巨人 Logo + 报告目录全面重设计

#### 1. Logo: "百眼巨人" 概念重设计 (`Sidebar.tsx`)
- 旧: 中央单眼 + 十字准星 (4 条方向线)
- 新: 中央瞳孔 + **8 颗卫星"百眼"**均匀环布 + 十字准星
- 底座蓝色圆，8 个小白点代表 Argus 的无数眼睛；中央眼 + 准星保留精准/投资隐喻

#### 2. 报告目录 TOC 全面重设计 (`ReportViewer.tsx` + `.module.css`)
- **Header**: 标题 13px 加粗，右置 SVG 图标按钮（⊟ 折叠全部 / ⊞ 展开全部）替代旧文字按钮
- **父级条目新增**:
  - SVG chevron 图标 ▸/▾（`rotate(90deg)` 旋转动画，`cubic-bezier(0.16,1,0.3,1)`）
  - 子项计数 Badge（灰色 pill，active 时联动蓝底）
  - 分离点击行为：chevron → 折叠/展开；文字 → 滚动到章节
- **子项文件树层级**:
  - 左侧 `1.5px` 竖线连接器（`border-left`），父子视觉清晰
  - `max-height` + `opacity` 过渡动画（0→600px, 0.35s）
- **交互增强**:
  - 父行 hover 浅色高亮；active 蓝色左边框 + 淡蓝背景
  - IntersectionObserver 联动当前阅读位置高亮
  - 隐藏无子项父级的 chevron 占位

### Files Changed
- `frontend/src/components/Sidebar.tsx` — `LogoIcon` SVG 百眼环重设计
- `frontend/src/components/ReportViewer.tsx` — `TocPanel` 全面重写 + `onToggle` prop
- `frontend/src/components/ReportViewer.module.css` — 旧 8 个 TOC class → 新 14 个 class
- `frontend/package.json` — v0.7.12 → v0.7.13
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 37/37 vitest 全部通过
- ✅ TypeScript `tsc --noEmit` 零错误
- ✅ Vite build 成功

---

## v0.7.12 (2026-06-22)

### Changed — 前端全面 UI 优化 (设计系统 + 组件层级 + 交互细节)

**动机**: 散户/个人投资者使用反馈：界面偏冷硬、信息层次不够清晰、缺少品牌辨识度。

**设计方向**: 清晰 · 现代 · 友好 (Notion/Linear 风格)，纯桌面端，不改业务逻辑。

---

#### Phase 1: 设计基础层 (`index.css`)
- **色彩系统**: 冷灰白 → 暖底微米 (`#faf9f7`)，主色 `#3167f3` → `oklch(52% 0.16 250)` 更通透
- **新增语义化表面**: `--surface-raised` / `--surface-overlay` 替代卡片嵌套
- **新增软状态色**: `--positive-soft` / `--warning-soft` / `--negative-soft` 状态背景
- **排版层级加大**: H1 24→28px, H2 18→20px, H3 15→16px, Body 13→14px, Caption 10→11px
- **字体细节**: `font-feature-settings: "cv01" 1, "cv04" 1` 启用 Inter 替代字符集
- **流体间距**: `--space-section/block/gutter` 基于 `clamp()` 自适应视口
- **全局焦点环**: `:focus-visible` 2px 蓝色 + 2px offset
- **按钮动效优化**: `:active` scale(0.97) translateY(1px) 下压感

#### Phase 2: 组件层级 (6 组件 TSX + CSS)

**Sidebar**:
- Logo: 蓝色方块"A" → SVG Argus之眼 (圆形靶心+准星)
- 激活态保留 `border-left` + 微背景，移除 uppercase 标签
- Footer 字号 10→11px，间距增加

**StockPool**:
- 表格行高 36→44px (14px body + 呼吸感)
- 评分条 6→8px，过渡 0.3s→0.8s cubic-bezier
- hover 左侧蓝色指示线 (`td:first-child::before` 2px 动画)
- "未分析" → "点击分析 →" 蓝色引导文案
- 表头移除 `text-transform: uppercase`
- 门控标签新增 `transition` 颜色过渡
- 展开动画 `ease` → `cubic-bezier(0.16, 1, 0.3, 1)`

**ScoreCard**:
- 综合总分 22→28px + `letter-spacing: -1px`
- 分组间距 14→20px + 分组间竖线分隔
- 子分数 13→15px，维度进度条 4→5px
- 进度条过渡 `ease` → `cubic-bezier`

**ReportViewer**:
- **卡片解构**: `contentInner` 去掉 `box-shadow` + `border-radius`，内容自然融入背景
- **空状态重建**: emoji 48px → SVG 内联插画 (72×72 简洁图表) + 引导性文案
- **悬浮回顶**: 固定 `.backTop` → 右下悬浮胶囊 (`floatingBack`)，scroll>400px 时渐入，hover 上浮
- **H2 段落标题**: `border-bottom: 2px accent` → `1px border-default`，hover 时变 accent
- **H3 颜色统一**: `#555b7e` → `var(--text-secondary)`
- **TOC 按钮**: 实线边框 → ghost button (hover 时显现)
- **Gate 门控标签**: 新增 `transition` 过渡
- **所有动效**: `ease` → `cubic-bezier(0.16, 1, 0.3, 1)`
- **按钮 spinner**: outline/error 变体适配度提升

**UX 文案优化**:
- 空状态主文案: "请从股池选择一只股票" → "从左侧股池选一只股票，查看深度分析报告"
- 空状态副文案: "点击左侧股池中的个股..." → "我们会帮你分析生意本质、护城河、增长引擎等 10 个维度"
- 加载中: "加载报告中..." → "正在为你准备分析报告..."
- 分析按钮: "🔍 分析个股" → "🔍 开始分析"
- 重新分析: "🔄 重新分析" → "🔄 重新生成报告"
- StockPool 未分析: "未分析" → "点击分析 →"

**ResizablePanel**:
- 手柄视觉宽度 4→6px，点击热区扩大 (margin hack)
- 拖拽时 `document.body` 全局 cursor 锁定 + `userSelect: none`

#### Phase 3: 交互与细节
- **错误框增强**: 新增左侧 3px 红色竖线指示 + `--negative-soft` 背景
- **警告框增强**: 左侧 3px 橙色竖线
- **StockPool 错误**: 圆角卡片 + 红色软背景
- **Sidebar 过渡**: `ease` → `cubic-bezier(0.16, 1, 0.3, 1)`

### Files Changed
- `frontend/src/index.css` — 设计 token 全面重塑 (~90行)
- `frontend/src/components/Sidebar.tsx` — Logo SVG + `LogoIcon` 组件 (+20行)
- `frontend/src/components/Sidebar.module.css` — 激活态 + 间距 (~10行)
- `frontend/src/components/StockPool.tsx` — "点击分析 →" 文案 (1行)
- `frontend/src/components/StockPool.module.css` — 行高/hover指示线/动画 (~40行)
- `frontend/src/components/ScoreCard.module.css` — 分数/间距/分隔线 (~30行)
- `frontend/src/components/ReportViewer.tsx` — 空状态SVG + 悬浮按钮 + 文案 + 类型修复 (~30行)
- `frontend/src/components/ReportViewer.module.css` — 卡片解构/H2/动效/错误框 (~60行)
- `frontend/src/components/ResizablePanel.tsx` — cursor 锁定 (+4行)
- `frontend/src/components/ResizablePanel.module.css` — 手柄视觉 (~10行)
- `frontend/src/components/Layout.module.css` — 过渡优化 (1行)
- `frontend/package.json` — 版本 0.7.10 → 0.7.12
- `docs/CONTEXT.md` — 版本 0.7.11 → 0.7.12
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 37/37 vitest 全部通过
- ✅ TypeScript `tsc --noEmit` 零错误
- ✅ 零业务逻辑变更 (仅 CSS + 文案 + SVG)

---


## v0.7.11 (2026-06-22)

### Fixed — 股池 QRV 评分栏不显示分数

#### 问题
后台分析完成后，前端股池 QRV 栏目永远显示 `"—"`。根因是 `qrv_agent.py` 仅在 `qrv_analysis.json` 中保存 `meta`/`gate_status`/`llm_raw_response`/`tokens_used`，但从 LLM 输出的「综合打分卡」表格中提取 `scores` 结构化数据。

LLM 确实生成了各维度评分（如 Q1=8, Q2=9, V3=9, 综合=7.7），但这些数字嵌在 markdown 文本中从未被解析。

#### 修复
- **`qrv_agent.py`**: 新增 `_parse_scores()` 静态方法，用正则从 LLM markdown 输出的「综合打分卡」表格提取 Q1-Q3/R1-R4/V1-V3 10 维度分数 + 综合总分
- `_parse_scores()` 自动计算 Q/R/V 加权均分
- `analyze_async()` 写完 `qrv_analysis.json` 时同步写入 `scores` 字段
- 已有回填逻辑（`stocks.py` L282-297）在分析完成时自动将 scores 回填到股池内存缓存，前端无需等缓存过期即可看到

#### 后端兼容
- 已分析完成的个股需要**重新分析**才能在 `qrv_analysis.json` 中生成 `scores` 字段
- 不重新分析 → `scores=None` → 股池仍显示 `"—"`（无破坏性）
- 新分析的个股自动带 scores

### Files Changed
- `backend/app/services/qrv_agent.py` — +`_parse_scores()` (~60行) + JSON 输出加 `scores`
- `docs/CONTEXT.md` — 版本号 0.7.7 → 0.7.11
- `backend/app/strategies/turtle/turtle-coordinator.md` — 版本号
- `backend/app/core/config.py` — 版本号 0.7.9 → 0.7.11
- `backend/pyproject.toml` — 版本号 0.7.9 → 0.7.11
- `CHANGELOG.md` — 本条目

---

## v0.7.10 (2026-06-22)

### Added — 引用跳转金色闪烁动画 + Path B 内部链接高亮整行

#### 问题
1. 跳转后的淡蓝色高亮动画太弱，用户不易察觉目标行
2. 只有 `<cite>` 路径（Path A）有高亮，内部链接 `[A1](#a1)`（Path B）走浏览器原生 hash 跳转 → 完全没有高亮提示

#### 修复

##### 1. 动画升级（CSS）
- 废弃 `refFlash` / `sectionFlash` 淡蓝色渐隐 → 统一替换为 `jumpFlash` 金色闪烁
- 颜色：`rgba(255, 193, 7, 0.38)` → 金色，比之前的蓝色醒目得多
- 时长：2s → 1.5s（更紧凑的反馈感）
- `refRowHighlight` 和 `sectionHighlight` 共用同一动画

##### 2. Path B 内部链接高亮（TSX）
- `handleCiteClick` → 升级为 `handleContentClick` 统一点击处理器
- Path A (cite 标签)：保持原有逻辑 + 使用新 `jumpFlash` 动画
- Path B (内部链接 `a[href^="#"]`)：
  - `e.preventDefault()` 阻止浏览器原生 hash 跳转
  - 通过 `document.getElementById()` 找到目标锚点
  - 用 `el.closest('tr')` 定位整行 → 金色闪烁 1.5s
  - 若目标在折叠 section 中 → 展开全部 section → 350ms 后重试
- 提取公共 `flashTarget()` 工具函数，两路径复用

##### 3. scrollToSection 同步
- `setTimeout` 移除 class 时间：2000ms → 1500ms（匹配 CSS 动画时长）

#### 测试
- `citation-jump.test.tsx` 新增 3 个 Path B 高亮测试：锚点在 tr 内、多行锚点独立、链接-锚点匹配
- 37/37 vitest 全部通过（原 34 + 新增 3）

### Files Changed
- `frontend/src/components/ReportViewer.module.css` — 合并 refFlash + sectionFlash → jumpFlash 金色闪烁
- `frontend/src/components/ReportViewer.tsx` — handleCitClick → handleContentClick (+Path B + flashTarget)
- `frontend/tests/citation-jump.test.tsx` — +3 个 Path B 高亮测试
- `frontend/package.json` — 版本 0.7.9 → 0.7.10
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 37/37 vitest 全部通过
- ✅ TypeScript 新增代码零错误（预存 2 个与本次无关）

---

## v0.7.9 (2026-06-22)

### Fixed — 链接跳转覆盖范围扩展（窄匹配 → 宽匹配）

#### 问题
`preprocessCitations` Step 2 正则只匹配 `[A-Z][-\w]*\d+` 引用格式（如 `[A1]`、`[W-q-3]`），但 LLM 可能产生其他格式的内部链接：
- 纯小写：`[abc](#abc)`
- 小写+连字符：`[some-link](#some-link)`
- 下划线：`[REF_001](#ref_001)`
- 中文字符：`[中文锚点](#中文锚点)`

这些链接的 href 不加 `user-content-` 前缀，而 `rehype-sanitize` 给目标 id 自动加前缀 → **href 和 id 不匹配 → 点击无跳转**。

#### 修复
- `preprocessCitations` Step 2 正则从窄匹配：
  ```
  /\[([A-Z][-\w]*\d+)\]\(#(?!user-content-)([-\w]+)\)/g
  ```
  → 宽匹配：
  ```
  /\[([^\]]+)\]\(#(?!user-content-)([^)]+)\)/g
  ```
- 现在**任意** `[文字](#锚点)` 格式的 markdown 内部链接都会被加上 `user-content-` 前缀

#### 测试
- `citation-jump.test.tsx` 新增 8 个边界测试：纯小写、连字符、下划线、中文锚点、数字锚点、外部链接不受影响等
- 34/34 vitest 全部通过

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — Step 2 正则窄→宽匹配
- `frontend/tests/citation-jump.test.tsx` — +8 个边界测试
- `frontend/package.json` — 版本 0.7.8 → 0.7.9
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 34/34 vitest 全部通过
- ✅ TypeScript 零编译错误

---

## v0.7.8 (2026-06-22)

### Fixed — 引用跳转功能回归修复（先测试后代码）

#### 根因诊断（vitest 单元测试驱动）
1. **`<a id="a1">` 锚点被跳过**：`rehype-sanitize` 默认给所有 `id` 加 `user-content-` 前缀，导致 `<a href="#a1">` 和 `<a id="user-content-a1">` 不匹配
2. **`<cite>` 标签被清除**：`defaultSchema.tagNames` 不含 `cite`，且属性名需用 camelCase（`dataRef` 非 `data-ref`）

#### 修复内容
- `preprocessCitations` 新增 Step 2：`[A1](#a1)` → `[A1](#user-content-a1)`，同步 href 匹配 sanitize 输出
- `sanitizeSchema.tagNames` 添加 `cite`
- `sanitizeSchema.attributes.cite` 使用 camelCase：`['dataRef', 'id', 'className']`
- `sanitizeSchema.attributes.a` 添加 `['id', /.*/]`, `['name', /.*/]` 正则形式
- 新增 `tests/citation-jump.test.tsx`：26 个 vitest 单元测试全覆盖两条引用路径
- 新增 `vitest.config.ts` + `tests/setup.ts` + `npm run test:unit` 脚本
- 安装 vitest@3, jsdom, @testing-library/react 等测试依赖

### Added
- `frontend/tests/citation-jump.test.tsx` — 26 个单元测试
- `frontend/vitest.config.ts`
- `frontend/tests/setup.ts`
- `npm run test:unit` / `npm run test:unit:watch`

---

## v0.7.7 (2026-06-22)

### Fixed — 三项前端修复 + 股池分数实时更新

#### 1. 引用点击跳转修复 (ReportViewer.tsx + .module.css)
- `mdComponents.a` 组件转发 `{...rest}` → `id`/`name` 等属性不再被丢弃，锚点跳转正常
- `isDefaultExpanded` 正则新增 `参考来源|资料来源|引用` → 参考来源区域默认展开，DOM 中锚点已存在
- CSS 全局添加 `cite { cursor: pointer }` → 引用元素有视觉点击反馈

#### 2. 盈利质量趋势着色 (ReportViewer.tsx + .module.css)
- `TdRenderer` 新增 `TREND_MAP`：识别 `up`/`down`/`stable`/`吃老本`/`收缩` → 自动着色
  - `up` → 绿色 ▲ up / `down` → 红色 ▼ down / `stable` → 灰色 ─ stable
- CSS 新增 `.trendUp`(绿) / `.trendDown`(红) / `.trendStable`(灰)

#### 3. 股池分数实时更新 (stocks.py)
- `_run_analysis_background` done 时读取 `qrv_analysis.json` 的 `scores`，回填到 `_pool_cache`
- 前端股池栏无需等缓存过期即可看到最新的 QRV 分数

---

## v0.7.6 (2026-06-22)

### Changed — 置信度质量加权 + 前端引用锚点/TOC 修复

**问题**: 四个用户反馈：
1. WebSearch 置信度全是 HIGH（阈值太松：≥6条snippet 即 HIGH，每模块 12+条永远满足）
2. 报告中引用显示为裸 `[W-q-1](#w-q-1)`，无法点击跳转
3. TOC 导航点击 V3 子标题跳转到 V 父标题
4. 引用锚点 `<a id="...">` 被 rehype-sanitize 剥离，跳转失效

**方案**:

#### 1. 置信度质量加权 (coordinator.py)
- 新增 3 个确定性打分函数（零 LLM）：
  - `_source_credibility(url)` → 基于域名分类（官方1.0 / 权威0.8 / 研报0.7 / 主流媒体0.5 / 聚合0.3 / 自媒体0.1）
  - `_info_density(content)` → 基于数字+单位数量（≥5→1.0, ≥2→0.7, ≥1→0.4）
  - `_recency(text)` → 基于年份（1年内1.0, 1-3年0.5, 3年+0.2）
- 每条 snippet 打总分 0~3 → 按质量总分判定模块置信度：
  - 总分≥12→HIGH, ≥6→MEDIUM, ≥2→LOW, <2→NONE
- 每 snippet 写入 `quality_score`（新增字段）+ `confidence`（质量标签）

#### 2. 前端引用锚点修复 (ReportViewer.tsx)
- **2a**: `preprocessCitations` 正则加 `(?!\()` 负向前瞻 → `[W-q-1](#w-q-1)` 不被正则误匹配，react-markdown 正常渲染为 `<a>` 链接
- **2b**: `rehype-sanitize` schema 新增 `a[id]`、`a[name]` 属性白名单 → `<a id="w-q-1">` 锚点不被剥离

#### 3. TOC 子标题导航修复 (ReportViewer.tsx)
- TOC 子项 `onClick`：`item.id` → `sub.id`
- `scrollToSection` 新增 h3 查找逻辑：优先 `document.querySelector('h3[id="..."]')`，fallback h2 section
- 父 section 自动展开

### Files Changed
- `backend/app/strategies/turtle/coordinator.py` — +85行 (3 质量函数 + _tavily_search snippet/模块置信度改造)
- `backend/rules/v2/turtle_qrv.yaml` — 置信度定义更新（计数→质量加权）
- `backend/app/strategies/turtle/turtle-coordinator.md` — v0.7.5→v0.7.6 + Step 7 置信度说明
- `docs/CONTEXT.md` — v0.7.5→v0.7.6 + DataSummarizer v2.3.0
- `frontend/src/components/ReportViewer.tsx` — 引用正则 + sanitize schema + TOC h3 导航 (~+30行)
- `backend/app/core/config.py` — 0.7.5→0.7.6
- `backend/pyproject.toml` — 0.7.5→0.7.6
- `frontend/package.json` — 0.7.5→0.7.6
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 98/98 pytest 全部通过
- ✅ TypeScript tsc --noEmit 零错误
- ✅ Linter 零错误
- ✅ 纯确定性规则引擎，零 LLM 调用

### Migration Notes
- 已缓存的 `websearch.yaml` 中 snippet 的 `confidence` 仍是旧值（MEDIUM），需 `--force-websearch` 重搜才能获得新质量加权置信度
- `quality_score` 为新字段，老缓存中缺失，不影响下游（`data_summarizer.py` 兼容兜底）

---

## v0.7.5 (2026-06-21)

### Added — 参考来源锚点跳转 + 置信度使用规则 (Prompt + 数据层)

**问题**: 用户反馈两个设计缺口：
1. 报告中 `[W-q-3]` 等引用标记只是纯文本，无法点击跳转到参考来源
2. websearch 有置信度数据（HIGH/MEDIUM/LOW/NONE），但 Prompt 没有告诉 LLM 如何使用

**方案（零计算逻辑变更）**:

#### 1. 锚点跳转 (turtle_qrv.yaml Prompt)
- 核心铁律第 2 条：`[A2]` 纯文本 → 必须写成可点击 `[A2](#a2)` + 参考来源行前放 `<a id="a2"></a>` 锚点
- W-引用表模板：标记列从裸 `[W-q-1]` → `<a id="w-q-1"></a>[W-q-1](#w-q-1)`
- A-引用表模板：标记列从裸 `[A1]` → `<a id="a1"></a>[A1](#a1)`
- 前端需 `rehype-raw` 插件支持 HTML 锚点（已安装）

#### 2. 置信度使用规则 (turtle_qrv.yaml Prompt 新增整节)
- 置信度四级定义 (HIGH/MEDIUM/LOW/NONE) + 对应引用规则
- LOW 置信度来源不可作为主要论据，强结论需标注「⚠️ 低置信度」
- 某维度全 LOW/NONE → 开篇声明外部数据可信度不足
- W-引用表新增"置信度"列，从 reference_index 提取

#### 3. 数据层注入置信度 (data_summarizer.py v2.1→v2.2)
- `_build_reference_index()` W 条目新增 `module_confidence` + `snippet_confidence` 字段
- 新增 `confidence_summary` 块，汇总 5 模块置信度 + overall 评级
- overall 评级规则: HIGH≥3→HIGH, HIGH+MEDIUM≥3→MEDIUM, 其他→LOW→NONE

### Files Changed
- `backend/rules/v2/turtle_qrv.yaml` — v4.1→v4.2: +锚点跳转指令 +置信度使用规则整节 +W/A引用表模板加锚点+置信度列 (~+40行)
- `backend/app/services/data_summarizer.py` — v2.1→v2.2: W条目加module_confidence/snippet_confidence + confidence_summary (~+25行)
- `backend/app/strategies/turtle/turtle-coordinator.md` — v0.7.4→v0.7.5 + Step 7 置信度说明 + Step 8 输出质量
- `docs/CONTEXT.md` — 版本号 + DataSummarizer 版本
- `backend/app/core/config.py` — 版本 0.7.4→0.7.5
- `backend/pyproject.toml` — 版本 0.7.4→0.7.5
- `frontend/package.json` — 版本 0.7.4→0.7.5
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 98/98 测试全部通过
- ✅ 纯 Prompt + 数据索引层改动，零计算逻辑变更

---

## v0.7.4 (2026-06-21)

### Fixed — 报告输出质量四件套 (Prompt + 数据锚点)

**问题**: 用户反馈四个报告质量问题：
1. 报告段落不稳定 — 一会儿以"质量分析"开头，一会儿以"整体研判"/"分析摘要"开头，导航栏缺段
2. 超链接无 URL — `[W-q-2]` 不可点击、`[A7]` 在参考来源中完全消失
3. 表格趋势 up/down/stable 不直观
4. 估值区间建议每次输出差距极大，LLM 凭感觉估 PE

**方案**:

#### 1. 报告结构强制 (turtle_qrv.yaml Prompt)
- 在 Prompt 最前面新增强制输出结构声明，明确 7 个顶级 `##` 标题的固定顺序和名称
- LLM 不得在 Q 之前添加"分析摘要""概述"等章节
- 前端导航栏直接依赖这些 `##` 解析，不按模板输出 = 导航栏缺失

#### 2. 参考来源完整化 (turtle_qrv.yaml + data_summarizer.py)
- Prompt 中参考来源分两类：**W-引用**（websearch URL，必须有可点击链接）和 **A-引用**（Data Summarizer 数据来源 + 关键原始数值）
- `data_summarizer.py` `_build_reference_index()` 新增 A1-A8 数据锚点，包含：
  - A1: 最新年营收/净利/ROE（亿/%）
  - A2: 收入结构线索
  - A3: 5年分红合计（亿）
  - A4: CQ 通过维度数 + FAIL维度
  - A5: PR%/门槛%
  - A6: PE/PB/股息率
  - A7: 应收周转天数/固定资产占比%
  - A8: PE 当前值 + 分位点（p25/median/p75）
- LLM 在报告末尾参考来源中可直接提取这些数值填入 A-引用表格

#### 3. 趋势箭头 (turtle_qrv.yaml Prompt)
- `up`/`down`/`stable` → `↑`/`↓`/`→`，同时禁止使用英文词

#### 4. 估值区间公式约束 (turtle_qrv.yaml Prompt)
- 低估 PE = min(当前PE × 0.7, A8.p25)
- 合理 PE = A8.median
- 高估 PE = max(当前PE × 1.3, A8.p75)
- 目标价 = 最新年度 EPS × PE
- 明确禁止凭感觉估 PE

### Files Changed
- `backend/rules/v2/turtle_qrv.yaml` — v4→v4.1: +结构强制 +箭头 +估值公式 +A系列参考来源 (~+70行)
- `backend/app/services/data_summarizer.py` — v2.0→v2.1: reference_index +A1-A8 (~+90行)
- `backend/app/strategies/turtle/turtle-coordinator.md` — Step 8 标注 v0.7.4 输出质量
- `docs/CONTEXT.md` — 版本号 + DataSummarizer 版本
- `backend/app/core/config.py` — 版本 0.7.3→0.7.4
- `backend/pyproject.toml` — 版本 0.7.3→0.7.4
- `frontend/package.json` — 版本 0.7.3→0.7.4
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 98/98 测试全部通过
- ✅ 纯 Prompt + 数据索引层改动，零计算逻辑变更

---

## v0.7.3 (2026-06-21)

### Added — R4 重大事件与资本运作 (QRV v4 框架)

**问题**: 分众传媒 3 月公告定增收购新潮传媒 (83.5 亿)，此类重大资本运作事件在搜索/提取/分析三层均漏掉——搜索未搜"定增""并购"，提取器无企业事件覆盖，QRV 10 维度无一要求分析。

**方案（三层联动，不新增搜索成本）**:

| 层 | 改动 | 说明 |
|---|------|------|
| 搜索层 | `q_websearch` 新增 1 条关键词 | `"定增 并购 收购 资产重组 资本运作 重大合同 重大事项"` |
| 提取层 | `WebSearchExtractor` 新增 `_extract_corporate_events()` | 5 类事件正则提取：定增/并购/重组/重大合同/诉讼 |
| 分析层 | QRV prompt 新增 R4 模块 | 事件清单表 + 影响分析 + 跨维度联动(Q2护城河/Q3增长/R3控股/V1价值陷阱) |

**事件提取器详情** (`websearch_extractor.py`):

| 事件类型 | 提取字段 | 正则示例 |
|---------|---------|---------|
| `placement` (定增) | amount_billion, purpose | `(定增\|非公开发行\|发行股份\|募集资金)` |
| `merger` (并购) | target, amount_billion | `(收购\|并购\|要约收购)` |
| `restructure` (重组) | description | `(重大资产重组\|资产注入\|资产置换\|借壳上市)` |
| `major_contract` (重大合同) | amount_billion, counterparty | `(中标\|签约\|签署.*(合同\|协议\|订单))` |
| `litigation` (重大诉讼) | amount_billion, type | `(诉讼\|仲裁\|起诉\|被诉\|应诉)` |

**R4 模块结构**:
- R4.1: 近期重大事件清单表（日期/类型/金额/量化影响）
- R4.2: 事件影响分析（短期/中长期，每个事件 80 字）
- R4.3: 跨维度联动表（并购→Q2护城河/Q3增长，定增→R3控股/V1价值陷阱）
- R4.4: 综合评判（扩张期/整合期/收缩期/动荡期）

**分析框架**: QRV v3 → v4，10 模块 → 11 模块，综合打分卡新增 R4 行。

### Files Changed
- `backend/rules/v2/turtle_qrv.yaml` — v3→v4: +1 搜索关键词, +R4 分析模块, +R4 prompt
- `backend/app/services/websearch_extractor.py` — +`_extract_corporate_events()` (~80行)
- `backend/app/services/data_summarizer.py` — data_sufficiency +R4_corporate_events
- `backend/app/strategies/turtle/turtle-coordinator.md` — Step 7/7.5/8 同步 11 模块
- `docs/CONTEXT.md` — 版本号 + R4 模块 + WebSearchExtractor 更新
- `backend/app/core/config.py` — 版本 0.7.1 → 0.7.3
- `backend/pyproject.toml` — 版本 0.7.1 → 0.7.3
- `frontend/package.json` — 版本 0.7.0 → 0.7.3
- `backend/tests/test_websearch_extractor.py` — **新建** 5 个 corporate_events 单元测试
- `backend/tests/test_spec_compliance.py` — +2 个 R4 合规测试
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 全量测试通过
- ✅ Linter 零错误

---

## v0.7.2 (2026-06-21)

### Fixed — dim7 供应商挤压 N/A 原因不透传

- **`cash_quality.py`**: dim7 `no_supplier_squeeze_or_insufficient_data` 拆分为两种：
  - `not_applicable_no_supplier_credit` — 净欠款连续为0（非制造业，如分众传媒），标记"不适用"
  - `insufficient_data_for_cagr` — 数据不足无法计算
- **`data_summarizer.py`**: dim7 新增 `reason` 字段透传给 QRV Agent，区分「不适用」vs「数据缺失」
- **`turtle-coordinator.md`**: 新增 dim7 reason 码说明

---

## v0.7.1 (2026-06-21)

### Fixed — 全链路8项同步修复 (v0.7.0 后补齐)

**审计发现**: v0.7.0 CQ 8维度上线后，以下 8 项文档/代码未同步：

#### P0 — 文档（版本号+维度数）
- `CONTEXT.md` L58: 「CQ 5维度」→「CQ 8维度」
- `CONTEXT.md` L64: 「现金质量5子维度」→「现金质量8子维度」
- `turtle-coordinator.md` L337: 「CQ 5维度表」→「CQ 8维度表」

#### P1 — 代码能力缺口
- **A7 应付周转占位符修复** (`data_summarizer.py`): 现金转化周期从 `total_liab` 近似 → 改用真实 `accounts_payable + notes_payable` 计算应付周转天数
- **A1 新增字段** (`data_summarizer.py`): yearly_data 新增 `accounts_payable_billion` / `notes_payable_billion` / `total_payables_billion`
- **A4 dim7 透传逐年比率** (`data_summarizer.py`): dim7 块新增 `yearly_ratios` 字段(净欠款/成本逐年值)，QRV Agent 可据此做行业绝对值判断
- **validate 字段缺失 WARNING** (`coordinator.py`): `_validate_raw_data()` 新增 v0.7.0 7 个可选字段缺失检测，记录 WARNING 提醒运维 `--full` 重拉
- **fin_exp 负值钳底** (`penetration_return.py`): `fin_exp = max(0.0, fin_exp)` 防止利息净收入反哺 PR（现金奶牛型公司 PR 虚高）

#### P2 — 行业阈值配置
- **`industry_profiles.yaml`**: 每个行业新增 `cq_thresholds.supplier_debt_ratio_max` (IT=0.30, 医药=0.35, 食品饮料=0.35, 电力=0.40, 房地产=0.60, 银行=null, 默认=0.40)

### Files Changed
- `docs/CONTEXT.md` — 版本号 + 维度数修正
- `backend/app/strategies/turtle/turtle-coordinator.md` — V1 维度数修正
- `backend/app/services/data_summarizer.py` — A1 + A4 dim7 + A7 修复 (~+35行)
- `backend/app/strategies/turtle/coordinator.py` — validate WARNING (~+15行)
- `backend/app/strategies/turtle/penetration_return.py` — fin_exp clamp (+1行)
- `backend/rules/v2/industry_profiles.yaml` — 6行业+默认 cq_thresholds
- `backend/app/core/config.py` — 版本号 0.7.0 → 0.7.1
- `backend/pyproject.toml` — 版本号 0.7.0 → 0.7.1
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 86/86 测试全部通过
- ✅ Linter 零错误

---

## v0.7.0 (2026-06-21)

### Added — 分红资金来源质量检测（CQ 8维度）

**问题**: 原有 CQ 5维度只检测现金质量本身，未检测分红的现金从哪来。低负债率公司可能通过借钱发债或压上游货款来维持高分红，这种风险在原有的60%负债率门槛和5年聚合 PR 中被平滑掉。

**方案（新增 CQ dim6-8 软门）**:

| 维度 | 公式 | 门槛 | 检测什么 |
|------|------|:--:|------|
| 6 FCF分红覆盖率 | count(FCF ≥ dividend_paid_cf, 5y) | ≥4/5 | 借钱发债分红？ |
| 7 供应商挤压 | (净供应商欠款/营业成本)CAGR − 营收CAGR | <10pp | 压上游货款撑现金流？ |
| 8 有息负债趋势 | 有息负债率3年变化 | <10pp | 杠杆在攀升？ |

**数据层（新拉8个资产负债表字段）**:
- `accounts_payable` / `notes_payable` → 供应商欠款
- `contract_liab` / `advance_receipts` → 区分健康预收款
- `st_borrow` / `lt_borrow` / `bonds_payable` / `noncurrent_liab_due_in_1y` → 有息负债精确计算

**规则第6条触发**: 新字段 → `--force` 全量重拉 → `--compute-only` 用新数据算

**改动的文件（11个）**:
- `tushare_client.py` — balancesheet fields +8
- `data_fetcher.py` — 提取8个新字段
- `cash_quality.py` — 新增 dim6/7/8 计算 + CAGR方向修复
- `coordinator.py` — dim_fail_stats 扩展到8维
- `data_summarizer.py` — A4/CQ 扩展到8维
- `turtle_cash_quality.yaml` — dim6-8 规则定义
- `turtle_coordinator.md` — Step 3/4 文档更新
- `turtle_qrv.yaml` — V1 CQ 表格 5→8维
- `test_cash_quality.py` — dim6-8 边界测试
- `test_spec_compliance.py` — 8维度合规测试

**效果（42候选池）**: CQ通过12/未通过30 → dim6(FCF分红覆盖)=25失败(最强信号), dim7(供应商挤压)=7失败, dim8(有息负债趋势)=0失败（说明Screener负债率<60%门槛已有效）

---

## v0.6.22 (2026-06-21)

### Fixed — 分析中间状态被跳过（computing/websearch 不可见）

**问题**: 点击分析后，前端只显示"正在拉取财务数据..."直接跳到"正在调用 LLM 分析..."，中间的 `computing`（计算 CQ+PR）和 `websearch`（搜索外部信息）阶段完全不可见。

**根因**: 轮询间隔 2 秒，而 `computing`（<0.5s 纯 CPU 计算）和 `websearch`（7 天缓存命中 <0.1s）两个阶段合起来不到 1 秒，全部发生在两次轮询之间，轮询抓到的最新状态已是 `analyzing`。

**修复（前端轮询加最小显示时长门控）**:
1. 新增 `STAGE_ORDER` 阶段顺序定义：`fetching → computing → websearch → analyzing`
2. 轮询检测到状态跨越 ≥2 级时（如 `fetching` → `analyzing` 跳过 `computing`+`websearch`），自动注入中间阶段
3. 每阶段至少显示 `MIN_STAGE_MS=1500ms`，通过 `setTimeout` 链式推进
4. 终态（done/error/timeout）立即显示，清除所有注入定时器
5. 相邻阶段推进（维护 ≥2s 轮询间隔 ≥ MIN_STAGE_MS）直接显示，不注入
6. 组件卸载时清理所有残留定时器

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — 加 `scheduleStageChain` + 轮询阶段跳过检测
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号 0.6.21 → 0.6.22
- `backend/pyproject.toml` — 版本号 0.6.21 → 0.6.22
- `backend/app/core/config.py` — APP_VERSION 0.6.21 → 0.6.22
- `frontend/package.json` — 版本号 0.1.0 → 0.6.22

### Verified
- ✅ TypeScript 零编译错误
- ✅ Linter 零错误

---

## v0.6.21 (2026-06-21)

### Fixed — 重新分析按钮"一直显示提交中"Bug (UX)

**问题**: 已生成报告的个股点击"重新分析"后，按钮一直显示"提交中..."，几分钟后直接跳到"提交LLM做分析"，中间拉数据/计算/搜索等阶段完全不显示。

**根因**:
1. `submittingRef` 锁的 `mutationFn` 提前 return 时仍触发 `onSuccess` → 产生假提交（前端以为任务已启动，但 POST 未发出）
2. `onSuccess` 在 POST 完成后才设初始状态（`fetching`），而 POST 期间按钮只有 `isPending` 支配 → "提交中..."
3. 按钮文字中 `isMutating` 优先级高于 `analysisStatus` → 即使进度数据已到，按钮仍显示"提交中..."

**修复（三处联动）**:
1. `submittingRef` 锁删除 + `onSuccess` → `onMutate`：初始状态在 mutationFn 执行前即设置，点击瞬间就看到"正在拉取财务数据..."
2. 轮询加 `not_started` 保护：后端还没返回时，轮询返回 `not_started` 不会覆盖 `onMutate` 设置的乐观 `fetching` 状态
3. 按钮文字优先级调换：`analysisStatus.message` > `isMutating`（两处按钮均修复）

**防双击升级**: 两处按钮的 `disabled` 条件均新增 `isMutating`，替代已删除的 `submittingRef`。

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — 删 `submittingRef` (+onMutate + 轮询保护 + 按钮文字优先级 + disabled)
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号 0.6.20 → 0.6.21
- `backend/pyproject.toml` — 版本号 0.6.20 → 0.6.21
- `backend/app/core/config.py` — APP_VERSION 0.6.18 → 0.6.21

### Verified
- ✅ TypeScript 零编译错误
- ✅ Linter 零错误

---

## v0.6.20 (2026-06-21)

### Added — PR 硬排除：可支配现金均值 ≤ 0 不入股池

**动机**: 川投能源、宁沪高速、赛轮轮胎、博源化工 4 只股票可支配现金5年均值为负（-49.71亿 ~ -5.39亿），但 PR=0 仍被放入股池排在末尾。这些公司过去5年根本没产生可供股东分配的现金流，分红靠举债或吃老本。

**改动（四件套）**:

① `coordinator.py` — 建池前硬排除:
- `pool.append()` 前新增检查：`pr_result.disposable_cash_avg <= 0` → `continue`（不写入 computed.yaml 也不入池）
- 新增计数器 `pr_excluded`，进度条、日志、StepResult 全部补上

② `rules/v2/turtle_pr.yaml` — 新增 `hard_exclusion` 段:
- 条件: `disposable_cash_avg <= 0`
- 原因: 公司无法产生可供股东分配的现金流

③ `turtle-coordinator.md` — Step 5 判定标准拆分:
- 硬排除（不入股池）: 可支配现金均值 ≤ 0
- 软门（标记不淘汰）: PR < 门槛 / CV ≥ 0.5 / 数据不足5年

④ `tests/test_spec_compliance.py` — 新增 2 个测试:
- `test_pr_excluded_disposable_cash_negative`: 单股负可支配现金 → 排除
- `test_pr_excluded_single_vs_multiple`: 混合场景 → 只保留正的

### Files Changed
- `backend/app/strategies/turtle/coordinator.py` — +6行 (硬排除 + 计数器 + 进度)
- `backend/rules/v2/turtle_pr.yaml` — +4行 (hard_exclusion)
- `backend/app/strategies/turtle/turtle-coordinator.md` — 更新 Step 5
- `backend/tests/test_spec_compliance.py` — +120行 (2个新测试)
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号
- `backend/pyproject.toml` — 版本号 0.6.19 → 0.6.20
- `.codebuddy/memory/2026-06-21.md` — 每日日志

### Verified
- ✅ 64/64 测试全部通过 (含新增 2 个硬排除测试)

---

## v0.6.19 (2026-06-21)

### Added — 分析按钮 6 态状态机 + 8 项防错机制 (UX 重大升级)

**动机**: 分析按钮只有「🔍 分析个股」和「⏳ 分析中...」两种状态，用户完全不知道是在拉数据/跑AI/完成了/报错了。

#### 六态按钮 (idle → submitting → processing → success → error → timeout)

| 状态 | 文字 | 样式 | 可点击 |
|------|------|------|--------|
| 空闲 (无报告) | `🔍 分析个股` | 蓝色实心 | ✅ |
| 空闲 (有报告) | `🔄 重新分析` | 蓝色边框+白底 | ✅ |
| 提交中 | `◌ 提交中...` | 蓝色+旋转圈 | ❌ |
| 处理中 | `◌ {阶段名}` | 蓝色+脉冲动画+进度条 | ❌ |
| 完成 | `✅ 分析完成，加载报告中...` | 绿色实心 | ❌ |
| 失败 | `⚠️ 分析失败，点击重试` | 红色边框+淡红底+错误框 | ✅ |
| 超时 | `⚠️ 分析超时，点击重试` | 红色边框+淡红底 | ✅ |

#### 8 项防错机制

| # | 机制 | 防止什么 | 实现 |
|---|------|---------|------|
| ① | `useRef` 本地锁 + `pointer-events:none` | 快速双击、disabled 穿透 | `submittingRef` + 500ms 冷却 |
| ② | Mount 时主动探活 `GET /analyze/status` | F5 刷新后状态丢失 | `useEffect([selectedStock])` 探活 |
| ③ | 连续轮询失败 ≥5 → 警告 | 网络断连导致假死 | `consecutiveFailures` 计数器 |
| ④ | 10 分钟超时检测 | 后台任务僵尸 | 15s 定时器检测 `startedAtMap` |
| ⑤ | error/timeout → retry 先清再发 | 旧错误消息残留 | `onClick` 中 `delete analysisMap[code]` |
| ⑥ | success 不按时间消失，等报告真实到位 | 闪完绿色但报告还没出 | done entry 仅在 `reportData` 到位时清理 |
| ⑦ | POST 失败 vs Task 失败分开展示 | 用户知道重试还是检查后端 | `_errType: 'mutation' | 'task'` |
| ⑧ | `visibilitychange` 回来即时刷新 | 切后台导致进度滞后 | 监听 + 主动 `GET /status` |

#### CSS 新增动画

- `@keyframes btnPulse` — 蓝色脉冲光晕 (processing 状态)
- `@keyframes successFlash` — 绿色缩放弹入 (完成状态)
- `@keyframes spin` — 按钮内旋转 spinner
- `@keyframes btnPulse` — 蓝色脉冲 (processing)

#### 样式新增类

- `.analyzeBtnProcessing` — 脉冲蓝
- `.analyzeBtnSuccess` — 绿色实心
- `.analyzeBtnError` — 红色边框 (可点击重试)
- `.analyzeBtnOutline` — 蓝色边框+白底 (有报告时的重新分析)
- `.buttonSpinner` — 旋转加载圈
- `.errorBox` — 红色错误详情框
- `.successBox` — 绿色完成框
- `.warningBox` — 黄色警告框
- `.phaseLabel` — 进度阶段描述

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — +120行 (状态机 + 8 项防错)
- `frontend/src/components/ReportViewer.module.css` — +130行 (6 态样式 + 动画)
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号
- `backend/pyproject.toml` — 版本号 0.6.18 → 0.6.19

### Verified
- ✅ TypeScript 编译通过 (`tsc --noEmit`)
- ✅ 后端 76/76 测试通过
- ✅ Linter 零错误

---

- 所有交互按钮添加 `:active` 伪类：`transform: scale(0.88~0.97)` 微缩反馈
- 覆盖范围：分析按钮、TOC 导航、引用返回、返回顶部、汉堡菜单、重试按钮（9 处）
- `analyzeBtn`/`retryBtn` 额外 `:active:not(:disabled)` + `box-shadow` 收缩

### Files Changed
- `frontend/src/components/ReportViewer.module.css` — 7 处 `:active` (+15行)
- `frontend/src/components/StockPool.module.css` — 2 处 `:active` (+5行)

---

## v0.6.17 (2026-06-21)

### Fixed — 分析任务状态机两处内存泄漏

1. **error 状态永不过期** (`stocks.py`):
   - error 状态 5 分钟后自动从 `_analysis_tasks` 清除（此前只清理 done）

2. **非终止状态卡死永久阻塞** (`stocks.py`):
   - 任何状态超过 30 分钟自动标记为僵尸任务，允许重新提交
   - 此前只有 done/error 放行，卡在 fetching/computing/websearch/analyzing 永久阻塞

### Files Changed
- `backend/app/api/stocks.py` — error 清理 + 30min 超时检测 (+13行)

---

## v0.6.16 (2026-06-21)

### Changed — 个人使用整体调优 (Personal-Use Polish)

**动机**: 审视个人使用阶段的问题，做 8 项不影响未来平台架构的优化。

#### P0 — 三刀

1. **结构性切除 LLM 开场白** (`ReportViewer.tsx`):
   - 删除 `stripLlmRole()` (7 条打地鼠正则) + `stripHeaderTitle()`
   - 新增 `stripPreamble()`: 找到第一个 `## ` 标题，之前内容全部丢弃
   - 不再需要猜 LLM 会说什么废话，只要 prompt 要求 `## ` 开始正文即可
   - 同时简化 header 渲染 + 移除 section 内的 `stripLlmRole` 调用

2. **日志始终可读** (`logging.py`):
   - `ConsoleRenderer` 不再仅 DEBUG 模式使用，始终输出人类可读格式
   - 个人使用不需要 JSON 日志

3. **Sidebar 版本号+日期动态化** (`Sidebar.tsx`):
   - 版本号从 `GET /api/health` 动态获取 (替代硬编码 `v0.6.7`)
   - 数据日期从 `GET /api/stocks/status` 动态获取 (替代硬编码 `2026-06-19`)

#### P1 — 三便利

4. **数据新鲜度端点** (`stocks.py`):
   - 新增 `GET /api/status` 返回 `turtle_pool.json` 最后修改时间
   - 缓存 TTL: 5min → 1h (个人用只有手动刷新才变)

5. **砍 3 个未用前端依赖** (`package.json`):
   - 移除 `react-router-dom`、`zustand`、`@tanstack/react-virtual`
   - 全项目搜索零 import，加回只需一条 `npm install`

6. **一键启动脚本** (`start.bat`):
   - 双击启动 backend + frontend，打开浏览器即可

#### P2 — 两增强

7. **键盘快捷键** (`StockPool.tsx`):
   - `↑↓` 浏览股池、`Enter` 选中、`Esc` 取消高亮

8. **分析任务自动清理** (`stocks.py`):
   - done 状态 5 分钟后自动从 `_analysis_tasks` 字典清除

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — 结构性切除 preamble (~ −15行)
- `frontend/src/components/Sidebar.tsx` — 版本号+日期动态化 (+20行)
- `frontend/src/components/StockPool.tsx` — 键盘快捷键 (+25行)
- `frontend/src/components/StockPool.module.css` — `.highlighted` 样式
- `frontend/package.json` — −3 个未用依赖
- `backend/app/core/logging.py` — ConsoleRenderer 始终可读
- `backend/app/api/stocks.py` — +/status 端点 + 缓存 TTL + 自动清理
- `backend/app/core/config.py` — 版本号 bump
- `backend/pyproject.toml` — 版本号 0.6.15 → 0.6.16
- `start.bat` — **新建** 一键启动脚本
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号更新

### Verified
- ✅ 不影响 SQLAlchemy/structlog/apscheduler/akshare/Jinja2 等未来架构件
- ✅ 后端测试通过

---

## v0.6.15 (2026-06-19)

### Fixed — 生产就绪·止血 Top 8 (CRITICAL)

**动机**: 代码审计发现 20 项代码卫生问题，筛选出 8 项真正能造成线上事故的「止血」项。

#### 1. 静默异常 (P0) — 7 处 `except: pass` → `logger.warning(..., exc_info=True)`
- `stocks.py` L82 (`_load_name_map` JSON 解析)、L145 (turtle_pool.json 读取)、L169 (qrv_analysis.json 评分)、L217 (raw_data.yaml meta)、L347 (computed.yaml)、L362 (qrv_analysis gates)
- `data_fetcher.py` L335 (缓存新鲜度检查)
- `data_summarizer.py` L500 (行业对标数据)
- **防止 v0.6.10 同类幽灵 Bug 再次发生**

#### 2. XSS 防护 (P0) — `rehype-sanitize`
- `ReportViewer.tsx`: `rehypePlugins` 新增 `rehypeSanitize`（放在 `rehypeRaw` 之后）
- 防止 LLM 输出中注入 `<script>` 等恶意 HTML

#### 3. 假端点修复 (P0) — `trigger_refresh` 返回 501
- `strategies.py` POST `/{strategy_id}/refresh`: 移除虚假 "刷新任务已提交" 消息
- 改为返回 HTTP 501 并告知正确调用方式

#### 4. 股池缓存误清 (P0) — 单股分析不再清空全局股池缓存
- `stocks.py` trigger 中：`_pool_cache["data"] = None` → 仅更新该股 `has_report`

#### 5. trace_id middleware (P0) — 每条 HTTP 请求自动注入 trace_id
- `main.py`: 新增 `trace_id_middleware`，调用 `set_trace_id()`
- 修复所有 API 日志匿名问题

#### 6. 硬编码路径归一化 (P1) — 7 处 `parent.parent.parent` → `settings.*_DIR`
- `stocks.py`: `CACHE_DIR` → `settings.STOCK_CACHE_DIR`
- `qrv_agent.py`: rules 路径 → `settings.RULES_DIR / "v2"`
- `coordinator.py`: rules 路径 → `settings.RULES_DIR`
- `data_summarizer.py`: industry_stats 路径 → `settings.STOCK_CACHE_DIR`, industry_profiles 路径 → `settings.RULES_DIR`
- `run_single_stock_analysis.py`: cache_dir → `settings.STOCK_CACHE_DIR`
- **连带修复**: `config.py` `RULES_DIR` 从 `app/rules/` → `backend/rules/` (此前为死路径)

#### 7. ts_code 输入校验 (P1) — 4 端点加 regex `\d{6}\.(SH|SZ|BJ)$`
- `stocks.py`: `GET /{ts_code}/analysis`, `POST /{ts_code}/analyze`, `GET /{ts_code}/analyze/status`, `GET /{ts_code}/gates`

#### 8. `.env.example` 补全 (P1)
- 新增 `TAVILY_API_KEY`, `CORS_ORIGINS`, `DEBUG`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`

### Files Changed
- `backend/app/core/config.py` — RULES_DIR 修复
- `backend/app/core/logging.py` — import uuid (已存在, 无改动)
- `backend/app/main.py` — 版本号 + trace_id middleware + health 版本
- `backend/app/api/stocks.py` — 7 处异常日志 + CACHE_DIR + ts_code 校验 + 缓存策略
- `backend/app/api/strategies.py` — trigger_refresh → 501
- `backend/app/services/qrv_agent.py` — rules_dir → settings
- `backend/app/services/data_fetcher.py` — L335 异常日志
- `backend/app/services/data_summarizer.py` — 2 处路径 + L500 异常日志
- `backend/app/strategies/turtle/coordinator.py` — rules_dir → settings
- `frontend/src/components/ReportViewer.tsx` — +rehype-sanitize
- `frontend/package.json` — +rehype-sanitize 依赖
- `backend/.env.example` — 补全 5 项
- `backend/pyproject.toml` — 版本 0.3.0 → 0.6.15
- `scripts/run_single_stock_analysis.py` — cache_dir → settings
- `CHANGELOG.md` — 本条目
- `docs/CONTEXT.md` — 版本号更新
- `.codebuddy/memory/2026-06-19.md` — 每日日志

---

### Fixed — 切换未分析股票时旧报告闪烁 Bug

**问题**: 点击未分析过的个股时，右侧先短暂显示上一只股票的报告（~3-4s），然后才跳回"暂无分析报告"。

**根因**: `ReportViewer.tsx` 的 `useQuery` 中 `placeholderData: (prev) => prev` 无条件保留上一次查询的数据。当 queryKey 从 `['analysis', '600519.SH']` 变为 `['analysis', '002555.SZ']` 时，placeholderData 将茅台报告暂存到 `reportData`，导致：
- `reportData !== null` → 跳过 loading 判断
- 渲染旧报告的 ReportContent（标题却是新股票名）
- API 404 + retry=1 → ~3-4s 后 `reportData=undefined` → 才显示"暂无分析报告"

**修复**: `placeholderData` 改为条件式——仅当 `prevQuery.queryKey[1]` 与当前 `selectedStock.ts_code` 一致时才保留旧数据，切换股票时返回 `undefined` 立即清空。

**效果**:
- 切换到未分析股票 → 显示"加载报告中..." → API 404 → "暂无分析报告"（无旧报告闪烁）
- 同股票重新分析 → 旧报告保留（UX 不丢失阅读位置）
- 不影响其他任何功能路径（StockPool 预加载、并行分析、竞态切换）

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — `placeholderData` 条件化（1 行 → 5 行）
- `CHANGELOG.md` — 本条目

---

## v0.6.13 (2026-06-19)

### Added — Playwright E2E 测试基础设施

**动机**: v0.6.12 修复的三连崩溃（白屏/卡死/闪烁）靠肉眼验证不可能每次改代码都回归一遍。需自动化冒烟测试前端核心路径。

**方案**: Playwright + `page.route()` 动态拦截，零 DeepSeek token 消耗。

**测试覆盖（13 个用例）**:

| 层 | 用例 | 关键验证 |
|---|------|---------|
| P0 冒烟 | 股池渲染 + 选股 → Gate → 报告 | ErrorBoundary 不触发 |
| P0 冒烟 | 切换股票不闪白 | `placeholderData` 生效 |
| P0 冒烟 | TOC 展开/折叠 | 报告目录可交互 |
| P0 并行 | 单股完整分析流程 (POST→轮询→done) | `setAnalysisMap` 多次更新不崩 |
| P0 并行 | 三股并行分析全流程 | 并发轮询不冲突 |
| P1 交互 | CQ PASS/FAIL 标签 | 颜色正确 |
| P1 交互 | cite 引用跳转 | 展开参考来源 → 定位到 ref-row |
| P1 交互 | API 500 → 错误 + 重试 | 错误状态正确渲染 |
| P1 交互 | 汉堡菜单 | 展开/折叠 |

**Mock 策略**:
- `page.route()` 浏览器内拦截所有 `/api/*` 请求，不连后端、不调 Tushare/Tavily/DeepSeek
- 多股并行测试用阶段计数器模拟 5 态状态机 (fetching→computing→websearch→analyzing→done)
- API 500 测试拦截 `/data/turtle_pool.json` 预加载防止缓存干扰

**运行**:
```bash
cd frontend && npm test          # headless 全量
npm run test:ui                   # UI 模式
npm run test:headed               # 有头浏览器调试
```

### Files Changed
- `frontend/tests/playwright.config.ts` — **新建** Playwright 配置
- `frontend/tests/e2e/mocks.ts` — **新建** mock 数据 (股池/Gate/报告)
- `frontend/tests/e2e/smoke.spec.ts` — **新建** P0 冒烟 5 用例
- `frontend/tests/e2e/multi-stock.spec.ts` — **新建** P0 并行分析 2 用例
- `frontend/tests/e2e/interactions.spec.ts` — **新建** P1 交互 6 用例
- `frontend/package.json` — `@playwright/test` 依赖 + test scripts
- `CHANGELOG.md` — 本条目

### Verified
- ✅ 13/13 全部通过 (36.4s)
- ✅ DeepSeek token: 0

---

## v0.6.12 (2026-06-19)

### Fixed — 🔴 前端崩溃三连：白屏 + 加载卡死 + 切换闪烁

**问题**: 
1. 多股并行分析时频繁白屏崩溃（Not​FoundError: removeChild）
2. 切换股票/重新分析时"加载报告中…"遮住所有内容
3. 点到已分析过的股票一片白色什么都不显示

**根因**:
- `injectCitationElements` 用原生 `replaceChild` 替换了 React 管理的 DOM 节点。每次轮询触发的 `setAnalysisMap` → 重渲染 → React reconcile 找不到被替换的节点 → 崩溃
- `useQuery` 无 `placeholderData`，切换/重分析时 `data` 变 `undefined` → 全屏遮罩
- `main.tsx` 无 `ErrorBoundary`，任何组件异常 = 全页白屏

**修复（P0+P1）**:
- 🔴 P0: 砍掉 `injectCitationElements` 全部原生 DOM 操作（~70 行），改用 `preprocessCitations()` markdown 字符串预处理 + `rehype-raw` 让 React 安全管理 `<cite>` 标签
- 🔴 P0: `main.tsx` 加 `ErrorBoundary` 类组件，崩溃时显示错误信息 + 重载按钮
- 🟡 P1: analysis `useQuery` 加 `placeholderData: (prev) => prev`，保持旧报告不闪烁
- 🟡 P1: `reportLoading` 分支加 `!reportData` 条件 + Gate 展示，不再全屏遮罩
- 🟡 P1: `setAnalysisMap` 加浅比较，状态不变时返回相同对象引用，减少 80% 无意义重渲染
- 🟡 P1: `TrRenderer` 新增 `<cite>` 元素检测，自动为参考来源行设 `ref-row` id
- 移除：`lastCiteEl` 状态、`contentRefs` ref、`registerContentRef`、`scrollBackToCite`、浮动"返回引用"按钮

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — 约 100 行净删减（砍 ~80 行原生 DOM 操作，+~20 行安全替代）
- `frontend/src/main.tsx` — +35 行 ErrorBoundary
- `frontend/package.json` — 新增 `rehype-raw` 依赖
- `CHANGELOG.md` — 本条目

---

## v0.6.11 (2026-06-19)

### Fixed — 前端多股并行分析追踪：analysisStatus 单例 → analysisMap 字典

**问题**: 分析股票 A 时点击股票 B，B 显示假"分析中 0%"(analysisStatus 被残留状态污染)。多股无法并行追踪进度。

**根因**: `analysisStatus` 为全局单例 `useState`，不区分 ts_code。轮询 `useEffect` 依赖 `selectedStock`，切换股票时前一股的轮询立即中断。

**修复**:
- `analysisStatus` 单例 → `analysisMap: Record<string, AnalysisEntry>` 字典，按 ts_code 隔离
- 轮询从 `useEffect([selectedStock, ...])` → 持久 `setInterval`（useRef 避 dep churn），每 2s 并行 `Promise.allSettled` poll 所有 active 任务
- `currentStatus` 从 `analysisMap[selectedStock.ts_code]` 派生，自动跟随当前选中股
- `analyzeMutation` 的 `onSuccess/onError` 写入 `analysisMap` 对应 ts_code key
- 分析完成 800ms 后自动清理 done entry（避免 `analysisMap` 无限膨胀）

### Files Changed
- `frontend/src/components/ReportViewer.tsx` — 约 70 行重构 (3 处 replace)
- `CHANGELOG.md` — 本条目

**构建**: `tsc --noEmit` + `vite build` 全部通过 ✅

---

## v0.6.10 (2026-06-19)

### Fixed — 个股分析按钮卡 0% 的静默崩溃 Bug

**问题**: 前端点击「🔍 分析个股」后一直显示"分析中 0%"，后端 data 目录不生成任何报告。

**根因**: `_run_analysis_background()` 的 except 块中 `from app.core.logging import get_logger` → **ImportError**（`logging.py` 不存在 `get_logger` 函数）。后台任务发生异常后，错误处理代码立刻抛出 ImportError，整个异步任务静默崩溃，状态永远卡在 `fetching, 0%`。

**修复**:
- 顶部新增 `import asyncio, logging`；移除 `BackgroundTasks` 依赖
- `_run_analysis_background()`: 新增启动日志 + 状态更新日志；except 块改用 `logging.getLogger(__name__)`
- `trigger_stock_analysis()`: `BackgroundTasks.add_task()` → `asyncio.create_task()` 确保异步任务可靠调度

### Files Changed
- `backend/app/api/stocks.py` — import + get_logger → logging + task 调度方式修复
- `CHANGELOG.md` — 本条目

**测试**: 76/76 全部通过 ✅

---

## v0.6.9 (2026-06-19)

### Added — 重新分析按钮对接个股分析流水线

**问题**: 前端"🔍 分析个股"/"🔄 重新分析"按钮调 `POST /api/stocks/{ts_code}/analyze` 但后端只清缓存 → 空壳。个股分析必须手动 `python scripts/run_single_stock_analysis.py`。

**方案**: 后端加后台任务 + 前端加轮询进度。

**后端 `stocks.py`**:
- `trigger_stock_analysis()`: 加 `BackgroundTasks` 参数 → 启动 `_run_analysis_background()` 异步执行全流程
- 新增 `_analysis_tasks` 内存字典追踪 6 态状态机 (fetching/computing/websearch/analyzing/done/error)
- 新增 `GET /{ts_code}/analyze/status` 轮询端点，前端 2 秒一次查进度
- 防止重复提交：运行中的任务直接返回 `"分析任务已在运行中"`

**后端 `coordinator.py`**:
- 新增 `run_single_stock_full()`: 封装 Step 0-5 全流程（获取名称 → 拉取数据 → CQ+PR → qrv_input → WebSearch → QRV Agent）
- 支持 `status_callback` 回调实时更新进度

**前端 `ReportViewer.tsx`**:
- 新增 `analysisStatus` state + `useEffect` 轮询 loop
- 无报告状态: 进度条 + 阶段文字 (拉取数据/计算中/搜索中/LLM分析中)
- 有报告"重新分析"按钮: 禁用态 + 进度条 + 错误提示
- `ReportViewer.module.css`: 新增 `.progressBarWrap` / `.progressBar` / `.progressLabel`

### Files Changed
- `backend/app/api/stocks.py` — 重写 trigger + 状态追踪 + status 端点 (~70行)
- `backend/app/strategies/turtle/coordinator.py` — 新增 run_single_stock_full (~100行)
- `frontend/src/components/ReportViewer.tsx` — 轮询 + 进度UI (~80行)
- `frontend/src/components/ReportViewer.module.css` — 进度条样式
- `CHANGELOG.md` — 本条目

---

## v0.6.8 (2026-06-19)

### Fixed — 后端启动卡住 (启动时遍历 44 目录读 YAML)

**问题**: uvicorn 启动时 `stocks.py` 模块级 `_build_stock_index()` 遍历 44 个缓存目录读 `raw_data.yaml` → 启动"卡在 CLI"。用户早已要求只读 `turtle_pool.json`。

**修复**:
- 删除 `_stock_index` / `_INDEX_READY` / `_build_stock_index()` / `ensure_index()` 整段
- 换为 `_load_name_map()`: 只读 `turtle_pool.json` 一次构建 `ts_code → name` 映射
- `_find_stock_dir()`: 从 name + ts_code 直拼路径，不存在才兜底扫描目录名（不读 YAML）
- `get_stock_pool()`: 直接用 `name + ts_code` 拼路径检查 `has_report` / `scores`
- 删除 `StockPoolItem` 重复的 `scores` 字段

**效果**: 启动不再遍历目录/读 YAML，uvicorn 秒开；股池仍从 `turtle_pool.json` 读取。76 测试全过。

### Files Changed
- `backend/app/api/stocks.py` — 删内存索引 + 换 JSON 映射 + 删重复字段
- `CHANGELOG.md` — 本条目

---

## v0.6.7 (2026-06-19)

### Changed — Sidebar 图标栏 + 汉堡手动切换

**问题**: Sidebar 缩进后完全消失(8px)，无图标栏；"股池"纯文字不直观。

**改动**:

① **Sidebar 图标栏**:
- 缩进宽度 8px → 56px，保留 Logo A 图标 + 策略图标居中排列
- `Sidebar.tsx`: 新增 `collapsed` prop，缩进时隐藏文字只显示图标
- `Sidebar.module.css`: 新增 `.collapsed` 模式样式（居中对齐、去除左边框）

② **汉堡图标替代"股池"**:
- `StockPool.tsx`: "股池" h2 → 三条杠 SVG 汉堡图标按钮
- `StockPool.module.css`: 新增 `.hamburger` 样式（32px 透明按钮，hover 高亮）
- 点击汉堡 → 手动切换侧边栏展开/缩进

③ **双控制并行**:
- `Layout.tsx`: 新增 `sidebarCollapsed` 手动 state + `handleToggleSidebar`
- 选股 → 自动缩进（`setSidebarCollapsed(true)`）
- 汉堡 → 手动 toggle（`setSidebarCollapsed(prev => !prev)`）
- 悬停 → 临时展开，离开后恢复

### Files Changed
- `frontend/src/components/Layout.tsx` — 手动/自动双控制
- `frontend/src/components/Layout.module.css` — 缩进宽度 56px
- `frontend/src/components/Sidebar.tsx` — collapsed prop + 条件渲染
- `frontend/src/components/Sidebar.module.css` — collapsed 图标栏样式
- `frontend/src/components/StockPool.tsx` — 汉堡图标组件 + onToggleSidebar prop
- `frontend/src/components/StockPool.module.css` — hamburger 按钮样式
- `CHANGELOG.md` — 本条目

---

## v0.6.6 (2026-06-19)

### Fixed — 三个 UI Bug

- **Bug 1 图标**: Sidebar 策略图标 emoji(🐢🚀)→SVG 线性图标
- **Bug 2 重复点击**: 点击已选中个股→不再取消选中
- **Bug 3 闪旧报告**: ReportViewer 移除 keepPreviousData

---

## v0.6.5 (2026-06-19)

### Changed — 前端 7 项 UX 优化

**① Sidebar 自动收起+悬浮弹出**:
- 点击个股后 Sidebar 自动收起 (width=0)，鼠标靠左边缘 8px 触发条悬浮弹出
- `Layout.tsx`: 新增 `sidebarHovered` 状态，通过 `onMouseEnter/Leave` 控制折叠
- `Layout.module.css`: 新增 `.sidebarWrapper`/`.collapsed`/`.sidebarTrigger` 样式

**② 标题去重**:
- 移除组件硬编码 H1 中的"QRV 深度分析报告"
- 新增 `stripHeaderTitle()` 过滤 LLM 输出的 `# 标题` 行

**③ 过滤 LLM 角色内容**:
- 新增 `stripLlmRole()` 正则过滤 "好的，收到您的指令。作为一名拥有15年A股..." 等角色陈述段落
- 应用于 header 和所有 section 内容

**④ 表格边框/排版/对齐优化**:
- `border-collapse: collapse` + 外边框加深 `var(--border-strong)`
- 表头底线 2px + 表头背景 `#f0f3fa`
- 所有 td 统一 `text-align: left`
- 斑马纹增强 + hover 高亮

**⑤ 跳转高亮动画**:
- `scrollToSection()`: 目标 section 添加 `.sectionHighlight` 2 秒渐变动画
- `handleCiteClick()`: 引用跳转兜底滚动（找不到行时滚动到来源 section）

**⑥ 超链接修复**:
- `mdComponents` 新增 `a` 组件：外部链接 `target="_blank" rel="noopener noreferrer"`
- 引用跳转延迟 250ms→350ms 确保 expand 动画完成

**⑦ 个股下方弹出打分卡**:
- `StockPool.tsx`: 选中行下方展开行内嵌 `ScoreCard`，新增 `useQuery` 拉取 gates
- `ScoreCard.tsx`: 新增 `compact` 属性，StockPool 内嵌时更紧凑
- `ScoreCard.module.css`: 新增 `.compact` 模式样式
- `StockPool.module.css`: 新增 `.expandedRow`/`.expandedInner` 展开动画

### Files Changed
- `frontend/src/components/Layout.tsx` — Sidebar 折叠+悬浮
- `frontend/src/components/Layout.module.css` — 折叠样式
- `frontend/src/components/ReportViewer.tsx` — 去重标题+过滤LLM角色+跳转高亮+超链接
- `frontend/src/components/ReportViewer.module.css` — 表格+动画+链接样式
- `frontend/src/components/StockPool.tsx` — 打分卡展开行
- `frontend/src/components/StockPool.module.css` — 展开行动画
- `frontend/src/components/ScoreCard.tsx` — compact 属性
- `frontend/src/components/ScoreCard.module.css` — compact 样式
- `CHANGELOG.md` — 本条目

---

## v0.6.4 (2026-06-19)

### Fixed — Pool 零延迟 + 切换白屏根治 (CRITICAL UX)

**问题**: 股池首次加载读 43 目录 × 86 YAML 文件 → 2-3s；茅台→海康→茅台切换白屏。

**根因分析**:
1. Pool API 放着现成的 `turtle_pool.json` 不读，偏要遍历 43 目录解析 86 YAML
2. `_read_yaml()` 定义在 `_build_stock_index()` 调用之后 → 启动时 NameError 被 try-except 吞掉，索引中的 `name`/`industry` 全是目录名兜底
3. React Query 默认 `gcTime=5min` 缓存过期后回收 → 切回旧股票需重新请求
4. 无 `placeholderData` 切换时旧报告立即消失 → 闪白
5. `injectCitationElements` DOM 操作无卸载守卫 → 竞态崩溃

**修复**:

① **Pool API 直接读 turtle_pool.json** (`stocks.py`):
- 43 目录遍历 + 86 YAML 解析 → 单次 `json.load("turtle_pool.json")`
- `has_report` 从内存索引 O(1) 补上
- 首次请求: 2-3s → <10ms

② **修复 `_read_yaml` 定义顺序** (`stocks.py`):
- 移到 `_build_stock_index()` 之前，消除 NameError

③ **gcTime: Infinity** (`main.tsx`):
- 缓存永不回收，切回任意股票秒出

④ **placeholderData + key 防白屏** (`ReportViewer.tsx`):
- `placeholderData: keepPreviousData` — 切换时保留上一只报告
- `key={tsCode}` — ReportContent 强制干净重建
- `mountedRef` — injectCitationElements 卸载守卫

### Files Changed
- `backend/app/api/stocks.py` — Pool 读 turtle_pool.json + _read_yaml 顺序修复
- `frontend/src/main.tsx` — gcTime: Infinity
- `frontend/src/components/ReportViewer.tsx` — placeholderData + key + mountedRef
- `CHANGELOG.md` — 本条目

---

## v0.6.3 (2026-06-19)

### Changed — 性能三件套 + 打分卡 (MAJOR UX)

**根因**: 点个股→报告出现 需 2 次 HTTP 请求 + 后端每次遍历 43 个目录读盘 = 可感知卡顿。打分卡数据其实在 `qrv_analysis.json` 里但只存在于折叠的报告章节中。

**① 后端内存索引 — O(1) 目录查找**:
- `_build_stock_index()`: 启动时扫描一次目录, 构建 `ts_code → {name, dir, has_report}` 索引
- `_find_stock_dir()`: 遍历 43 目录 → O(1) 索引查表
- Pool API: 复用索引遍历, 新增 `has_report` 字段

**② 个股 endpoint 缓存**:
- `/gates`: + 内存缓存 TTL=10min (不再每次读盘)
- `/analysis`: + 内存缓存 TTL=10min
- `/analyze` 触发时清除对应缓存

**③ 前端悬停预加载**:
- `StockPool.tsx`: `onMouseEnter` 250ms 延迟后 `queryClient.prefetchQuery` 预加载 gates + analysis
- 有报告才预加载 (`has_report=true`), 无报告不浪费请求
- 悬停=数据已就绪, 点击=0ms 渲染

**④ 新增 ScoreCard 打分卡**:
- `ScoreCard.tsx` + `ScoreCard.module.css`: 报告顶部 9 维度打分卡, 默认展开
- 三组 (Q质量/R韧性/V估值) 分组展示, 每组含子维度进度条
- `GateResult` 新增 `scores` 字段

**⑤ 修复 React Query staleTime**:
- Pool: 显式 `staleTime=5min` (之前依赖全局默认=0 → 切 Tab 就重新请求)

### Files Changed
- `backend/app/api/stocks.py` — 内存索引 + 缓存 + has_report + scores
- `frontend/src/types.ts` — StockPoolItem.has_report + GateResult.scores + QrvScores 扩展
- `frontend/src/components/StockPool.tsx` — hover 预加载
- `frontend/src/components/ScoreCard.tsx` — **新建** 打分卡
- `frontend/src/components/ScoreCard.module.css` — **新建**
- `frontend/src/components/ReportViewer.tsx` — 集成 ScoreCard
- `frontend/src/components/Sidebar.tsx` — v0.6.1→v0.6.3
- `CHANGELOG.md` — 本条目

---

## v0.6.2 (2026-06-18)

### Fixed — 前端白屏 + 加载慢修复
- **CSS 高度链**: `html`/`body` 加 `height: 100%`，`#root` 改 `height: 100%` + `min-height: 100vh`，修复布局塌陷导致白屏
- **Pool API 缓存**: `get_stock_pool` 加内存缓存 (TTL=5min)，避免每次请求读 86 个 YAML 文件
- **前端错误处理**: StockPool 组件加 `isError`/`refetch` 支持，显示错误信息和重试按钮

---

## v0.6.1 (2026-06-18)

### Fixed — 全量 Tushare 字段审计 + 3 大 Bug 修复 (CRITICAL)

**根因**: 全量审计发现 7 个数据问题 — fields 缺失导致数据丢失 + 归一化误伤百分比 + 字段名错误

**B1: 6 个 API 补全 fields 参数** (`tushare_client.py`):
- `get_income()`: 显式指定 16 个字段 (含 `int_income`)
- `get_balance_sheet()`: 显式指定 14 个字段 (含 `total_cur_assets/liab`)
- `get_cashflow()`: 显式指定 15 个字段 (含 `n_cash_flows_fnc_act`, `n_disp_subs_oth_biz`, `c_pay_dist_dpcp_int_exp`)
- `get_fina_indicator()`: 显式指定 7 个字段 (含 `current_ratio`, `quick_ratio`)
- `get_dividend()`: 显式指定 4 个字段 (含 `payout_ratio`)
- `get_daily_basic()`: 显式指定 9 个字段
- 修复前: 不传 `fields` 依赖 Tushare 默认返回子集 → `financing_cf`/`acq_subsidiary`/`payout_ratio` 100% 为 0

**B2: 归一化 Bug 修复** (`data_fetcher.py`):
- `_normalize_to_yi()`: 所有字段无差别 ÷1e8 → 新增 `NON_MONETARY` 白名单
- 白名单: `gross_margin`, `net_margin`, `roe`, `eps`, `revenue_yoy`, `net_profit_yoy`, `debt_ratio`, `current_ratio`, `quick_ratio`
- 修复前: 茅台毛利率 91.18% → 缓存 9.12×10⁻⁷ → QRV 显示 0.0%
- 修复后: 百分比/比率/EPS 不再被归一化

**B3: 字段名修正** (`data_fetcher.py`):
- `n_cashflow_fin_act` → `n_cash_flows_fnc_act` (Tushare 官方字段名, 筹资活动现金流量净额)

**B4: 遗漏实现** (`data_fetcher.py`):
- `gross_profit`: 硬编码 0.0 → `revenue - oper_cost`
- `volatility_1y`: 硬编码 0.0 → 年化波动率 (252 日对数收益率 std × √252 × 100%)

### Migration Notes
- **必须 `--full` 全量重拉** raw_data.yaml（字段集变更 + 归一化白名单修复）
- 顺序: `--full` 全量拉取 → `--compute-only` 重算

---

## v0.6.0 (2026-06-18)

### Phase C — 代码质量加固

**C2: `rule_version` 默认值 "v1" → "v2"**
- `cash_quality.py`: 构造函数默认 `rule_version="v2"`，避免静默降级

**C7: 股票名拉取失败加 WARNING**
- `run_single_stock_analysis.py`: Tushare `stock_basic` 失败时打印 `[WARN]`

**C6: 回购数据按年聚合**
- `data_summarizer.py` A3: 回购从"取前5条"改为"按年份分组求和"，与分红聚合逻辑对齐

**C1: 删除破损的 HTML 渲染**
- `run_single_stock_analysis.py`: 移除对不存在的 `render_qrv_html` 模块的调用 + 未定义变量 `entry`，占位 TODO

**C5: `.env` 化选股器阈值**
- `config.py`: 新增 8 个 `TURTLE_MIN_*` / `TURTLE_MAX_*` setting 字段
- `screener.py`: 构造函数从 `settings` 读取阈值，替代硬编码类变量
- `.env`: 新增对应的 8 个配置项

**C3: 提取公共 `find_stock_dir`**
- 新增 `utils.py`: 独立函数 `find_stock_dir(cache_dir, ts_code)`
- 删除 3 处重复实现: `coordinator.py`, `qrv_agent.py`, `run_single_stock_analysis.py`

### Phase B — 数据完整性

**B1: WebSearch 缓存复用**
- `coordinator.py` `_run_websearch`: 7 天缓存命中直接返回，新增 `force` 参数
- `run_single_stock_analysis.py`: 新增 `--force-websearch` 标志

**B2: PE/PB/股息率历史分位**
- `data_fetcher.py`: `valuation_history` 新增 `dv_ratio` 字段
- `data_summarizer.py`: 新增 `_a8_valuation_percentile()` 方法，计算 5 年 PE/PB/股息率分位点（p5/p25/median/p75/p95 + 当前百分位）
- `_rate_valuation`: 引用 A8 数据提升 V2 维度评分

**B3: 行业对标数据**
- `coordinator.py` `_compute_industry_stats`: 全量刷新后按行业计算 PE/ROE/股息率/毛利率/负债率中位数，写入 `industry_stats.yaml`
- `data_summarizer.py` `_load_industry_stats`: 加载行业对标并注入 `A6_valuation_snapshot`

---

## v0.5.3 (2026-06-18)

### Fixed — 治本：入口归一化 + 12 处单位换算 Bug

**核心改动: 数据入口归一化** (`data_fetcher.py`):
- 新增 `_normalize_to_yi()`: 写入 raw_data.yaml 前将所有金额统一为亿元
- 财务三表: 元 → 亿元 (÷1e8); total_share: 万股 → 亿股 (÷1e4)
- dividend total_dividend: 万元 → 亿元 (÷1e4); repurchase_amount: 万元 → 亿元 (÷1e4)
- 百分比值 (roe/gross_margin/dv_ratio) 和 ratio 值 (pe/pb) 不动

**修复 12 处单位换算 Bug** (`data_summarizer.py`):
- A1: 所有 `_billion` 字段去掉 `/1e8`（已归一化为亿元）
- A3: `total_dividend_billion`/`total_dividend_5y_billion`/`amount_billion`/`total_repurchase_billion` 去掉 `/1e8`
- A3: `r.get("amount")` → `r.get("repurchase_amount")` (key 名不匹配导致回购全 0)
- A3: 分红按财年聚合（5 条记录 → 5 个财年），不再因每年多次分红而只覆盖 3 年
- A5: `disposable_cash_*_billion`/`total_dividend_5y_billion`/`repurchase_cancellation_billion` 去掉 `/1e8`
- A5: `risk_free_rate_pct`/`spread_pct` 去掉 `×100`（存储时已是 %）
- A6: `total_mv_billion` 去掉 `/1e8`（已亿元）；`dividend_yield_pct` 去掉 `×100`（Tushare 已是 %）
- `_sf()`: 新增 `field_name` 参数，None 时 WARNING 日志防止静默归零

**简化 PR 公式** (`penetration_return.py`):
- 去掉 `B=1e8`/`dc_b`/`td_yuan`/`rp_b` 四个单位换算变量
- PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%（全部亿元直接算）

**`risk_free_rate` 配置修复** (`coordinator.py`):
- 默认值从硬编码 2.5 → 读取 `settings.TURTLE_RISK_FREE_RATE`（.env 配置 1.7%）

**文档同步**:
- `turtle_qrv.yaml`: `max_tokens` 16384 → 32768
- 新增 `docs/TUSHARE_UNITS.md`: 每个 Tushare 端点的原始单位 + 归一化规则
- 更新 `docs/CONTEXT.md`/`turtle-coordinator.md`/`rules/v2/turtle_pr.yaml`

### Migration Notes
- **必须 `--full` 全量重拉** raw_data.yaml（归一化后的金额与旧缓存不兼容）
- 顺序: `--full` 全量拉取 → `--compute-only` 重算

---

## v0.5.2 (2026-06-18)

### Fixed — 数据完整性 + 双文件夹 + 截断三大修复

**修复 1: Tushare 全量字段拉取** (`tushare_client.py` + `data_fetcher.py`):
- `tushare_client.py`: `get_income`/`get_balance_sheet`/`get_cashflow` 去除 `fields` 限制，全量拉取全部字段（此前只拉 ~40/~300 字段）
- `data_fetcher.py` `fetch_single_stock()`: 新增费用端字段 (sell_exp/admin_exp/rd_exp/total_profit/oper_cost/int_income)、流动资产/流动负债、c_pay_dist_dpcp_int_exp
- `data_fetcher.py`: 新增 `net_margin` 计算 (优先 fina_indicator.netprofit_margin → 兜底 net_profit/revenue*100)
- 解决 QRV 报告中净利率全列 N/A 的问题
- ⚠️ 字段名修正: Tushare income 全量返回的是 `sell_exp`/`admin_exp`/`oper_cost`/`rd_exp`，非 `less_selling_exp`/`less_manage_exp`/`operate_cost`

**修复 2: 双文件夹 Bug** (`coordinator.py` + `qrv_agent.py` + `run_single_stock_analysis.py`):
- 根因: raw_data.yaml 写在 `{ts_code}/`, computed.yaml 写在 `{name}_{ts_code}/` → `_build_qrv_input` 找不到 computed，CQ/PR 数据全部丢失
- `_find_stock_dir`: 优先级反转 — 先匹配 `{name}_{ts_code}` (有 computed), 再 fallback `{ts_code}`
- `run_single_stock_analysis.py`: computed.yaml 写入 `stock_dir/` 而非新建 `{name}_{ts_code}/`

**修复 3: LLM 输出截断** (`config.py` + `qrv_agent.py`):
- `config.py`: `LLM_MAX_TOKENS` 8192→32768（报告 ~300 行 + 25 URL 参考来源，之前 8192 严重不够）
- `qrv_agent.py`: 新增 `finish_reason=="length"` 截断检测，截断时 WARNING 日志 + 报告中标记 `truncated: true`
- `timeout` 120→300s

**修复 4: ✕100 二次放大 Bug** (`data_summarizer.py`):
- `gross_margin_pct`/`net_margin_pct`/`roe_pct`: raw_data 中已是百分比值（91.18 即 91.18%），代码再 ×100 → 9118%
- 改为 `round(value, 1)` 直接使用

**Enhancement** (`data_summarizer.py` + `run_single_stock_analysis.py`):
- A1 新增费用率: `sell_exp_to_revenue_pct`/`admin_exp_to_revenue_pct`/`rd_exp_to_revenue_pct`
- A1 新增费用绝对额: `sell_exp_billion`/`admin_exp_billion`/`rd_exp_billion`/`total_profit_billion`/`operate_cost_billion`/`fin_exp_billion`
- `run_single_stock_analysis.py`: 新增 `--force` 标志支持强制重拉 + `utf-8` stdout 修复 Windows GBK emoji 编码
- 所有 76 测试通过

### 验证 (600519.SH 贵州茅台)
- raw_data: 13年 × ~50字段 = ~650数据点 (之前 ~25字段/年)
- net_margin: 50.5%~52.7% 全13年可用 (之前全部N/A)
- 参考来源: 25个URL完整输出 (之前截断只剩1个)
- CQ: PASS (5维度全部通过) | PR: 2.85% PASS
- 文件夹: 仅 `600519.SH/` (无双份)

---

## v0.5.1 (2026-06-18)

### Fixed — 三个 Bug 修复 + URL 证据链

**Bug 1: 总市值 N/A** (`_a6_valuation_snapshot`):
- 根因: `total_mv` 在 Tushare daily_basic 接口中已以亿元为单位, 代码再除以 1e8 导致显示为 0.0
- 修复: 添加单位自适应逻辑 (> 1e7 则视为亿元, 否则按元换算)

**Bug 2: PR 穿透回报率 213%** (`_a5_pr_detail`):
- 根因: `computed.yaml` 中 `pr` 和 `threshold` 已存储为百分比形式 (2.13 = 2.13%), 代码再 × 100 导致二次放大
- 修复: 去掉 × 100, 改为直接 `round(pr_val, 2)`

**Enhancement 1: 人均薪酬搜索** (`turtle_qrv.yaml` R2 websearch):
- 新增关键词: 「人均薪酬 应付职工薪酬」, 修复 R2 人才结构表中人均薪酬总是 N/A 的问题

**Enhancement 2: URL 证据链** (`data_summarizer.py` + `turtle_qrv.yaml`):
- `data_summarizer.py`: 新增 `_build_reference_index()` 方法, 从 websearch 提取所有 snippet URL 索引 (W-q-1, W-r1-3 等)
- `turtle_qrv.yaml` prompt: 报告末尾新增「参考来源」章节要求, [W-*] 标记 → 对应 URL 映射表
- 所有 76 测试通过

---

## v0.5.0 (2026-06-18)

### Changed — QRV Agent v3: 分析框架扩展 + DataSummarizer v2 (MAJOR)

**根因**: v0.4.0 报告仍有"薄"感——DataSummarizer 只提取 25% 原始数据, A2 透传不做提取, 缺少生意本质/人才结构/增长引擎等深度维度

**框架扩展 (P0)**:
- **Q1 扩展生意本质分析**: 卖什么/怎么卖/上下游/收款方式(应收周转天数)/轻资产vs重资产(固定资产占比)
- **Q3 新增增长引擎**: 增长驱动拆分(量×价)、第二曲线进度、CAPEX/折旧比率(扩张/维持/吃老本)
- **Q2 新增护城河可攻破性**: 技术颠覆风险/跨界竞争/护城河变宽还是变窄
- **R2 合并人才结构**: 员工总数/研发人员占比/人均创收/人均薪酬
- **R1 新增国家战略定位**: 十四五/十五五/国产替代/信创
- **综合打分卡**: 8模块 → 10维度

**DataSummarizer v2 (P0-1)**:
- **A1 扩展**: 9字段 → 20+字段 (EPS/FCF/CAPEX/营业利润/商誉/商誉占比/固定资产占比/应收周转天数/存货周转天数/折旧/CAPEX折旧比/流动比率/速动比率)
- **A7 新增生意属性**: 收款方式(advance_or_near_cash/normal_credit/extended_credit) + 资产类型(light/medium/heavy) + CAPEX模式(expansion/maintenance/underinvesting)
- **Layer 3 数据充分性评估**: 每维度 rich/partial/missing 三级评级, LLM 拿到后知道哪些跳过

**WebSearchExtractor (P1-1)**:
- **新文件**: `websearch_extractor.py` — 规则引擎从 websearch 预提取 7 类结构化事实(收入/市占率/管理层/行业/人才/政策/供应链)
- 不调用 LLM (零成本零延迟), 纯正则匹配

**行业配置文件 (P1-2)**:
- **新文件**: `rules/v2/industry_profiles.yaml` — 定义 IT设备/银行/医药/食品饮料/电力 等行业特有指标
- DataSummarizer 按行业动态适配 (银行→不良率, 制造业→产能, IT→研发人员)

**Prompt 大改 (P0-3+P1-3)**:
- `turtle_qrv.yaml` v2→v3: Q1扩展 + Q3新增 + R2人才 + 护城河可攻破性 + 国家战略 + data_sufficiency使用指引
- WebSearch R2新增人才结构关键词
- 盈利趋势表从6行→13行 (20+字段)

**P2: DataSummarizer 按行业动态加载**: `_load_industry_profile()` + `_extract_industry()` + 模糊匹配

### Files Changed
- `backend/app/services/data_summarizer.py` — v1→v2: A1 20+字段 + A7 + Layer3 + P2行业加载 (~450行)
- `backend/app/services/websearch_extractor.py` — **新增** (280行, 7类规则提取器)
- `backend/rules/v2/industry_profiles.yaml` — **新增** (100行, 7行业+默认)
- `backend/rules/v2/turtle_qrv.yaml` — v2→v3: 框架+prompt全面扩展
- `backend/app/services/qrv_agent.py` — 版本号更新 + _build_prompt接入extractor
- `backend/app/strategies/turtle/turtle-coordinator.md` — Step 7.5新增 + Step 8更新
- `docs/CONTEXT.md` — v0.4.0→v0.5.0, 模块说明更新
- `.codebuddy/rules/rules.md` — 第9条更新(输入侧+输出清单)
- `CHANGELOG.md` — v0.5.0条目

---

### Changed — QRV Agent v2: 定量升级 (MAJOR)
- **根因**: v0.3.0 QRV 报告「虚」—— LLM 输出缺乏具体数字和报道支撑，如"收入来源多元化"无任何具体金额/占比/增速
- **三大根因修复**:
  1. 数据截断：`_build_prompt()` 中 `max_chars=30000` 截断 122K 数据 → **移除截断，改为结构化摘要**
  2. Prompt 模糊：只要求"定性分析结论" → **全面重写**，每模块强制输出量化表格（12张强制表格）
  3. WebSearch 关键字不足 → 新增收入结构、分红回购、行业规模等专项搜索
- **新增 `data_summarizer.py`**: 预处理引擎，从 raw + computed + websearch 提取 6 个结构化摘要块 (A1-A6)
- **Prompt 升级**: `turtle_qrv.yaml` v1→v2，约 1500 字强制量化模板，包含：
  - 核心铁律: 无数字不结论、无来源不引用、表格优于段落、数据缺失就声明
  - 12 张强制表格: 收入结构表、盈利趋势表、护城河指标表、风险清单表、管理层画像表、分红回购表、股权结构表、CQ 5维度表、资产负债快照、估值快照、PR计算表、三情景预估
- **`qrv_agent.py`**: 引入 DataSummarizer 预处理 → 不截断原始数据 → LLM 拿到完整 websearch + 结构化摘要
  - `_build_prompt()`: 不再 `yaml.dump` 后截断，改为 `data_summary.yaml + websearch.yaml + financials_recent.yaml` 三合一
  - `_call_llm()`: max_tokens 8192→16384, temperature 0.1→0.2
- **WebSearch 增强**: 每次搜索从 2 个 keywords → 2-3 个，新增收入结构、竞争格局、分红回购等
- **`rules.md`**: 新增第 9 条「LLM 输出：不虚不飘，数字说话」
- **文档同步**: CONTEXT.md / turtle-coordinator.md / CHANGELOG.md 全部更新

### Files Changed
- `backend/rules/v2/turtle_qrv.yaml` — prompt v1→v2, websearch 增强
- `backend/app/services/data_summarizer.py` — **新增** (260行)
- `backend/app/services/qrv_agent.py` — 去截断 + summarizer + max_tokens 16384
- `backend/app/strategies/turtle/coordinator.py` — 版本号 v0.3.0→v0.4.0
- `backend/app/strategies/turtle/turtle-coordinator.md` — Step 8 重写
- `docs/CONTEXT.md` — 版本号 + 数据流更新
- `.codebuddy/rules/rules.md` — 新增第 9 条

---

## v0.3.1 (2026-06-18)

### Fixed — PR v2 CV 软门代码未实现
- **Bug**: `turtle_pr.yaml` gate_type 已为 soft，但 `penetration_return.py` 中 CV 仍为硬门（`return result` 提前返回），导致 CV ≥ 0.5 的公司跳过 Step 2 分红/回购计算，`total_dividend_5y` 停留在默认值 0.0
- **Root Cause**: v0.3.0 软门改造未同步到代码层 CV 子门逻辑
- **Fix**:
  - `penetration_return.py`: CV 检查不再 `return`，改为设置 `PRResult.cv_warning = True`，继续执行后续 Step 2-4
  - `PRResult` 新增 `cv_warning: bool = False` 字段
  - `to_computed_format()` 输出新增 `cv_warning` 字段
  - `turtle_pr.yaml`: CV 注释「硬门」→「软门」
- **Tests**: `test_cv_gate_rejects` 更新为软门语义（CV≥0.5 标记警告，继续计算 PR）
- **测试**: 62/62 全绿

---

## v0.3.0 (2026-06-17)

### Changed — QRV 综合分析框架 (MAJOR)
- **CQ/PR 门**: 硬门 → **软门**（标记不淘汰），判定结果交 QRV Agent 综合研判
- **QRV Agent**: 新建设计，取代原 Step 8（基本面门）+ Step 9（估值门）
  - Q (Quality): 商业模式 + 护城河
  - R (Resilience): 外部环境 + 管理层 + 控股结构
  - V (Valuation): 价值陷阱 + 历史分位 + 压力测试
  - **单次 LLM 调用**，输出定性结论（不打分 A-F）
- **WebSearch**: 从预留接口 → **5次 Tavily 搜索**（Q商模+护城河、R1外部、R2管理层、R3控股、V估值）
- **统一数据包**: `qrv_input.yaml` 整合 raw_data + computed + screener + gate_results + websearch
- **配置清理**: 移除 Brave 搜索，只保留 Tavily

### Changed — 流程重排
- 原 Step 6-10 → 缩减为 Step 6-8
- 原 Step 8 基本面门 + Step 9 估值门 → 合并到 Step 8 QRV Agent
- 原 Step 10 报告生成 → 整合到 QRV Agent 输出

### Added
- `rules/v2/turtle_qrv.yaml` — QRV 分析框架规则
- `app/services/qrv_agent.py` — QRV Agent 服务（含 CLI 入口）
- `data/stock_cache/{ts_code}/qrv_input.yaml` — 统一数据包
- `data/stock_cache/{ts_code}/qrv_analysis.md` — Markdown 报告
- `data/stock_cache/{ts_code}/qrv_analysis.json` — 结构化报告

### Changed — 版本号升级
- 全局: `0.2.1` → `0.3.0` (pyproject.toml / main.py / config.py / CONTEXT.md)
- 规则: `v2` 不变（v0.3.0 继续使用 rules/v2/）

### Changed — coordinator.py
- `run_full_refresh()`: CQ/PR 不再淘汰 (`continue` 移除)，所有计算完成股入池
- `analyze_single_stock()`: 真实实现 Step 6-8
- `_build_qrv_input()`: 整合所有数据源
- `_run_websearch()`: 5次 Tavily 搜索
- `_run_qrv_analysis()`: 单次 LLM 调用

### Fixed — 版本号一致性修复 (2026-06-17 晚)
- **Bug**: `coordinator.md` + `config.py` + `coordinator.py` + `qrv_agent.py` + `test_spec_compliance.py` 共 8 处标注 `v3`，但实际 rules/ 只有 `v1/` 和 `v2/`，所有代码硬路径加载 `v2`
- **Fix**: 全部改回 `v2`，与 rules/v2/ 目录一致
- **screener.py**: 注释修正（11→10条件, v1→v2, 条件编号去重）
- **测试**: 62/62 全绿

### Fixed — 12项审视问题全面修复 (2026-06-17 夜)
- **P0-1**: `pyproject.toml` 加 `aiohttp` 依赖
- **P0-2**: `qrv_agent.py` 规则路径 `parent.parent` → `parent.parent.parent`
- **P0-3**: `coordinator.py` emoji `✅` → `[Done]`
- **P0-4**: `qrv_agent.py` CLI emoji + LLM 占位符 emoji 替换
- **P0-5**: **代码去重** — coordinator 删除 `_build_qrv_prompt()` / `_call_llm()` / `_default_qrv_prompt()` (~170行)，`_run_qrv_analysis()` 改为委托 `QRVAgent.analyze_async()`
- **P1-6**: 前端 `StockDetail.tsx` 4门→2门（删除 fundamental/valuation，CQ/PR hard→false，新增 QRV 摘要区）
- **P1-7**: API `stocks.py` GateResult 移除 fundamental/valuation，新增 qrv_summary；StockPoolItem 新增 cq_passed/pr_passed
- **P2-8**: `turtle-coordinator.md` emoji 置信度→ASCII
- **P2-9**: `CONTEXT.md` emoji 置信度→ASCII
- **P2-10**: `screener.py` 11→10条件注释（已完成于上一轮）
- **P2-11**: `cash_quality.py` docstring "硬门判定"→"软门标记"
- **P2-12**: `run_single_stock_analysis.py` L80 v3→v2
- **额外**: `coordinator.py` _tavily_search emoji→NONE
- **测试**: 62/62 全绿

---

## v0.2.1 (2026-06-17)

### Fixed — PR v2 数据链路修复 (CRITICAL)
- **`coordinator.py`**: `run_full_refresh()` 新增 `force` 参数，透传给 `fetch_candidate_data()`，修复 `--force` 不重拉个股缓存的 Bug
- **`run_turtle_refresh.py`**: `--force` 标志正确传递到 coordinator
- **`tushare_client.py`**: `get_income()` / `get_balance_sheet()` / `get_cashflow()` 显式指定 `fields`，确保 PR v2 所需的 `fin_exp`、`lt_eqt_invest`、`c_pay_acq_const_fiolta`、`n_disp_subs_oth_biz` 字段被正确拉取
- **`data_fetcher.py`**: `_safe_float()` 增加 `field_name` 参数，字段缺失时输出 WARNING 日志，防止 `None → 0.0` 静默兜底

### Root Cause
v0.2.0 PR v2 升级后，API 调用未指定 `fields` + `--force` 未真正重拉 → 所有个股缓存仍为 v1 格式 (2026-06-15) → PR v2 新增的 4 个扣除项被 `_safe_float(None)` 静默兜底为 0 → PR 系统性高估 (=PR v1)

### Docs — 文档修正 + 全量重拉 (2026-06-17)
- **`turtle-coordinator.md`**: Step 3 PR 公式从 v1 旧版改为指向 Step 5 v2 公式，消除文档内同一定义重复且矛盾的歧义
- **`CONTEXT.md`**: 版本号 v0.2.0 → v0.2.1
- **全量重拉**: `--force` 刷新全部 40 只候选股缓存，验证 v2 字段 (fin_exp / lt_eqt_invest / capex / acq_subsidiary) 完整写入 `raw_data.yaml`
- **验证结果**: 候选40 → CQ通过27 → PR通过16，股池 PR 2.73%~6.14%
- **测试**: 55/55 全绿

---

## v0.2.0 (2026-06-17)

### Changed — PR v2 穿透回报率公式升级
- **可支配现金**: 3年均值 → 5年逐期计算
- **扣除项**: 2项 → 5项（新增: 并购子公司 / 长投净增 / 财务费用）
- **CV 硬门**: `可支配现金_CV < 0.5`，过滤大起大落
- **分配比率**: 总额/总额方案（CV门消除大年偏差）
- **字段修正**: `c_pay_for_tan_il` → `c_pay_acq_const_fiolta` (Tushare正确字段名)
- **字段重命名**: `interest_expense` → `finan_exp`
- **新增字段**: `fin_exp`(income), `lt_eqt_invest`(bs), `n_disp_subs_oth_biz`(cf)

### Changed — 版本统一
- 全局版本号: `0.1.0` → `0.2.0` (pyproject.toml / main.py / config.py / CONTEXT.md)
- 规则版本: `v1` → `v2` (config.py / coordinator.py / coordinator.md)
- `.env.example` 脱敏 + 默认值同步

### Changed — 代码注释修正
- screener.py 注释与实际阈值对齐（上市年限 > 8年 / 市值 > 200亿）

### Added
- `CHANGELOG.md` — 版本变更记录
- `rules/v2/` — 规则 v2 目录（turtle_pr / turtle_cash_quality / turtle_screener）

### Fixed
- `.env.example` 安全: 移除真实 API Key

---

## v0.1.0 (2026-06-15)

### Initial Release

- FastAPI + React 18 全栈投资策略分析网站
- **龟龟策略**: 类红利股选股框架，四门筛选
  - 现金质量门 (CQ, 硬门) — 5子维度
  - 穿透回报率门 (PR, 硬门) — 确定性计算
  - 基本面门 (软门, LLM) — 6模块
  - 估值门 (软门, LLM) — 4步流程
- Mixed Coordinator 模式: `turtle-coordinator.md` 流程定义 + `coordinator.py` 编排执行
- Tushare 数据源 + YAML 本地缓存
- SQLite 数据库 + Alembic 迁移
- 规则版本化: `rules/v1/`
- 选股器: 10条件筛选（ST排除 / 强周期排除 / 上市年限 / 市值 / ROE / PE / 股息率 / 毛利率 / 负债率 / PB）
