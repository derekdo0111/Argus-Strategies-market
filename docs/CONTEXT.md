# Investment Strategy — 领域上下文

> 版本: v0.6.15 | 更新: 2026-06-19

---

## 项目目标

个人投资策略分析网站。用户通过左侧策略列表选择策略，中间区域展示该策略产出的股池，右侧展示单股详细分析报告。

## 核心领域语言 (Ubiquitous Language)

### 策略 (Strategy)
- **龟龟策略 (Turtle Strategy)**: 类红利股策略，核心逻辑：在现金质量有保证的前提下，通过穿透回报率筛选高回报标的。
- **高景气价值股策略 (High-Prosperity Value)**: 预留策略槽位，后续实现。

### 选股与门控
- **选股器 (Screener)**: 每个策略的初筛条件，从全A股中过滤出候选池。输出约 80-150 只候选。
- **门 (Gate)**: 候选池中的个股依次通过的门控检查。
  - v0.2.x: CQ/PR 为硬门（不通过即淘汰），基本面/估值为软门（标记不淘汰）
  - **v0.3.0**: **全部改为软门**（标记不淘汰），CQ/PR 判定结果交 QRV Agent 综合研判
- **股池 (Stock Pool)**: 通过选股器筛选 + 确定性计算完成的股票列表，按穿透回报率降序排列。

### 龟龟策略流程 (v0.5.0)

```
Step 1: 选股器 → candidate_pool.yaml
Step 2: 数据拉取 → raw_data.yaml
Step 3: 确定性计算 → computed.yaml (CQ + PR)
Step 4: CQ门 [软门] → 标记通过/未通过
Step 5: PR门 [软门] → 标记通过/未通过 → 股池
Step 6: 统一数据包 → qrv_input.yaml
Step 7: WebSearch → 5次Tavily搜索 → websearch.yaml
Step 7.5: WebSearchExtractor → 预提取结构化事实 ★v0.5.0
Step 8: QRV Agent v3 → DataSummarizer v2预处理 → 单次LLM → qrv_analysis.md + .json
```

### QRV 分析框架 (v0.5.0 重大升级)
取代原 Step 8 (基本面门) + Step 9 (估值门)，单次 LLM 综合分析。

**v0.5.0 重大升级**：
- **DataSummarizer v2**: A1 从 9 字段扩展到 20+ 字段 (EPS/FCF/CAPEX/商誉/应收周转/存货周转等)
- **新增 A7 生意属性**: 收款方式(应收周转天数)、轻/重资产(固定资产占比)、CAPEX模式(扩张/维持/吃老本)
- **Layer 3 数据充分性评估**: 告诉 LLM 每维度 rich/partial/missing，missing 直接跳过
- **WebSearchExtractor (Layer 2)**: 规则引擎从 websearch 预提取 收入结构/市占率/管理层事实/人才/国家政策
- **行业配置文件**: `industry_profiles.yaml` 按行业动态适配额外指标 (IT设备→研发人员占比,银行→不良率)
- **Prompt v3**: Q1 扩展生意本质、Q3 新增增长引擎、R2 新增人才结构、打分卡 8→10 维度

| 维度 | 模块 | 内容 |
|------|------|------|
| **Q (Quality)** | Q1 生意本质+商业模式 | 卖什么/怎么卖/上下游/收款方式/轻资产、收入结构、盈利质量趋势 |
| | Q2 护城河+可攻破性 | 市占率/研发/成本/外来者威胁评估 |
| | Q3 增长引擎 | 量价驱动拆分、第二曲线进度、产能扩张(CAPEX/折旧) |
| **R (Resilience)** | R1 外部环境+国家战略 | 行业周期、风险清单、国家规划定位 |
| | R2 管理层+人才结构 | 管理层画像、分红回购、研发人员占比/人均创收 |
| | R3 控股结构 | 实控人风险、关联交易 |
| **V (Valuation)** | V1 价值陷阱 | CQ 5维度 + 资产负债快照 |
| | V2 历史分位 | PE/PB/股息率历史位置 + 同行对比 |
| | V3 压力测试 | PR穿透回报率 + 三情景预估 |

### 核心公式
- **穿透回报率 (PR)** v2: PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%
- **可支配现金（5年逐期）**: 经营CF − CAPEX − 并购子公司 − max(0, 长投净增) − 财务费用
- **现金质量5子维度**: 见 `rules/v2/turtle_cash_quality.yaml`

### 数据流
- **全量刷新**: 选股器 → 数据拉取(**v0.5.3: 入口归一化亿元**) → 确定性计算 → 软门标记 → 股池。定时任务触发。
- **按需分析**: 单股点击 → 统一数据包(qrv_input.yaml) → WebSearch(5次Tavily) → DataSummarizer预处理 → QRV Agent(单次LLM) → 报告。
- **数据缓存**: Tushare全量数据拉取后**归一化为亿元**存入本地YAML，后续计算只读缓存。
- **单位规范**: 参见 `docs/TUSHARE_UNITS.md`，所有 raw_data.yaml 金额字段统一为亿元。

### 技术角色
- **Coordinator**: 混合模式编排器。`turtle-coordinator.md` 定义流程，`coordinator.py` 执行编排。
- **WebSearch Agent**: Tavily API 联网搜索，5次搜索覆盖Q/R/V，输出带置信度标注。
- **WebSearchExtractor** (v0.5.0): 规则引擎从 websearch 预提取结构化事实 (收入结构/市占率/管理层/人才/政策)。
- **DataSummarizer** (v2.0.0): 预处理引擎，A1 20+字段 + A7 生意属性 + Layer 3 数据充分性评估，按行业动态加载 profile。
- **QRV Agent**: Q/R/V 三维度综合分析，CFA角色单次LLM调用，输出 `qrv_analysis.md` + `.json`。

---

## 技术架构

```
frontend/          React 18 + TypeScript + Vite
backend/           Python FastAPI
  app/
    api/           REST API 路由
    core/          配置、日志、数据库连接
    strategies/
      turtle/      龟龟策略（选股器、门控、PR计算、Coordinator）
    services/      QRV Agent、WebSearch、数据拉取
    models/        SQLAlchemy 模型
  tests/           测试
  alembic/         数据库迁移
  rules/v2/        规则版本化
data/
  templates/       数据模板 Schema
  stock_cache/     个股数据缓存
scripts/           运维脚本
docs/
  adr/             架构决策记录
```

## 数据缓存结构

```
stock_cache/{ts_code}/
├── raw_data.yaml        # Tushare原始数据
├── computed.yaml        # 确定性计算结果
├── qrv_input.yaml       # v0.4.0: 统一数据包
├── websearch.yaml       # WebSearch结果
├── qrv_analysis.md      # QRV Agent v2 Markdown报告（含量化表格）
└── qrv_analysis.json    # QRV Agent 结构化数据
```

## 质量保障

- **测试**: pytest 单元测试 + SPEC 合规测试
- **版本管理**: 规则版本化 `rules/v{N}/` + Alembic 迁移
- **Trace**: structlog + trace_id
