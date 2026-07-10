# Investment Strategy — 长期记忆

## v1.2.1 VerifyAgent 冲突阈值 + ReportAgent 级联修正展示 (2026-07-10)
- **Bug 1**: `_aggregate_rounds()` 弱冲突(score=2)多轮一致→strong 错判为 overturned。修复: 仅 ≥1轮=3分 + ≥2轮有冲突 → strong
- **Bug 2**: `_render_report()` 不展示 CounterAgent 修正信息(original_sentiment/causality_note)。修复: 新增 sentiment 变更 + 级联裁决原因展示
- **改动文件**: verify_agent.py, report_agent.py, pyproject.toml(1.2.0→1.2.1), CHANGELOG.md
- **测试**: 208/208 ✅

## v1.2.0 ScreeningAgent 精选推荐 (2026-07-10)
- **动机**: v1.1.0 LLM 一次性处理 201 只股票超时 → 程序化兜底无假设命中 → 50 只纯财务排名。用户要的是"15-20 只精选龙头覆盖上下游"。
- **新架构**: 程序化预筛+分段+全量财务预排(Stage1) → LLM 分段精选每段挑 6 只(Stage2) → 三维打分+分段排名(Stage3)
- **关键设计决策**:
  - 代表公司强制豁免候选池（仅第一层，不复杂化）— 解决财务排名排除战略重要股
  - purity_estimate 程序化营收比例计算（不浪费 LLM token）
  - 下游排他关键词：模组/SSD/分销优先级归 downstream（修复 v1.1.0 江波龙/佰维存储错归 mid）
  - LLM prompt 从"穷举分类"改为"精选挑选"——从 18-25 只候选挑 5-8 只
  - LLM failure → 程序化取财务 top K 兜底
- **config**: `PROSPERITY_SCREENING_TOP_PER_SEGMENT=6`
- **改动文件**: screening_agent.py(重写), screening_direction_prompt.md(重写), screening_scorer.py(+1字段), report_agent.py(+1列), config.py, pyproject.toml(1.1.0→1.2.0), test(2适配), CHANGELOG
- **测试**: 208/208 ✅

## v1.1.0 假设树感知分赛道筛选 + 验证诊断展示 (2026-07-09)
- **动机**: 股池混排无法区分核心/蹭概念；合成报告漏修正陈述；LLM方向匹配超时/随机
- **新建**: `tools/screening_scorer.py` — 假设权重计算器(causality_strength=broken→0) + 三维打分(景气适配/风险暴露/质量)
- **重写**: `screening_agent.py` — 4阶段→3阶段(LLM分类+标记命中→程序化三维打分→分段排名)
  - LLM 任务从「打分0~1」改为「分类到环节+标记命中了哪些假设+关联占比估计」
  - 假设树全部层级(L0-L3)参与命中判断，不再仅L3
  - `purity_estimate` 三层折扣：混血公司景气适配×0.18→自然下沉不硬排除
- **重写**: `screening_direction_prompt.md` — 输出从score/matched_l3→segment/positive_hits/negative_hits/purity_estimate
- **修改**: `report_agent.py` — 每条假设推理链后加「验证诊断」(因果链强度+修正陈述+验证说明)；股池拆三张分段表(上游/中游/下游)
- **改动文件**: screening_scorer.py(新), screening_agent.py(重写), screening_direction_prompt.md(重写), report_agent.py(+60行), test_prosperity_coordinator.py(2测试适配), pyproject.toml, CHANGELOG.md
- **测试**: 208/208 ✅ | 版本: v1.0.5→v1.1.0

## v1.0.5 ScreeningAgent 消费 chain_model Phase 6 (2026-07-09)
- **动机**: ScreeningAgent 签名已预留 chain_model 但 _llm_direction_match() 未注入
- **改动**:
  - 新增 `_format_chain_context()` — 3 块方向匹配专属上下文（代表公司正例锚点 / 环节描述股票分类参考 / 瓶颈校准规则）
  - `_llm_direction_match()` + `chain_model=None` → 注入 `{chain_context}`
  - `screen()` Stage 1 透传 `chain_model`
  - `screening_direction_prompt.md` + `{chain_context}` 占位符 + 2 条链感知规则（代表公司锚定 / 瓶颈校准）
- **不动**: `_compute_purity()`（确定性关键词路径无 LLM）、`purity_scorer.py`（主路径确定性代码，LLM 回退 <1% 不值扩接口）
- **设计决策**: 只改 Stage 1 方向匹配不碰 Stage 2 纯度打分；chain_model=None 时返回占位文本零影响
- **改动文件**: screening_agent.py(+55), screening_direction_prompt.md(+8), CHANGELOG.md, pyproject.toml
- **版本**: v1.0.4 → v1.0.5 | 测试: 208/208 ✅
- **Wiki-Centric 五大 Agent 消费状态**: HypothesizeAgent ✅ | VerifyAgent ✅ | CounterAgent ✅ | ScreeningAgent ✅ | LearningAgent (Producer)
- **后续**: B 路线 — 实战验证跑一次完整 Pipeline 验证全链效果；C 路线 — 收敛性实验 #3 量化 Wiki-Centric 架构稳定性改善

## v1.0.4 CounterAgent 消费 chain_model + prompt 模板化 Phase 5 (2026-07-09)
- **动机**: CounterAgent 签名已预留 chain_model 但未注入，prompt 全部硬编码无模板
- **改动**:
  - 新增 `counter_cascade_prompt.md` 模板（~110行），继承原规则 + `{chain_context}` 占位符 + 链感知裁决指引
  - 新增 `_format_chain_context()` — 从 YAML 提取 6 块级联裁决专属上下文（瓶颈/供需/技术/级联规则）
  - `_build_cascade_prompt()` 从硬编码迁移到模板 .format()，新增 `_build_fallback_prompt()` 降级
  - `_llm_cascade()` + `cascade()` 透传 chain_model
- **设计决策**: 不做 VerifyAgent 式原子化（级联裁决=全局链级语义，不可逐假设原子化）。LLM 仍做语义法官，上下文从"盲人摸象"→"产业链全景地图"
- **改动文件**: counter_agent.py(+170/-95), counter_cascade_prompt.md(新增), CHANGELOG.md, pyproject.toml
- **版本**: v1.0.3 → v1.0.4 | 测试: 208/208 ✅
- **后续**: ScreeningAgent 消费 chain_model（签名已预留但未实际消费）

## v1.0.3 VerifyAgent Q5 链适配度深度重构 Phase 4 (2026-07-09)
- **动机**: brainstorming 确认 v1.0.2 仅占位符插入不够——Q1-Q4 规则链无感知，chain_context 是"参考书"不是"评分标准"
- **方案 C（修正版）**: 产业链拓扑从"参考书"升级为"评分标准"，5 个问题 + 5 个修正
  - Q1: 环节对口优先 — 先判断假设对应环节 → 只算涉及该环节的信源
  - Q2: 参考 tracking_indicators.meaning + supply_demand.overall_judgment 方向
  - Q3: 瓶颈校准 — bottleneck high/critical + 国产化率<30% → 反例上行校准；反例不涉瓶颈 → 最高 1 分
  - Q4: 情感联动 — 与 bottleneck level 联动（砍掉"信号放大效应"不可操作化部分）
  - Q5 chain_fit（新增）: aligned / misaligned（2 档非 3 档），只影响 confidence ±1 级，不影响 status
- **关键设计决策**:
  - chain_fit misaligned ≠ status 降级（避免旧知识惩罚新信息）
  - Q5 2 档（非 3 档）减少 LLM 自由度
  - Q2 不依赖 tracking_indicators.expected_direction（YAML 中无此字段），改用 meaning 文本
- **改动文件**: verify_prompt.md(全量重写), verify_agent.py(_synthesize_status/confidence + _aggregate_rounds + _parse_verification_result + _format_chain_context), test_prosperity_coordinator.py(+6), CHANGELOG.md, pyproject.toml
- **版本**: v1.0.2 → v1.0.3 | 测试: 208/208 ✅
- **后续**: CounterAgent 消费 chain_model → 已完成 v1.0.4
- **实现**:
  - `_format_chain_context(chain_model)` — YAML→prompt 文本（照 HypothesizeAgent 同逻辑，各 Agent 自包含）
  - chain_model 串入 `_verify_chain_with_llm()` 和 `_generate_counter_queries()`
- **prompt 模板**: verify_prompt.md + counter_query_prompt.md 均新增 `{chain_context}` 占位符
- **效果**: Q1 信源对口判断 / Q2 数据对齐参考 tracking_indicators / Q3 反例冲突结合国产化率校准 / 反例搜索词定向化
- **版本**: v1.0.1 → v1.0.2 | 测试: 204/204 ✅
- **改动文件**: verify_agent.py, verify_prompt.md, counter_query_prompt.md, CHANGELOG.md, pyproject.toml
- **后续**: CounterAgent 消费 chain_model (v1.0.3) + CounterAgent prompt 内嵌→模板文件

## v1.0.1 HypothesizeAgent 消费 chain_model Phase 2 (2026-07-09)
- **动机**: Phase 1 签名预留了 chain_model 但 3 个 prompt builder 均未注入，假设生成完全依赖搜索片段
- **实现**: 
  - `_format_chain_context(chain_model)` — YAML→prompt 文本（7 板块：产业链结构/瓶颈视图/供需格局/技术路径/跟踪指标/使用规则），chain_model=None 时返回空字符串
  - chain_model 串入 `_form_single_round` / `_phase1_skeleton` / `_phase2_fill` → 3 个 `_build_*_prompt()` 消费
- **prompt 模板**: 3 个模板（hypothesize/hypothesize_phase1/hypothesize_phase2）均新增 `{chain_context}` 占位符
- **效果**: L3 锚定 representative_companies / L0 围绕供需矛盾 / bottleneck 环节更多假设 / key_indicators 参考 tracking_indicators
- **版本**: v1.0.0 → v1.0.1 | 测试: 204/204 ✅
- **改动文件**: hypothesize_agent.py, hypothesize_prompt.md, hypothesize_phase1_prompt.md, hypothesize_phase2_prompt.md, CHANGELOG.md, pyproject.toml

## v1.0.0 Wiki-Centric 架构 Phase 0+1 (2026-07-09)
- **动机**: wiki 被当管道末端归档 — LearningAgent 产出的产业图谱（价值链/瓶颈/公司）无 agent 消费，CounterAgent 连 history 都没有
- **Phase 0**: 新增 `industries/{name}.yaml` 伴生文件协议（chain/bottlenecks/supply_demand/technology_paths/tracking_indicators）；LearningAgent.learn() → tuple(md, yaml_dict)
- **Phase 1**: Coordinator 新增 `_load_chain_model()`；4 agent 签名加 `chain_model=None`；CounterAgent 补 `history` 参数
- **关键决策**: HypothesizeAgent / VerifyAgent / CounterAgent 如何消费 YAML 构建分析飞轮 **待详细讨论**（另案），Phase 1 仅做签名预留
- **版本**: v0.23.7 → v1.0.0 | 测试: 204/204 ✅ | Spec v0.24 §11
- **改动文件**: learning_agent.py, learning_prompt.md, coordinator.py, hypothesize_agent.py, verify_agent.py, counter_agent.py, screening_agent.py, 存储芯片.yaml(新), CHANGELOG.md, pyproject.toml, config.py, test_prosperity_coordinator.py, spec, plan

## v0.23.6 成分股超限交互式子板块推荐 (2026-07-08)
- **动机**: `screening_agent.py` 硬截断 `[:50]` 丢掉 55% 成分股，且截断无序。不能用财务预筛替代（误杀景气早期优质标的）。
- **方案**: 交互式子板块推荐 — 概念成分股超过 `PROSPERITY_SCREENING_THRESHOLD`(=50) 时，rapidfuzz 搜索子概念 + 用户选择或全量分析
- **新增**:
  - `concept_index.py`: `suggest_subconcepts(main_name)` — rapidfuzz 搜索 + 成分股数过滤 + 排除自身
  - `coordinator.py`: `check_industry_size(industry_name)` — 预检+推荐
  - `config.py`: `PROSPERITY_SCREENING_THRESHOLD: int = 50`
- **修改**:
  - `screening_agent.py`: 删除硬截断 `[:50]`
  - `run_prosperity_ai.py`: 重构为完整 CLI 工具（`--force-full` 跳过交互）
- **版本**: v0.23.5 → v0.23.6

## v0.23.5 ConceptIndex 概念板块本地索引 (2026-07-08)
- **新增**: `concept_index.py` — Tushare `ths_index(type=N)` 全量拉取 (409个概念板块) + rapidfuzz 模糊搜索
  - `build(force)`: 全量构建 → `data/concept_index.yaml` (24h TTL)
  - `search(name)`: rapidfuzz WRatio 模糊搜索，中文友好
  - `resolve(name)`: 一键搜索+获取成分股 (ths_member)
- **集成**: `industry_metrics.py` `get_industry_ts_codes()` 新增信源0 (ConceptIndex 优先)
- **依赖**: +rapidfuzz ^3.14.0, pyproject: 0.23.4→0.23.5
- **设计决策**: ConceptIndex 是基础设施组件，不进入 Wiki。Wiki 是 LLM 研究报告，ConceptIndex 是 API 元数据缓存
- **测试**: 204/204 ✅

## v0.23.3 概念板块构建器升级 Bocha 主搜索 (2026-07-08)
- **问题**: `concept_builder` 仍硬编码用 Tavily，未跟随 SearchAgent 的 Bocha 升级 → 人工智能概念板块漏掉兆易创新(603986.SH)等关键标的
- **修复**: 新增 `_detect_engine()` (Bocha>Tavily>none) + `_bocha_search()` (对齐 SearchAgent 参数)；`search_concept_stocks()` 引擎分发，Bocha 失败降级 Tavily
- **副作用**: 删除 `data/prosperity/concept_boards/人工智能.yaml` 旧缓存，下次运行自动用 Bocha 重建
- **改动**: concept_builder.py, pyproject.toml, CHANGELOG.md
- **测试**: 204/204 ✅ | 版本: v0.23.2→v0.23.3

## v0.23.2 纯度分全 0 Bug 修复 (2026-07-08)
- **问题**: 所有股票 purity_score 全为 0.00% — `investment_implication` 是 dict 而非 str，`_extract_l3_keywords()` 中 `re.split()` 对 dict 抛 TypeError，被 `_compute_purity()` 静默吞掉
- **修复**: 
  - 新增 `_flatten_field()` — 安全处理 dict/str/None 三种类型，dict 时拼接 values 为字符串
  - `_extract_l3_keywords()` + `_llm_direction_match()` + `_llm_match_fallback()` 三处统一使用
  - `_compute_purity()` 异常处理新增 `traceback.format_exc()` 日志
- **改动**: purity_scorer.py, screening_agent.py, CHANGELOG.md, pyproject.toml
- **测试**: 204/204 ✅ | 版本: v0.23.1→v0.23.2

## v0.23.1 CounterAgent 安全网：防止 partial/unverified 被误杀 (2026-07-08)
- **问题**: 「人工智能」行业 CounterAgent LLM 将 3 条 partial/unverified 误判为 overturned → 级联屠杀 L2/L3 → 股池=0
- **修复**: 双重保护机制
  - LLM prompt: 新增「绝对禁止」章节 — partial/unverified 绝不 overturned；disputed 区分方向反转(强)vs程度变化(弱)
  - 代码安全网: `_apply_cascade()` 程序化拦截 keep_unreachable + partial/unverified → 强转 downgrade_confidence
  - 硬编码兜底: `_hardcoded_cascade()` 用方向反转关键词(缩减/转负/萎缩)判定 disputed→overturned
  - 配置化: `PROSPERITY_COUNTER_TIMEOUT` 替代硬编码 120s
- **改动**: counter_agent.py, config.py, pyproject.toml, CHANGELOG.md, spec v0.22→v0.23
- **测试**: 204/204 ✅ | 版本: v0.23.0→v0.23.1 | pyproject: 0.22.0→0.23.1

## v0.23.0 Bocha 中文搜索 + 截断解除 (2026-07-08)
- **动机**: 上轮 brainstorming 分析 — 67% 零信源率，Tavily 中文覆盖弱占 30%，截断占 20%
- **Bocha API**: `POST https://api.bochaai.com/v1/web-search`，Bearer 认证，返回 summary 详细摘要
- **search_agent.py**: 新增 `_bocha_search()` / `_detect_engine()` (Bocha > Tavily)；去重截断 500→10000 字符
- **hypothesize_agent.py**: 新情报解除 300 字截断，旧情报保持 500 字
- **config.py**: +BOCHA_API_KEY，版本 0.21→0.23；.env + .env.example 新增
- **测试**: 204/204 ✅ | 用户需在 https://open.bochaai.com/dashboard 获取 Key 填入 .env

## v0.22.0 精确分类级联：强反例推翻 vs 弱反例降级 (2026-07-07)
- **问题**: 「人工智能」12 条假设仅 1 条真正强反例(H1-2)，却因 Q3 布尔逻辑 + 级联误杀导致 8 条 unreachable
- **方案 C**: Q3 三级分级(none/weak/strong) + 多轮一致原则 + weak_disputed 降级不切链
- **verify_agent.py**: Q3 聚合布尔→三级；`_synthesize_status` 入参 conflict_level(str)；新增 weak_disputed 状态；cascade 切链集合移除 disputed
- **counter_agent.py**: LLM prompt 更新；`_hardcoded_cascade` 切断集合 `{overturned, unreachable, disputed}` → `{overturned, unreachable}`
- **verify_prompt.md**: Q3 评分分级说明，强调不要把"侧面对比"打到 2/3 分
- **report_agent.py**: SIGNAL_MAP +weak_disputed 映射；status_map +🟡
- **coordinator.py**: CounterAgent 日志 +weak_disputed 统计
- **Spec**: `docs/specs/2026-06-29-prosperity-strategy-design.md` → v0.22
- **测试**: 204/204 ✅ | 版本: v0.14.1→v0.22.0

## v0.21.2 LLM 超时快速失败机制 (2026-07-06)
- **问题**: 07-05 实验全超时，每次 7.5 分钟才退出（3 轮总计 22+ 分钟）
- **根因**: `_call_llm_phase1` 硬编码 30s 超时无视 `.env` + 超时被吞掉触发多层 fallback
- **修复**: 
  - 新增 `LLMUnavailableError` → Timeout/ConnectionError 直接抛异常，不 fallback
  - `_call_llm_phase1` 超时读 settings（修复硬编码 bug）
  - `_phase1_skeleton`/`_phase2_fill`/`form_hypotheses` 全部 propagate 异常
  - `convergence_experiment.py` 检测失败立即终止实验
  - `.env`: `deepseek-v4-pro-202606` → `deepseek-v4-flash`
- **效果**: Phase 1 全超时从 450s → 45s 后退出；Phase 2 从 300s → 60s 后退出
- **测试**: 200/200 ✅ | 版本: v0.21.1→v0.21.2 | pyproject: 0.14.0→0.14.1

## 分段验证工具 (v0.21.1, 2026-07-05)
- `scripts/segmented_verify.py` — 支持 `--record` / `--step {hypothesize|verify|counter|screening|report} --runs N` / `--all`
- `backend/app/strategies/prosperity/tools/checkpoint.py` — CheckpointStore 管道中间状态持久化
- Record: 全流程一次，拦截 Tavily + counter query → 存全部 6 个 checkpoint
- Replay: 从 checkpoint 注入上游 + 缓存回放 Tavily → 仅重放目标 Agent N 次 → 对比稳定性
- 所有磁盘/DB 写入 mock，不污染生产数据
- 改哪个 Agent 就只验证哪段，节省 70-90% 时间

## v0.20.0 收敛性实验 #2：3轮投票不足，49 处差异反而恶化 (2026-07-05)
- 在 v0.20.0（VerifyAgent 3轮投票）落地后重跑收敛实验：49 处差异（v0.19=42 处）
- **Tavily 缓存 100% 命中**（14/14），外部输入冻结确认有效
- **新增波动源**：HypothesizeAgent（12 vs 14 假设）、CounterAgent（overturned 6→2）、ScreeningAgent（0→0→23 stocks）
- verified_sentiment 在 3 次 outer run 间也不稳定（H2-2: positive→negative→positive）
- 报告：`backend/data/prosperity/raw/人工智能/convergence_report.md`
- 下一步：HypothesizeAgent self-consistency + CounterAgent 软衰减 + Screening 不依赖精确 status

## v0.20.0 P0 VerifyAgent 多轮投票稳定性增强 — 设计阶段 (2026-07-05)
- 收敛性实验证实 temperature=0 仍不收敛（42 处差异），根源在 VerifyAgent LLM 单轮输出不稳
- 选择 **Plan A**（仅修 VerifyAgent，不碰 CounterAgent），下游零影响
- 核心方案：3 轮并行 LLM（Self-Consistency），字段级聚合
  - Q1: `supporting_source_indices` 3 轮交集 → 过滤幻觉
  - Q2: `data_alignment` 3 轮众数 → 保留 LLM 语义
  - Q3: `counter_conflict_score` 0-3 分级 + 3 轮 MAX → 安检逻辑
  - sentiment: 3 轮众数 → `verified_sentiment`
- 关键决策：Q3 用 MAX 不用 median（安检不漏检），Q1 用交集不用 median（LLM 易多数不会漏数），Q2 保留 LLM 不程序化（需语义判断"结构性分化"）
- _synthesize_status/_synthesize_confidence 规则不变，只输入来源变
- Spec: `docs/specs/2026-07-05-prosperity-stability-p0.md`
- Plan: `docs/plans/2026-07-05-prosperity-stability-p0.md`
- 改动文件：verify_prompt.md + verify_agent.py + test_prosperity_coordinator.py（仅 3 个核心文件，~230 行）
- 不受影响：counter_agent.py, coordinator.py, report_agent.py, screening_agent.py, 前端, 龟龟

## v0.19.1 P0/P1 wiki 锚定 + 搜索防覆盖 (2026-07-04)
- **P0**: VerifyAgent 之前完全没吃到 wiki 历史上下文（HypothesizeAgent 吃到了），导致两次运行间 source_count/data_alignment/counter_conflict 剧烈漂移（confirmed 2↔8）。修复: `verify_prompt.md` + `{history_text}` 占位符，`verify_agent.py` + `_build_history_context()` + 透传（与 HypothesizeAgent 同源）。
- **P1**: 搜索文件名 `01_search_{date}.yaml` → `01_search_{date}_s{session_id}.yaml`，同日内两次运行不再互相覆盖。
- **测试**: 179/179 ✅ 零回归 | 版本: v0.19.0→v0.19.1 | pyproject: v0.11.0→v0.11.1
- **改动文件**: verify_prompt.md, verify_agent.py, search_agent.py, CHANGELOG.md, pyproject.toml

## v0.19.0 LLM 确定性验证 + 纯度分去 LLM 化 (2026-07-04)
- **动机**: Brainstorming 诊断 — 验证 confirmed↔partial 随机跳动 + 寒武纪纯度分 1%↔25% 剧烈跳动
- **根因**: LLM 一次调用输出 status（全局判断黑箱），temperature=0 仍非完全确定
- **方案 C**: 压缩 LLM 自由度 — 从「裁判」降级为「记分员」
- **Layer 1 — VerifyAgent 原子化**:
  - `verify_prompt.md`: 输出格式删 status/confidence，新增 Q1 source_count（计数）/ Q2 data_alignment（方向）/ Q3 counter_conflict（是否推翻）
  - `verify_agent.py`: 新增 `_synthesize_status()`（16 组合） + `_synthesize_confidence()` — LLM 不再输出 status，由代码确定
- **Layer 2 — 纯度分去 LLM**:
  - `purity_scorer.py`: `match_business_to_l3()` 改为动态关键词匹配为主（`_extract_l3_keywords` 从 L3 自动提词）
  - LLM 匹配降级为回退（仅关键词语法零匹配时触发）
- **测试**: 179/179 (152→179, +27 新测试) ✅ | 版本: v0.18.6→v0.19.0 | pyproject: v0.10.0→v0.11.0
- **设计 Spec**: `docs/specs/2026-07-04-llm-deterministic-verification.md`
- **⚠️ 稳定性实测 (2026-07-04)**: 对「人工智能」板块跑两遍→**20/100 分（差）**：
  - confirmed: 2→8（差 4 倍），partial: 6→4，unverified: 4→0
  - 股池: 23→27（4 只差异），纯度分 16/23 只不一致，排名 20/23 只变化
  - 评级: 景气→高景气
  - **根因**: `_synthesize_status()` 是确定性的，但它的 3 个输入 (source_count/data_alignment/counter_conflict) 仍是 LLM 输出，在两次运行间剧烈漂移。关键词纯度分也依赖 L3 假设文本（LLM 生成），假设变化→关键词不同→纯度分漂移
  - **结论**: 确定性改造只解决了「合成」环节，未解决「输入」环节。需要 Search 冻结 + 假设固定化才能根治

## v0.18.6 高景气策略推理链路 3 层 Bug 修复 (2026-07-03)
- **P0 — CounterAgent 语义级联 (Plan B)**: `_cascade_safety_net` polarity-blind → 新增 `counter_agent.py`（LLM cascade + hardcoded polarity fallback + safety_net 三级降级）。disputed+negative→keep alive。sentiment 直接覆盖（Plan B）。
- **P1 — 链条结构完整性**: Hypothesize prompt Rule 8 + `_validate_chain_completeness()` 软约束
- **P2 — SIGNAL_MAP 全覆盖**: 5→12 条目，去双重惩罚 ×0.5
- **Pipeline**: 6→7 步，CounterAgent 作为 Phase 3.5 在 verify 和 screening 之间
- **改动文件**: counter_agent.py(新), coordinator.py, verify_agent.py, hypothesize_prompt.md, hypothesize_agent.py, report_agent.py, config.py, pyproject.toml, CHANGELOG.md, docs/plans/2026-07-03-prosperity-cascade-fix.md(新)
- **版本**: v0.18.5 → v0.18.6 | pyproject: v0.9.9 → v0.10.0

## v0.18.5 Learning Agent 产业学习层实现 (2026-07-02)
- **实现**: `learning_agent.py` + prompt 模板 `rules/prosperity/prompts/learning_prompt.md`
- **位置**: Phase 1.5（Search → Learn → Hypothesize），首次构建、后续跳过
- **输出**: 产业图谱 7 节写入 `wiki/industries/{name}.md`，下游 Agent 零改动（`_load_history()` 自动消费）
- **测试**: 152/152 ✅ | 版本: v0.18.4 → v0.18.5 | pyproject: v0.9.8 → v0.9.9
- **后续**: 多源验证矩阵 + 全链路缓存（脑暴完成，待实现）

## 产业学习层（Learning Agent）设计 (2026-07-02)
- **动机**: LLM 在 Pipeline 中三处波动（HypothesizeAgent/VerifyAgent/ScreeningAgent），级联放大导致结果不稳定
- **根因**: 当前 Pipeline 缺少结构化知识背景 —— Search → Hypothesize 跳过了"学习"这一步
- **方案**: 新增 Learning Agent 作为 Phase 1.5（Search → Learn → Hypothesize）
  - 输出: 产业图谱 7 节写入 `wiki/industries/{name}.md`（价值链/供需/技术路径/政策/瓶颈/跟踪指标/不确定区域）
  - 一次 LLM 调用，下游零改动
  - 信源必引用 `[信源N]`（反幻觉），无信源不写
- **后续两块**: 多源验证矩阵 + 全链路缓存（脑暴完成，待 Spec）
- **文件**:
  - Spec: `docs/specs/2026-07-02-industry-learning-agent.md`
  - Prompt 模板: `backend/rules/prosperity/prompts/learning_prompt.md`
- **状态**: 设计完成，待实现

## v0.18.4 方向分作为股池第二参考指标展示 (2026-07-02)

## v0.18.4 方向分作为股池第二参考指标展示 (2026-07-02)
- **问题**: 方向分算出来后只参与内部 tuple sort，未在最终报告表格和 `score_detail` 中展示，用户无法解释 purity=0 股票的排序差异
- **修复**:
  - `screening_agent.py`: `score_detail` 新增 `direction_score` 字段（保留 3 位小数）
  - `report_agent.py`: 股池表格新增「方向分」列，格式 0.00~1.00
- **原则**: 方向分**不混入** `final_score`，排名核心仍是物理纯度分；方向分仅作为独立参考列，解释 tuple sort 的平局打破逻辑
- **改动文件**: `backend/app/core/config.py`, `screening_agent.py`, `report_agent.py`, `test_prosperity_coordinator.py`
- **测试**: 145/145 ✅ | 版本: v0.18.3 → v0.18.4 | pyproject: v0.9.7 → v0.9.8 | APP_VERSION: 0.18.0 → 0.18.4

## v0.18.3 选股信号质量感知融合 (2026-07-02)
- **问题**: Stage 1 方向匹配有搜索上下文，Stage 2 纯度打分无搜索上下文 → 信息割裂；概念入口过松；H3-3 规避方向无负向信号；purity=0 股票随机排列
- **修复**:
  - `concept_builder.py`: LLM 提取加 `relevant` 字段，过滤行情/指数成分股等无关股票
  - `screening_agent.py`: `_detect_polarity()` + L3 极性 tag；tuple sort `(purity_score, direction_score)`；硬过滤 `matched_l3=null + purity=0`
  - `purity_scorer.py` + `screening_agent.py`: `_build_search_context_for_purity()` 提取搜索素材中公司上下文注入 purity prompt；`screen()` 将 `search_result` 透传至 `_compute_purity()`
- **效果**: 纯度 > 0 股票不受影响；purity=0 但 direction > 0 按方向分有序；完全无关股票被移除
- **测试**: 144/144 ✅ | 版本: v0.18.2 → v0.18.3 | pyproject: v0.9.6 → v0.9.7

## v0.18.2 方向匹配允许 null (2026-07-02)
- **Bug**: LLM 方向匹配提示词强制"覆盖所有成分股" → 每只股票都被分配了一个 L3 方向（中钨高新→H3-2、王子新材→H3-3 等明显不相关也被归类）
- **修复**: `_llm_direction_match()` 提示词新增不匹配规则 + null 示例，Stage 4 `direction_annotation` 从 "-" 改为 "不匹配"
- **注意**: purity_scorer 已有 null 语义（`related_items: []` 即不匹配），仅同步了输出示例
- **改动文件**: `screening_agent.py`, `purity_scorer.py`, `CHANGELOG.md`, `pyproject.toml` (v0.9.6)
- **测试**: 144/144 ✅

## v0.18.1 Bugfix: fina_indicator 字段名纠正 (2026-07-02)
- **Bug**: `tushare_client.get_fina_indicator()` 请求字段名 `revenue_yoy` / `net_profit_yoy` → Tushare 正确字段是 `or_yoy` / `netprofit_yoy`
- **影响**: 免费层不识别错误字段名 → 静默忽略 → YAML 中 34 只股票增速全 null → finance_score 70% 权重用假值 0 计算百分位
- **修复**: `tushare_client.py` 字段名改正 + rename 映射 (`or_yoy→revenue_yoy`, `netprofit_yoy→net_profit_yoy`)，下游零改动
- **验证**: 4 只测试股票全部返回真实数据（中核科技 -49%/+693%, 永鼎 +42%/-45%）
- **注意**: stock_pool.yaml 需重新生成才生效

## v0.18.0 股池筛选：业务纯度排名 (2026-07-02)
- **问题**: 方向+财务分都看公司整体，不区分子业务。永鼎超导仅占16%却因光纤增速+卖房收益排第一
- **方案**: 筛选阶段回答"跟投资方向多大关系"，不是"公司好不好"
  - 排名: 纯度分 = 相关业务收入/总收入（fina_mainbz + LLM匹配）
  - 方向: 仅标注 matched_l3，不参与排名
  - 财务: 4因子百分位（去动量），仅参考列
  - 报告表格: 排名|股票|纯度分|ROE|毛利率|营收增速|匹配方向
- **新增**: `purity_scorer.py`（批量拉取+LLM匹配+纯度计算）, `tushare_client.py.get_fina_mainbz()`
- **修改**: stock_screener（去动量）, screening_agent（4阶段：标注→纯度→财务→排名）, report_agent（表格列更新）, config（删旧权重）
- **测试**: 41/41 ✅ | 版本: v0.17.4 → v0.18.0

## v0.17.4 regenerate_screening.py 报告数据源修复 (2026-07-01)
- 修复独立刷新脚本报告污染：陈述/推理链为空 + Mermaid 节点 ID 不匹配
- `load_verified_hypotheses()` 改为三步合并：DB(验证状态) + wiki .md(陈述/推理链/ID/上游) → 按标题匹配
- 可控核聚变验证: 12/12 条完整

## v0.17.3 高景气策略 Agent max_tokens 全局统一 (2026-07-01)
- 6 个 Agent 全部改为 `settings.LLM_MAX_TOKENS`（当前 32768），不再各自写死
- 新增 `scripts/regenerate_screening.py`：独立重跑 Screening + Report，验证可控核聚变 34 只全部方向匹配成功
- report_agent 股池从 Top 10 → 全量展示

## v0.17.0 Watchlist 巡检系统 — 全自动研究触发器 (2026-07-01)
- **动机**: watchlist 是"备忘录"而非"巡检系统"——`check_watchlist()` 只判断日期到期，`last_value` 永远为 `None`
- **目标**: 全自动研究触发器（路径 C）——指标变化超过阈值 → 自动触发新一轮研究
- **设计方案（Brainstorming 逐项确认）**:
  1. **HypothesizeAgent: key_indicators string[] → object[]** — 新增 name/frequency/search_query/expected_direction
  2. **TrackAgent.check_industry()** — 行业级巡检入口：Tavily 搜索 → LLM 提取值 → 触发判定
  3. **触发判定**: 数值超 20% 阈值 OR 方向反转 → triggered
  4. **跟踪范围**: confirmed/partial/unverified/disputed（排除 unreachable/overturned）
  5. **YAML 权威源 + SQLite 查询缓存** — 单向同步，消除双写不一致
  6. **coordinator.py pre_check**: pipeline 开头（search 前）自动调用巡检
- **数据获取**: 路径 2（LLM + WebSearch 动态获取），因 indicator 是 LLM 生成的非结构化文本
- **触发方式**: 路径 B（按需触发，研究前预检）— 零空跑
- **数据库**: tracking_items +7 列 + migrate_v4()
- **改动文件**: hypothesize_agent.py, track_agent.py(重写), coordinator.py, models.py, report_agent.py
- **新增文件**: docs/specs/2026-07-01-watchlist-inspection-system.md
- **测试**: 138/138 ✅ | 版本: v0.16.0 → v0.17.0 | pyproject: v0.9.1 → v0.9.2

## v0.16.0 高景气策略核心增强 Spec (2026-07-01) — 设计阶段
- **动机**: Brainstorming 缺陷分析发现两个致命缺陷——①VerifyAgent 纯代码 3 条 if-else 是伪验证（LLM 从未参与）②股池评分与推理链完全脱节（L3 选股方向未用到评分中）
- **根源**: 整条 6 Agent 管道只有 HypothesizeAgent 用到 LLM，其余全是确定性代码
- **设计方案（逐项讨论后确定）**:
  1. **VerifyAgent 完全重构**（P0）：LLM 串行验证推理链 + 反例搜索 + corrected_statement/causality_strength 输出。CounterAgent 合并进 VerifyAgent
  2. **新增 ScreeningAgent**（P0）：LLM 方向匹配（基于 L3 investment_implication + 搜索素材判断每只成分股契合度 0~1）+ 代码财务打分（含真实动量）→ 50/50 融合
  3. **HypothesizeAgent +sentiment**（P1）：positive/negative/neutral，方向是假设固有属性
  4. **ReportAgent 评级重构**（P1）：从计数 → 加权信号聚合（sentiment × 层级权重 × causality 折扣）
  5. **VerifyAgent 反例搜索**（P1）：LLM 自动生成 → Tavily 执行 → 喂入验证
  6. **动量真实数据**（P2）：Tushare daily 实时拉取，替代 stub 占位符
  7. **causality_strength**（P2）：strong/moderate/weak/broken
- **管道变更**: Search→Hypothesize→Verify→Screening→Report→Track（6→5 Agent）
- **LLM 调用**: 1 次 → (推理链条数 + 2) 次
- **Spec 文档**: `docs/specs/2026-07-01-prosperity-strategy-v16-enhancement.md`
- **版本**: v0.15.0 → v0.16.0 | pyproject: v0.9.0 → v0.9.1

## v0.15.0 代理下线 + 搜索引擎自建概念板块 (2026-07-01)
- **代理下线**: tushare_client.py 删除全部代理逻辑（~100行），简化为纯直连 + 重试。config.py 删除 TUSHARE_PROXY_URL
- **AKShare 替换**: 信源5 搜索引擎自建方案（Tavily 搜索 → LLM 提取 → stock_basic 交叉验证 → YAML 缓存）
- **新增 concept_builder.py**: 支持任意自定义概念（可控核聚变/固态电池/低空经济），首次 ~5s 后续缓存秒出
- **配置清理**: .env 删代理段 7 行；pyproject.toml 删 akshare 依赖
- **清理**: 删除 8 个过时代理测试脚本 (test_ths_*.py)
- **测试**: 133/133 ✅ | 版本: v0.14.7 → v0.15.0 | pyproject: v0.8.11 → v0.9.0
- **重要**: 2000 积分 token 直连完全满足需求，未来不再需要代理

## v0.14.5 景气管道性能优化 (2026-06-30)
- **问题**: 景气管道跑 30 分钟无输出，卡在 verify 阶段逐只调 fina_indicator（200 只串行 ~5min）
- **优化1**: TushareClient 类级别共享 proxy 状态 (`_class_using_proxy`)，后续实例跳过 ~8s 直连重试
- **优化2**: `_fetch_batch_financials` 批量 API（逗号分隔 100 只/次，200 只 2 次调用 ~3s vs 200 次）
- **优化3**: `_compute_acceleration` 复用 `_cached_fina_full` 不再二次拉取（又省 200 次调用）
- **优化4**: `run_full_pipeline` + verify_agent 每阶段 print 时间戳 + 统计（用户不用干等）
- **改动文件**: tushare_client.py, industry_metrics.py, coordinator.py, verify_agent.py, run_prosperity_ne.py
- **测试**: 133/133 ✅ | 版本: v0.14.4 → v0.14.5 | pyproject: v0.8.8 → v0.8.9

## v0.14.3 概念股池多信源兜底 (2026-06-30)
- **问题**: "新能源"不在标准行业分类中，`get_industry_ts_codes` 返回 0 只 → 全链条崩塌
- **方案**: stock_basic + 申万之后，追加 concept_detail（免费）+ ths_index→ths_member（代理）两层概念兜底
- **tushare_client.py**: 新增 get_concept_detail() / get_ths_index() / get_ths_member()
- **industry_metrics.py**: get_industry_ts_codes() 新增信源3+4 概念兜底
- **测试**: 132/132 ✅ | 版本: v0.14.2→v0.14.3 | pyproject: v0.8.6→v0.8.7
- **关键坑**: ths_member 股票代码字段是 `ts_code` 不是 `con_code`

## v0.14.2 watchlist 拆分为每行业独立文件 (2026-06-29)
- **动机**: watchlist.yaml 随行业增多越来越长，当研究 ≥5 行业时单文件难以维护
- **方案**: `tracking/watchlist.yaml` → `tracking/watchlist/{行业名}.yaml`，每行业一个文件
- **代码**: `_load_watchlist()` 遍历目录 glob(`*.yaml`)，新增 `_load_watchlist_legacy()` 后向兼容
- **内存表示不变**: 仍返回 `{行业名: [指标列表]}`，调用方零改动
- **改动文件**: track_agent.py, test_prosperity_coordinator.py, watchlist.yaml→watchlist/电气设备.yaml
- **测试**: 129/129 ✅ | 版本: v0.14.1 → v0.14.2 | pyproject.toml: v0.8.5 → v0.8.6

## v0.14.1 watchlist.yaml 按行业分组重构 (2026-06-29)
- **问题**: watchlist 扁平 items 列表 + `_merge_indicators` 仅用指标名做 key → 跨行业同名指标被错误合并
- **修复**: 复合 key `(indicator, industry)` + 写入格式改为 `{行业名: [指标列表]}` + `_load_watchlist` 兼容旧格式自动迁移
- **改动文件**: track_agent.py, watchlist.yaml, test_prosperity_coordinator.py (+3)
- **测试**: 129/129 ✅ | 版本: v0.14.0 → v0.14.1 | pyproject.toml: v0.8.4 → v0.8.5

## v0.14.0 Wiki 智能增强 — 重复行业研究优化 (2026-06-29)
- **问题**: v0.13.2 修复 5 Bug 后暴露 wiki 系统架构问题——重复行业缺乏冷却判断、Search 全量搜新旧混杂、只有 Hypothesize 读 wiki、评级行无限追加
- **方案**: 5 天冷却硬门控 + 全链历史锚定 + 增量搜索 URL 去重 + 评级行去重 + key_indicators 全量入 watchlist (Brainstorming → Spec → Plan 完成)
- **关键决策**:
  - 混合模式：5 天冷却硬门控 (`start_session(force=True)` 跳过)，确认后走软增强
  - IndustryHistory 数据类：Coordinator 预加载后逐级传入 6 Agent
  - Search: URL 去重 → 新结果 300字/旧结果 100字摘要
  - Synthesis 截取: ~3000字结构化（L0-L3+股池，不含验证/反推），非原 500 字
  - Verify/Counter 也注入历史上下文
  - Track: 所有假设（非仅 UNVERIFIED/OVERTURNED）的 key_indicators 提取，按指标名合并去重
  - 只取最近一次 session 历史假设
  - 指标自动巡检触发逻辑本次不做（只铺管道）
- **改动文件 (8个)**: industry_history.py(新), coordinator.py, search_agent.py, hypothesize_agent.py, verify_agent.py, counter_agent.py, report_agent.py, track_agent.py
- **测试**: 10 条测试要点覆盖全部场景
- **状态**: Spec + Plan 完成，待实现

## v0.13.2 景气打分系统五大 Bug 修复 (2026-06-29)
- **Bug 1 — 5/6 打分维度失效**: `get_fina_indicator` 缺 `revenue_yoy/net_profit_yoy/debt_to_assets` 字段 → 全量打分只剩 ROE 有数据
- **Bug 2 — quality_score 恒为 0**: 字段跨表（ocf/capex 在 cashflow 表）+ 名称错误（`gross_margin` 应为 `grossprofit_margin`）+ 名称错误（`debt_ratio` 应为 `debt_to_assets`）
- **Bug 1b — 百分位 4 档离散**: `_percentile_score` P25/P50/P75 分桶 → `bisect` 连续百分位排名
- **Bug 3 — 股池无中文名**: `_get_stock_data` 不查 `stock_basic` 表 → `get_stock_name_map()` 复用缓存
- **Bug 4 — LLM 不可复现**: `temperature: 0.3` → `0.0`
- **Bug 5 — 不读 wiki 历史**: `_build_prompt` 注入 `_load_wiki_history()` 锚定（最近 3 条评级 + 上次报告摘要）
- **改动文件**: tushare_client.py, stock_screener.py, industry_metrics.py, hypothesize_agent.py, report_agent.py
- **测试**: 118/118 ✅
- **版本**: v0.13.1 → v0.13.2

## v0.13.1 B1+D+A+C 四件套完成 (2026-06-29)
- **B1**: `industry_metrics.py` 新增 `get_industry_ts_codes()` — stock_basic + 申万分类双信源取并集 + 缓存，替换 verify_agent/report_agent 的 `str.contains()` 模糊匹配
- **D**: `_compute_acceleration` stub→真实化，拉取最近2期 fina_indicator 比较 revenue_yoy 加速/减速/持平
- **A**: API 4 分步端点 (`/hypothesize`/`/verify`/`/counter`/`/report`) 从 400 stub→真实实现，Coordinator 新增 `pipeline_cache` 暂存中间结果
- **C**: 前端集成测试 26 用例（IndustrySelector 8 + HypothesisBoard 10 + ReportViewer 8），vitest 全通过
- **测试**: 后端 118/118 ✅ + 前端 26/26 ✅
- **版本**: v0.13.0 → v0.13.1
- **下一步**: B2 第二个行业验证（需运行 pipeline）

## v0.13.0 高景气策略 SPEC 同步 + 剩余实现 (2026-06-29)
- **Phase A (SPEC sync)**: SPEC v0.1.0→v0.12.2，7 项更新：§2.2 因果推理链 / §2.3 级联+UNREACHABLE / §2.4 三遍扫描 / §2.5 叙事报告+Mermaid / §4 DB+状态流 / §10 v2设计决策 / CONTEXT.md同步
- **Phase B (实现)**:
  - `source_crawler.py`: stub→SIA 真实爬取 (httpx+BeautifulSoup)，SOURCE_HANDLERS 路由分发，WSTS+SEMI 保留 stub
  - `stock_screener.py`: _momentum_stub→_momentum_score，Tushare daily 真实计算 3/6月动量，in-memory 缓存
  - 前端 prosperity 3 组件: IndustrySelector + HypothesisBoard (L0-L3分栏) + ReportViewer (react-markdown)
  - Layout.tsx 注册 prosperity 组件映射
- **测试**: 15/15 通过 (新增 8 个: source_crawler 5 + stock_screener 3)
- **版本**: v0.12.2 → v0.13.0
- **下一步**: 前端集成测试 / 第二个行业验证 / industry_metrics Tushare 行业分类匹配

## v0.9.6 Tushare 代理服务器壳层注入 (2026-06-25)
- TushareClient.pro 属性注入 `_DataApi__http_url`，所有调用方 0 改动
- config.py: +`TUSHARE_PROXY_URL` (空=官方, 有值=代理)
- 代理: `https://ts.gyzcloud.top/api` | 周卡 2026-07-02到期 | 150次/min
- 所有代理代码标 `🧪 TEST-ONLY`，上线前 grep 定位

## v0.8.0 双策略平台重构 (2026-06-22)
- **架构**: 单策略 → 多策略平台。龟龟功能零退化。
- **策略注册表**: `app/core/registry.py` — StrategyMeta 数据类 + STRATEGIES 字典，策略元信息唯一真相来源
- **后端隔离**: `strategies/turtle/` 自包含（api.py + coordinator + screener + gate + qrv_agent + summarizer + extractor）
- **数据隔离**: `data/stock_cache/turtle/` 独立
- **前端隔离**: `components/turtle/` 独立，Layout 组件映射表分发
- **API**: `/api/turtle/*`，main.py 遍历 registry 自动挂载
- **共用**: `services/tushare_client.py` + `services/data_fetcher.py` + `core/config.py` + `core/logging.py`
- **加新策略**: registry 注册 1 行 + 新建 3 目录 + Layout 映射 1 行 = 5 分钟
- **测试**: 98/98 pytest + 37/37 vitest 全部通过

## 项目位置
- 所有项目文件夹创建在 D:\project\ 下
- **禁止在项目文件夹外创建文件**：所有产出文件（脚本、日志、输出等）必须放在对应项目文件夹内，不得散落在 D:\project\ 根目录
- 数据源 Tushare 为主，搜索引擎自建概念板块为兜底
- LLM API 用 OpenAI 兼容接口
- 前端虚拟滚动 + 异步加载

## 已知技术坑
- **Tushare `fina_indicator` 批次限制**: 单次调用最多处理约 100 只股票，超出静默截断。`_fetch_all_fina_indicator` 的 batch_size 不能超过 100，当前设为 60（覆盖率 99.9%+）
- **fillna(0) 副作用**: 数据缺失的股票会被 fillna(0) 填充，导致 ROE<=0/毛利率<=0 等条件误淘汰。必须先确保数据覆盖率足够高
- **`ocf_to_or` 字段含义**: Tushare `ocf_to_or` = OCF/Revenue(营业收入)，不是 OCF/NetProfit(净利润)。该字段已从选股器移除（v2026-06-15），CQ维度1直接计算替换
- **PowerShell 环境**: stdout 重定向会产生 CLIXML 乱码，测试结果需写入文件后读取
- **react-markdown v9 GFM 表格**: v9 不再内置 GFM 表格解析，必须显式安装 `remark-gfm` 并传入 `remarkPlugins={[remarkGfm]}`，否则 Markdown 表格以纯文本原样输出（2026-06-18 已修复）
- **ResizablePanel**: 通用可拖拽分隔组件，用于 sidebar↔主内容、TOC↔报告正文。宽度持久化到 localStorage，min/max 夹持，4px 分隔线 hover 显示 2px accent（2026-06-18 新增）

## 测试策略
- `backend/tests/test_spec_compliance.py` — SPEC 合规测试，验证代码实现是否符合 turtle-coordinator.md/ADR 规范（非逻辑测试，是 checklist 自动化）
- `frontend/tests/e2e/` — Playwright E2E 13 用例，`page.route()` 浏览器内拦截零后端依赖
- 每次改完代码后跑 `pytest tests\ -v` + `cd frontend && npm test` 确认无回归
- 现有后端 76 测试 + 前端 13 测试 全部通过 (v2026-06-19)

---

## v0.7.12 前端全面 UI 优化 (2026-06-22)
- **动机**: 散户/个人投资者反馈界面偏冷硬、信息层次不够清晰。设计方向：清晰·现代·友好 (Notion/Linear 风格)。
- **Phase 1 设计基础层**: 暖底微米色 (`#faf9f7`), 主色 oklch 更通透；新增 3 个语义化表面 + 3 个软状态色；排版层级加大 (H1 24→28px, Body 13→14px)；Inter cv01/cv04 启用；流体间距 clamp()
- **Phase 2 组件层级 (6 组件)**:
  - **Sidebar**: Logo SVG Argus之眼 (靶心+准星) 替换蓝色方块"A"
  - **StockPool**: 行高 36→44px, 评分条 8px, hover 左侧蓝线 (2px动画), "未分析"→"点击分析→"
  - **ScoreCard**: 综合总分 22→28px + letter-spacing:-1px, 分组间竖线分隔, 进度条 4→5px
  - **ReportViewer**: 卡片解构 (去 box-shadow/border-radius), 空状态 emoji→SVG (72×72), 悬浮回顶胶囊 (scroll>400px渐入), H2 2px→1px 软边框
  - **ResizablePanel**: 手柄 4→6px + 点击热区扩大, 拖拽时全局 cursor 锁定
- **Phase 3 交互**: 错误/警告框左侧 3px 竖线指示；所有动效 ease→cubic-bezier(0.16,1,0.3,1)；UX 文案 6 处优化
- **涉及文件 (13个)**: index.css, Sidebar/StockPool/ScoreCard/ReportViewer/ResizablePanel TSX+CSS, Layout.module.css, package.json, CONTEXT.md, CHANGELOG.md
- **测试**: 37/37 vitest ✅ | tsc --noEmit 零错误 ✅ | 零业务逻辑变更

## v0.7.11 股池 QRV 评分栏不显示分数 (2026-06-22)
- **根因**: `qrv_agent.py` 写的 `qrv_analysis.json` 从来不包含 `scores` 字段。LLM 确实输出了综合打分卡表格（如 Q1=8, V3=9, 综合=7.7），但数字嵌在 markdown 文本中从未被解析。
- **修复**: 新增 `QRVAgent._parse_scores()` 静态方法，用正则从 LLM markdown 的「综合打分卡」表格自动提取 Q1-Q3/R1-R4/V1-V3 10 维度分数 + 综合总分 + Q/R/V 加权均分
- **涉及文件**: qrv_agent.py (+~60行), CONTEXT.md, coordinator.md, config.py, pyproject.toml, CHANGELOG.md, memory
- **测试**: 98/98 pytest 通过 ✅, 冒烟测试: 全表/小数/N(A跳过/无表格 全部正确 ✅
- **后向兼容**: 已分析个股需重新分析才有 scores（不重新分析 → scores=None → `"—"`，无破坏）

## v0.7.7 三项前端修复 + 股池分数实时更新 (2026-06-22)
- **问题1 引用跳转失效**: a组件丢弃id属性 → `mdComponents.a` 转发 `{...rest}`；参考来源默认折叠无锚点 → `isDefaultExpanded` 加正则；cite无点击暗示 → CSS全局 `cursor:pointer`
- **问题2 盈利质量趋势无色**: TdRenderer 新增 `TREND_MAP` 识别 up/down/stable/吃老本/收缩 → up绿▲/down红▼/stable灰─
- **问题3 股池QRV分数不更新**: `_run_analysis_background` done时读取 `qrv_analysis.json` → 回填 `scores` 到 `_pool_cache`
- **涉及文件**: ReportViewer.tsx, ReportViewer.module.css, stocks.py, CHANGELOG.md, CONTEXT.md, pyproject.toml
- **测试**: Lint零错误 ✅

## v0.7.6 WebSearch 置信度质量加权 + 前端锚点/TOC 修复 (2026-06-22)
- **问题**: 置信度全是 HIGH（≥6条即HIGH,每模块12+条）；引用 `[W-q-1](#w-q-1)` 裸文本不跳转；TOC子标题跳错；锚点id被sanitize剥离
- **质量加权**: coordinator.py 新增 3 个确定性打分函数 (来源可信度/信息密度/时效性, 0-3分/条)，模块置信度按质量总分判定 (≥12→HIGH, ≥6→MEDIUM, ≥2→LOW)
- **前端修复**: 正则加 `(?!\()` 负向前瞻；`rehype-sanitize` schema 允许 `a[id]`/`a[name]`；TOC子项 `item.id`→`sub.id`；`scrollToSection` 支持 h3 查找
- **测试**: 98/98 全绿 ✅ | tsc零错误 ✅ | Linter零错误 ✅

## v0.7.5 锚点跳转 + 置信度使用规则 (2026-06-21)
- **问题**: 报告引用标记 `[W-q-3]` 是纯文本无法点击跳转；websearch 有置信度数据但 Prompt 未要求使用
- **锚点跳转**: 正文引用格式从 `[W-q-3]` → `[W-q-3](#w-q-3)` + 参考来源行前放 `<a id="w-q-3"></a>`，A系列同理
- **置信度规则**: turtle_qrv.yaml 新增全节，定义 HIGH/MEDIUM/LOW/NONE 四级 + 对应引用规则 + 降权要求
- **数据层**: data_summarizer.py v2.1→v2.2: W条目新增 module_confidence/snippet_confidence + confidence_summary 汇总
- **涉及文件**: turtle_qrv.yaml, data_summarizer.py, turtle-coordinator.md, CONTEXT.md, config.py, pyproject.toml, package.json, CHANGELOG.md
- **测试**: 98/98 全部通过，零计算逻辑变更

## v0.7.4 报告输出质量四件套 (2026-06-21)
- **问题**: 报告段落不稳定/超链接无URL/趋势英文词/估值区间LLM凭感觉估
- **结构强制**: Prompt 新增强制输出结构声明，7个顶级 ## 标题固定顺序和名称
- **参考来源**: data_summarizer reference_index +A1-A8 数据锚点，LLM可提取原始数值填入 A-引用表
- **趋势箭头**: up/down/stable → ↑/↓/→
- **估值公式约束**: 低估PE=min(当前PE×0.7, A8.p25)，合理PE=A8.median，高估PE=max(当前PE×1.3, A8.p75)
- **测试**: 98/98 全部通过

## v0.7.3 R4 重大事件与资本运作 (2026-06-21)
- **问题**: 分众传媒3月定增收购新潮传媒(83.5亿)这样的大事三层全漏
- **搜索层**: q_websearch +1 keyword "定增 并购 收购 资产重组 资本运作 重大合同 重大事项"
- **提取层**: WebSearchExtractor +`_extract_corporate_events()` (定增/并购/重组/重大合同/诉讼 5类正则)
- **分析层**: QRV v3→v4, 10模块→11模块, +R4事件清单表+影响分析+跨维度联动
- **涉及文件**: turtle_qrv.yaml, websearch_extractor.py, data_summarizer.py, turtle-coordinator.md, CONTEXT.md, config.py, pyproject.toml, package.json, test_websearch_extractor.py(新), test_spec_compliance.py, CHANGELOG.md
- **测试**: 98/98 全部通过 (原86 + 新增12)

## v0.7.2 dim7 reason 透传修复 (2026-06-21)
- **问题**: 分众传媒 dim7 供应商挤压显示 N/A，reason 字段未透传到 data_summarizer
- **`cash_quality.py`**: `no_supplier_squeeze_or_insufficient_data` 拆为 `not_applicable_no_supplier_credit`(无实物供应商) + `insufficient_data_for_cagr`(数据不足)
- **`data_summarizer.py`**: dim7 新增 `reason` 字段，QRV Agent 可区分「不适用」vs「数据缺失」
- **`turtle-coordinator.md`**: 新增 dim7 reason 码说明
- **测试**: 86/86 全部通过

## v0.7.0 分红资金来源质量检测 (2026-06-21)
- **动机**: CQ 5维度检测现金质量但不检测分红现金来源。低负债率公司可借钱发债或压上游货款维持高分红
- **新增 CQ dim6/7/8**: FCF分红覆盖率(dim6)、供应商挤压(dim7)、有息负债趋势(dim8) — 全部软门
- **数据层**: tushare_client.py 新增 8 个资产负债表字段 (accounts_payable/notes_payable/contract_liab/advance_receipts/st_borrow/lt_borrow/bonds_payable/noncurrent_liab_due_in_1y)
- **效果**: 42候选池 CQ通过12/未通过30，dim6(FCF分红覆盖)=25失败(最强信号)
- **改动的文件(11个)**: tushare_client.py, data_fetcher.py, cash_quality.py, coordinator.py, data_summarizer.py, turtle_cash_quality.yaml, turtle_coordinator.md, turtle_qrv.yaml, test_cash_quality.py, test_spec_compliance.py, CHANGELOG.md
- **测试**: 16/16 全部通过 (12 unit + 4 SPEC), pytest 全量绿 ✅
- **CAGR 方向 Bug 修复**: dim7 CAGR 计算方向反了 (ratios[-1]/ratios[0] → ratios[0]/ratios[-1]), 测试捕获并修复

## v0.6.22 分析中间状态跳过修复 (2026-06-21)
- **问题**: 分析时前端状态从 `fetching` 直接跳到 `analyzing`，中间 `computing`（计算CQ+PR）和 `websearch`（外部搜索）不可见
- **根因**: 轮询间隔 2s，computing（<0.5s）+ websearch缓存（<0.1s）合不到 1s，全部发生在两次轮询之间
- **修复**: 前端加最小显示时长门控 — `STAGE_ORDER` 定义阶段顺序，检测状态跨越 ≥2 级时注入中间阶段
- **机制**: `scheduleStageChain()` 按 MIN_STAGE_MS=1500ms 间隔逐个显示跳过阶段；终态立即显示；相邻推进直接显示
- **涉及文件**: ReportViewer.tsx (+70行), CHANGELOG.md, CONTEXT.md, pyproject.toml, config.py, package.json
- **测试**: 后端 78/78 全绿 ✅ | tsc --noEmit 零错误 ✅

## v0.6.19 分析按钮 6 态状态机 + 8 项防错机制 (2026-06-21)
- **动机**: 分析按钮只有 2 态 (idle/analyzing)，用户不知道在拉数据/跑AI/完成了/报错了
- **6 态**: idle → submitting(提交中...) → processing(阶段名+脉冲+进度条) → success(✅绿色+加载中) → error(⚠️红色+重试) → timeout(⚠️超时+重试)
- **按钮样式**: processing 蓝色脉冲动画、success 绿色缩放弹入、error 红色边框可点击重试、outline 蓝色边框(有报告时的重新分析)
- **① 本地锁**: `submittingRef` + 500ms 冷却防双击竞态
- **② 探活恢复**: mount 时 GET `/analyze/status` 恢复 F5 刷新后状态
- **③ 断连警告**: 连续 5 次轮询失败 → 黄色警告框
- **④ 超时检测**: 15s 定时器 + `startedAtMap` ref 检测 10min 僵尸任务
- **⑤ 重试清错误**: retry 前 `delete analysisMap[code]` 清旧错误
- **⑥ 成功等报告**: done entry 仅在 reportData 到位时清理（不按时消失）
- **⑦ 区分错误**: `_errType: 'mutation'|'task'` 区分 POST 失败 vs 后台任务失败
- **⑧ 切后台恢复**: `visibilitychange` 监听 + 主动 GET status
- **新增 CSS 类**: `.analyzeBtnProcessing`/`.analyzeBtnSuccess`/`.analyzeBtnError`/`.analyzeBtnOutline`/`.buttonSpinner`/`.errorBox`/`.successBox`/`.warningBox`/`.phaseLabel`
- **动画**: `@keyframes btnPulse`(蓝脉冲)、`@keyframes successFlash`(绿弹入)、`@keyframes spin`(旋转)
- **涉及文件**: ReportViewer.tsx(+120行), ReportViewer.module.css(+130行), CHANGELOG.md, CONTEXT.md, MEMORY.md, pyproject.toml
- **测试**: 后端 76/76 全绿 ✅ | tsc --noEmit 零错误 ✅ | vite build 通过 ✅

## v0.6.16 个人使用整体调优 (2026-06-21)
- **动机**: 审视个人使用阶段问题，做 8 项不影响未来平台架构的优化
- **P0-LLM开场白**: `stripPreamble()` 结构性切除（找第一个 `## ` 标题，之前全部丢弃），替代 `stripLlmRole` 的 7 条打地鼠正则
- **P0-日志可读**: `logging.py` ConsoleRenderer 始终使用（不再仅 DEBUG），个人使用不需 JSON
- **P0-版本号动态化**: Sidebar 从 `/api/health` 获取版本号 + `/api/stocks/status` 获取数据日期
- **P1-新鲜度端点**: `GET /api/status` 返回 turtle_pool.json mtime；缓存 TTL 5min→1h
- **P1-砍未用依赖**: 移除 react-router-dom/zustand/@tanstack/react-virtual (全项目零 import)
- **P1-一键启动**: `start.bat` 双击启动 frontend+backend
- **P2-键盘快捷键**: StockPool `↑↓` 浏览、`Enter` 选中、`Esc` 取消
- **P2-任务清理**: done 状态 5min 后自动从 `_analysis_tasks` 清除
- **测试**: 76/76 后端全绿 ✅ | tsc --noEmit 零错误 ✅ | vite build 通过 ✅
- **架构保留**: SQLAlchemy/alembic/structlog/apscheduler/akshare/Jinja2 全部未动

## v0.6.13 Playwright E2E 测试基础设施 (2026-06-19)
- **测试框架**: Playwright @playwright/test v1.61, Chromium headless
- **Mock 策略**: `page.route()` 浏览器内拦截所有 `/api/*` 请求，零后端依赖、零 DeepSeek token 消耗
- **多股并行模拟**: 阶段计数器 + `stages` 数组模拟 5 态 (fetching→computing→websearch→analyzing→done)，模拟 2s 轮询间隔
- **13 个测试用例**: smoke(5) + multi-stock(2) + interactions(6)，覆盖选股→Gate→报告→并行分析→cite跳转→API500→汉堡
- **运行**: `cd frontend && npm test` (headless), `npm run test:ui` (UI模式), `npm run test:headed` (有头浏览器)
- **关键坑**: `main.tsx init()` 预加载 `/data/turtle_pool.json` 会污染 API500 测试缓存，需额外 `page.route('**/data/turtle_pool.json', 404)`
- **全部通过**: 13/13 通过 (36.4s), DeepSeek token: 0
- **涉及文件**: `tests/playwright.config.ts`, `tests/e2e/mocks.ts`, `tests/e2e/{smoke,multi-stock,interactions}.spec.ts`, `package.json`

## v0.6.12 前端崩溃三连修复 (2026-06-19)
- **崩溃根因**: `injectCitationElements` 用 `replaceChild` 替换 React DOM → reconcile 失败 → NotFoundError 白屏
- **修复**: markdown 预处理 `preprocessCitations()` + `rehype-raw` 安全渲染 `<cite>`；ErrorBoundary 防全局白屏；`placeholderData` 防切换闪烁；`setAnalysisMap` 浅比较减少 80% 重渲染
- **涉及文件**: ReportViewer.tsx (~100行净删), main.tsx (+35行 ErrorBoundary), package.json (+rehype-raw), CHANGELOG.md
- **已知技术坑新增**: 原生 DOM 操作 (`replaceChild`/`appendChild`/`createElement`) 不得在 React 管理的 DOM 上执行；必须通过 `rehype-raw` + 字符串预处理在渲染前注入 HTML 标签

## v0.6.11 调试配置 + 诊断脚本 + asyncio GC 修复 (2026-06-19)
- **VS Code 调试**: 新建 `.vscode/launch.json` (FastAPI + Chrome 双配置) + `.vscode/settings.json`
- **诊断脚本**: `scripts/diagnose_analyze.py` — 4 步独立测试 (TushareClient → DataFetcher → CQ+PR → Coordinator)，支持 `python scripts/diagnose_analyze.py [ts_code]`
- **asyncio GC 预防**: `_bg_tasks: set` + `task.add_done_callback(_bg_tasks.discard)` 防止 create_task 被 GC
- **全链路验证**: POST analyze (200) + GET status (进度轮询) + GET analysis (完整报告) 全部通过前端代理
- **分析耗时**: 单股全流程约 7 分钟（WebSearch 5次 ~45s + LLM ~5min）
- **涉及文件**: launch.json, settings.json, diagnose_analyze.py, stocks.py

## v0.6.10 后台任务静默崩溃修复 (2026-06-19)
- **Bug**: 个股分析按钮卡 0% — `get_logger` 不存在导致 ImportError 吞掉异常，任务静默崩溃
- **修复**: `asyncio.create_task()` 替代 `BackgroundTasks`；`logging.getLogger(__name__)` 替代 `get_logger`；新增启动/状态日志
- **涉及文件**: stocks.py, CHANGELOG.md, MEMORY.md
- **测试**: 76/76 全绿

## v0.6.9 重新分析按钮对接个股分析 (2026-06-19)
- **问题**: 前端「🔍分析个股」/「🔄重新分析」只清缓存 → 空壳
- **后端**: `trigger_stock_analysis` + `BackgroundTasks` → `_run_analysis_background()` 异步跑 `coordinator.run_single_stock_full()`
- **状态追踪**: `_analysis_tasks` 字典 6 态 (fetching/computing/websearch/analyzing/done/error) + `GET /analyze/status` 轮询端点
- **Coordinator**: 新增 `run_single_stock_full()` 封装 Step 0-5 全流程，支持 `status_callback` 回调
- **前端**: `analysisStatus` + `useEffect` 2s 轮询 + 进度条 UI + 禁止重复提交
- **涉及文件**: stocks.py, coordinator.py, ReportViewer.tsx, ReportViewer.module.css, CHANGELOG.md
- **测试**: 76/76 全部通过

## v0.6.5 前端 7 项 UX 优化 (2026-06-19)
- **Sidebar**: 选股后自动收起，鼠标靠左边缘悬浮弹出
- **标题去重**: 移除硬编码 "QRV深度分析报告"，过滤 LLM header 中的 # 行
- **LLM角色过滤**: `stripLlmRole()` 正则去掉 "好的，收到您的指令。作为..." 等角色陈述段
- **表格优化**: collapse边框 + 2px表头底线 + 斑马纹 + 统一左对齐
- **跳转高亮**: 2秒 sectionFlash 动画
- **超链接**: external link→target=_blank, 引用跳转350ms延迟+兜底滚动
- **个股打分卡**: StockPool 选中行下方展开 compact ScoreCard
- **Pool API 读 turtle_pool.json**: 43 目录遍历 + 86 YAML 解析 → 单次 json.load，<10ms 返回
- **_read_yaml 顺序修复**: 移到 `_build_stock_index()` 之前，消除 NameError（被 try-except 吞掉导致索引中 name/industry 全是目录名）
- **gcTime: Infinity**: 缓存永不回收，切回任意股票秒出
- **placeholderData 已移除** (v0.6.5+): 不再保留上一只报告缓存，切换股票直接显示「加载中...」避免闪旧报告
- **测试**: 76/76 全部通过

## v0.6.7 Sidebar 图标栏 + 汉堡手动切换 (2026-06-19)
- **Sidebar 图标栏**: 缩进宽度 8px→56px，保留 Logo A + 策略图标居中；Sidebar 新增 `collapsed` prop 条件渲染
- **汉堡替代股池**: StockPool "股池" h2→三条杠 SVG 汉堡图标；`onToggleSidebar` 手动切换侧边栏
- **双控制并行**: 选股→自动缩进；汉堡→手动 toggle；悬停→临时展开
- **涉及文件**: Layout.tsx, Layout.module.css, Sidebar.tsx, Sidebar.module.css, StockPool.tsx, StockPool.module.css

## v0.6.6 三个 UI Bug 修复 (2026-06-19)
- **Bug 1 图标**: Sidebar 策略图标 emoji(🐢🚀)→SVG 线性图标（靶心十字准星 / 上升趋势箭头），CSS `.navIcon` 改为 flex 居中
- **Bug 2 重复点击**: 点击已选中个股→不再取消选中（return prev），避免 sidebar 意外弹开
- **Bug 3 闪旧报告**: ReportViewer 移除 `keepPreviousData`，切换股票时直接进入 loading 态，不闪现上一只报告
- **涉及文件**: `Sidebar.tsx`, `Sidebar.module.css`, `Layout.tsx`, `ReportViewer.tsx`

## v0.6.1 全量 Tushare 字段审计 + 归一化修复 (2026-06-18)
- **全量字段审计**: 逐一验证 6 个 API (income/balancesheet/cashflow/fina_indicator/dividend/daily_basic) 的字段名与 Tushare 官方文档一致性
- **B1: fields 参数**: 6 个 API 全部显式指定 fields，不再依赖 Tushare 默认返回子集 → 修复 financing_cf/acq_subsidiary/payout_ratio 100% 为 0
- **B2: 归一化 Bug**: `_normalize_to_yi()` 新增 NON_MONETARY 白名单 (gross_margin/roe/net_margin/eps/yoy/debt_ratio/current_ratio/quick_ratio)，百分比/比率/EPS 不再被误除 1e8 → 修复 QRV 报告中毛利率/ROE 显示为 0.0%
- **B3: 字段名修正**: `n_cashflow_fin_act` → `n_cash_flows_fnc_act` (Tushare 官方字段名)
- **B4: 缺失实现**: gross_profit 硬编码 0→revenue-oper_cost; volatility_1y 硬编码 0→252 日对数收益率年化波动率
- **B5: payout_ratio**: Tushare dividend API 不返回该字段 → 自算 DPS/EPS×100
- **验证**: 贵州茅台 600519.SH 14/14 检查通过; 全量 42 只候选股 100% 拉取成功, 股池 PR 2.12%~6.46%

## v0.3.0 QRV 升级 (2026-06-17)
- CQ/PR: 硬门→软门（标记不淘汰）
- Step 8+9: 基本面+估值门 → QRV Agent 单次LLM(3维度8模块)
- WebSearch: 5次Tavily搜索（Q商模+护城河、R1外部、R2管理层、R3控股、V估值）
- 数据流: 统一 qrv_input.yaml（raw+computed+screener+gate+websearch）
- QRV: 只出定性结论，不打分A-F
- Brave 搜索已移除，只保留 Tavily
- 新增 `qrv_agent.py` CLI 工具: `python -m app.services.qrv_agent --ts_code 600900.SH`

## AI Agent 规则
- `.codebuddy/rules/rules.md` — 7 条强制规则，每次会话自动注入 (2026-06-23)
  1. 工作流：先文档后代码，闭环更新项目文件
  2. 策略上下文自动加载：命中关键词 → 加载对应 SPEC 文档（龟龟→turtle-coordinator.md）
  3. 配置：`.env` 最高权威
  4. 数据：Tushare 字段名一字不改，输出用中文名+股票代码
  5. 缓存：新字段=全量重拉
  6. 测试：pytest 全绿才算完成
  7. 环境：PowerShell 不重定向
- 策略专属规则（公式四件套/硬门确定性/测试铁律）已下沉到各策略 SPEC 文档的「维护规则」章节

## 字段对照表
- `docs/TUSHARE_FIELDS.md` — Tushare 字段↔中文含义完整对照 (2026-06-17)
- ~~Bug: `c_pay_for_tan_il` 不存在~~ → 已修复为 `c_pay_acq_const_fiolta` (2026-06-17)
- PR v2 新增字段: `n_disp_subs_oth_biz`(并购), `lt_eqt_invest`(长投), `fin_exp`(财费-利润表)
- PR v2 字段重命名: cashflow `interest_expense` → `finan_exp`

## v0.2.1 关键修复 (2026-06-17)
- **`--force` 不重拉个股 Bug**: `coordinator.run_full_refresh()` 缺少 `force` 参数 → 新增透传链路
- **API 未指定 fields**: `tushare_client.py` 的 `get_income()`/`get_balance_sheet()`/`get_cashflow()` 显式指定所有 PR v2 必需字段
- **`_safe_float(None)` 静默兜底**: 增加 `field_name` 参数，缺失时 WARNING 日志
- **文档同步**: `turtle-coordinator.md` Step 3 补上 v2 PR 公式引用 + `CONTEXT.md` v0.2.1
- **全量重拉验证**: `--force` 刷新 40 只候选股 → 16 只入池 (PR 2.73%~6.14%)
- **测试**: 55/55 全绿
- **缓存命名**: 新目录统一用 ts_code（如 `600398.SH/`），旧中文名目录（如 `海澜之家_600398.SH/`）为孤儿，待清理

## v0.4.0 QRV v2 定量升级 (2026-06-18)
- **根因**: v0.3.0 QRV 报告"虚"—LLM 输出缺乏具体数字（"收入来源多元化"无金额/占比/增速）
- **DataSummarizer**: 新增 `data_summarizer.py`，从 raw+computed+websearch 提取 A1-A6 六块结构化摘要
- **去截断**: `qrv_agent._build_prompt()` 移除 30K 字符截断，改为 data_summary + 完整 websearch + 原始财务
- **Prompt v2**: `turtle_qrv.yaml` 约 1500 字强制量化模板，12 张强制表格，max_tokens→16384
- **WebSearch 增强**: 每模块 2-3 个 keywords，新增收入结构/分红回购/竞争格局等搜索
- **测试**: 新增 12 个 data_summarizer 测试，全量 74/74 通过

## v0.5.0 框架扩展 + DataSummarizer v2 (2026-06-18)
- **A1 扩展**: 9字段→26字段 (EPS/FCF/CAPEX/商誉/固定资产比/应收周转/存货周转等)
- **A7 新增生意属性**: 收款方式分类(先款后货/现款现货)、资产类型(轻/重)、CAPEX模式(扩张/维持/吃老本)
- **Layer 3 数据充分性评估**: 每维度 rich/partial/missing 三级, LLM 知道哪些跳过
- **WebSearchExtractor**: 规则引擎从 websearch 预提取 7 类结构化事实 (零LLM调用)
- **行业配置文件**: `industry_profiles.yaml` 按行业动态适配 (IT→研发人员,银行→不良率)
- **框架扩展**: 8模块→10维度 (Q1生意本质 + Q3增长引擎 + Q2护城河可攻破性 + R1国家战略 + R2人才结构)
- **测试**: 76/76 全部通过

## v0.5.1 QRV Bug修复 + URL证据链 (2026-06-18)
- **Bug 1: 总市值N/A**: `_a6_valuation_snapshot` 中 `total_mv` 已是亿元单位但多除了 1e8 → 改为自适应判断
- **Bug 2: PR 213%**: `_a5_pr_detail` 中 `pr`/`threshold` 已在 computed.yaml 存为百分比形式但多乘了 100 → 移除 ×100
- **人均薪酬**: `turtle_qrv.yaml` R2 websearch 关键词新增「人均薪酬 应付职工薪酬」
- **URL证据链**: `data_summarizer._build_reference_index()` 从 websearch 提取所有 snippet URL → prompt 末尾要求「参考来源」章节映射 `[W-*]` → URL
- **测试**: 76/76 全部通过

## v0.6.3 性能三件套 + 打分卡 (2026-06-19)
- **① 后端内存索引**: `_build_stock_index()` 启动时扫描 1 次 → `_find_stock_dir()` 从 O(n) 遍历变为 O(1) 查表
- **② 个股缓存**: `/gates` + `/analysis` 10min TTL, `/analyze` 触发时清除
- **③ 前端 hover 预加载**: StockPool `onMouseEnter` 250ms→`prefetchQuery`, `has_report=true` 才预取
- **④ ScoreCard**: 报告顶部 9 维度打分卡, 默认展开, 从 qrv_analysis.json→GateResult.scores 传递
- **Pool API**: 复用索引 + 新增 `has_report` 字段
- **涉及文件**: stocks.py, types.ts, StockPool.tsx, ReportViewer.tsx, ScoreCard.tsx(新), ScoreCard.module.css(新), Sidebar.tsx, CHANGELOG.md, CONTEXT.md

### Phase C — 代码质量
- **C2**: `cash_quality.py` 默认 rule_version "v1"→"v2"，消除静默降级风险
- **C7**: `run_single_stock_analysis.py` 股票名拉取失败加 WARNING 日志
- **C6**: `data_summarizer.py` A3 回购按年份分组聚合（对齐分红逻辑）
- **C1**: 删除破损 HTML 渲染（render_qrv_html 模块不存在 + entry 变量未定义）
- **C5**: 选股器 8 个阈值 `.env` 化（config.py 新增 setting → screener 读 settings）
- **C3**: 提取公共 `find_stock_dir` → 新文件 `backend/app/strategies/turtle/utils.py`

### Phase B — 数据完整性
- **B1**: WebSearch 7 天缓存复用 + `--force-websearch` 强制重搜
- **B2**: PE/PB/股息率历史分位（A8_valuation_percentile），dv_ratio 字段补全
- **B3**: 行业对标数据（industry_stats.yaml），注入 A6 估值快照

### 影响
- 测试: 76/76 全部通过
- 迁移: B2 存量数据缺少 dv_ratio 需要 `--full` 重拉后补齐

## v0.5.2 数据完整性大修 + 双文件夹Bug + LLM截断 (2026-06-18)
- **Tushare 全量字段**: `get_income`/`get_balance_sheet`/`get_cashflow` 去除 fields 限制，从 ~40 字段扩展到 ~300 字段全量拉取
- **raw_data 扩展**: 新增 sell_exp/admin_exp/rd_exp/total_profit/operate_cost/net_margin 等字段到 raw_data.yaml
- **双文件夹 Bug**: raw_data→{ts_code}/, computed→{name}_{ts_code}/ 导致 CQ/PR 数据丢失 → `_find_stock_dir` 先匹配 {name}_{ts_code} + run_single_stock 路径对齐
- **LLM 截断**: LLM_MAX_TOKENS 8192→32768 + finish_reason=="length" 截断检测
- **×100 Bug**: data_summarizer 的 gross_margin_pct/roe_pct/net_margin_pct 不再 ×100（raw_data 中已是百分比值）
- **A1 费用端**: 新增费用率 + 费用绝对额 9 个字段
- **数据流**: Tushare→client全量→fetcher全量写入→raw_data.yaml(~100字段/年)→summarizer按需取
- **测试**: 76/76 全部通过
