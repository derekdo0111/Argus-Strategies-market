# Investment Strategy — 领域上下文

> 版本: v0.16.0 | 更新: 2026-07-01

---

## 项目目标

个人投资策略分析网站。用户通过左侧策略列表选择策略，中间区域展示该策略产出的股池，右侧展示单股详细分析报告。

## 核心领域语言 (Ubiquitous Language)

### 策略注册表 (Registry)
- **`app/core/registry.py`**: 所有策略元信息的唯一真相来源。加新策略只需在此注册 + 新建策略目录。
- 策略列表通过 `GET /api/strategies` 动态返回，前端 Sidebar 自动渲染。

### 策略概览

| 策略 | 状态 | 核心逻辑 |
|------|:--:|------|
| 龟龟策略 (Turtle) | ✅ 运行中 | 现金质量 + 穿透回报率 |
| 高景气策略 (Prosperity) | ✅ 运行中 | 4层因果推理链 (L0→L3) + LLM 假设驱动行业研究 + 知识库沉淀 |

### 高景气策略 (Prosperity Strategy)

> 详细设计 SPEC 见 `docs/specs/2026-06-29-prosperity-strategy-design.md`

#### 核心范式
- **假设驱动研究（v2 因果链）**：输入行业 → 情报搜索 → 假设形成（4层 L0→L3） → 交叉验证（LLM 串行验证推理链，含反例搜索+修正版输出） → 股池筛选（LLM 方向匹配 + 财务打分 50/50） → 叙事报告
- **5 Agent 认知循环**：SearchAgent / HypothesizeAgent / VerifyAgent / ScreeningAgent / ReportAgent / TrackAgent
- **4层因果推理链**：L0 现状诊断 → L1 一阶推演 → L2 二阶推演+拐点 → L3 投资落点。每条假设有 derives_from 因果箭头 + sentiment 方向 + causality_strength 因果强度。
- **级联状态**：上游 OVERTURNED（已证伪）→ 下游 🚫 UNREACHABLE，不参与评级。DISPUTED（证据不足）不触发级联。LLM 验证 + 确定性后处理双保险。
- **LLM Wiki 知识库**：融合 Karpathy LLM Wiki 理念，假设页保留验证历史 + 修正陈述 + 反例证据。
- **双形态共用核心**：CodeBuddy Skills（对话式）+ Web 管道式，共用同一套 Agent + 确定性脚本

> v0.16 核心增强 Spec: `docs/specs/2026-07-01-prosperity-strategy-v16-enhancement.md`

#### 知识库架构
```
data/prosperity/
├── raw/{industry}/            ← 原始资料（只读）
├── wiki/                      ← LLM 维护的知识页面
│   ├── industries/            ← 行业总览页
│   ├── hypotheses/            ← 假设页（含验证历史+修正陈述+反例证据）
│   ├── concepts/              ← 通用概念（跨行业复用）
│   ├── comparisons/           ← 横向对比页
│   └── synthesis/             ← 综合报告
├── tracking/watchlist.yaml    ← 跟踪项
└── prosperity.db              ← SQLite 结构化数据
```

#### 确定性脚本（防幻觉）
- `industry_metrics.py` — 行业聚合指标（通用指标自动算 + 专属指标按 profile 配）
- `stock_screener.py` — 行业内百分位排名打分（含真实动量，非绝对阈值）
- `screening_agent.py` — LLM 方向匹配 + 财务打分 50/50 融合（新增 v0.16）
- `source_crawler.py` — Tier 2 行业数据爬取（价格/产能/渗透率）
- `wiki_indexer.py` — Wiki 索引维护

### 龟龟策略 (Turtle Strategy)

> 详细 SPEC 见 `backend/app/strategies/turtle/turtle-coordinator.md`

#### 选股与门控
- **选股器 (Screener)**: 11 条件规则引擎，从全A股中过滤出候选池。输出约 80-150 只候选。
- **门 (Gate)**: CQ/PR 为软门（标记不淘汰），判定结果交 QRV Agent 综合研判。
- **股池 (Stock Pool)**: 通过选股器 + 确定性计算的股票列表，按穿透回报率降序。可支配现金均值 ≤ 0 硬排除。

#### 策略流程

```
Step 1: 选股器 → candidate_pool.yaml
Step 2: 数据拉取 → raw_data.yaml
Step 3: 确定性计算 → computed.yaml (CQ + PR)
Step 4: CQ门 [软门] → 标记通过/未通过
Step 5: PR门 [软门] → 标记通过/未通过 → 股池
Step 6: 统一数据包 → qrv_input.yaml
Step 7: WebSearch → 5次Tavily搜索 → websearch.yaml
Step 8: QRV Agent → DataSummarizer预处理 → 单次LLM → qrv_analysis.md + .json
```

#### QRV 分析框架

| 维度 | 模块 | 内容 |
|------|------|------|
| **Q (Quality)** | Q1 生意本质+商业模式 | 卖什么/怎么卖/上下游/收款方式/轻资产 |
| | Q2 护城河+可攻破性 | 市占率/研发/成本/外来者威胁 |
| | Q3 增长引擎 | 量价驱动拆分、第二曲线、产能扩张 |
| **R (Resilience)** | R1 外部环境+国家战略 | 行业周期、风险清单、国家规划 |
| | R2 管理层+人才结构 | 管理层画像、分红回购、研发占比 |
| | R3 控股结构 | 实控人风险、关联交易 |
| | R4 重大事件与资本运作 | 定增/并购/重组/重大合同/诉讼 |
| **V (Valuation)** | V1 价值陷阱 | CQ 8维度 + 资产负债快照 |
| | V2 历史分位 | PE/PB/股息率历史位置 + 同行对比 |
| | V3 压力测试 | PR穿透回报率 + 三情景预估 |

#### 核心公式
- **穿透回报率 (PR)**: PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%
- **可支配现金（5年逐期）**: 经营CF − CAPEX − 并购子公司 − max(0, 长投净增) − 财务费用
- **现金质量8子维度**: 见 `rules/v2/turtle_cash_quality.yaml`

---

## 技术架构 (v0.8.0)

```
frontend/
├── src/
│   ├── components/
│   │   ├── Layout.tsx               ← 策略分发（组件映射表）
│   │   ├── Sidebar.tsx              ← 动态策略列表（GET /api/strategies）
│   │   ├── ResizablePanel.tsx       ← 拖拽面板
│   │   ├── turtle/                  ← 龟龟策略专属组件
│   │   │   ├── StockPool.tsx        ← 龟龟股池表格
│   │   │   ├── ScoreCard.tsx        ← 龟龟 QRV 打分卡
│   │   │   └── ReportViewer.tsx     ← 龟龟 Markdown 报告
│   └── types.ts

backend/
├── app/
│   ├── main.py                      ← 遍历 registry 自动挂载路由
│   ├── core/
│   │   ├── config.py                ← .env 配置（共享）
│   │   ├── logging.py               ← structlog（共享）
│   │   └── registry.py              ← ★ 策略注册表
│   ├── api/
│   │   └── strategies.py            ← 从 registry 读取策略列表
│   ├── services/                    ← 纯基础设施（共享）
│   │   ├── tushare_client.py        ← Tushare API 封装
│   │   └── data_fetcher.py          ← 数据拉取 → raw_data.yaml
│   └── strategies/
│       ├── turtle/                  ← 龟龟策略（自包含）
│       │   ├── api.py               ← API 端点 /api/turtle/*
│       │   ├── screener.py          ← 选股器
│       │   ├── cash_quality.py      ← CQ 门
│       │   ├── penetration_return.py← PR 计算
│       │   ├── coordinator.py       ← 流程编排
│       │   ├── qrv_agent.py         ← QRV LLM 分析
│       │   ├── data_summarizer.py   ← 数据预处理
│       │   ├── websearch_extractor.py← 搜索提取器
│       │   └── utils.py
├── rules/
│   └── v2/                          ← 龟龟规则
└── tests/

data/
├── stock_cache/
│   ├── turtle/                      ← 龟龟数据（42 个股）
│   │   ├── {name}_{ts_code}/
│   │   │   └── raw_data.yaml / computed.yaml / ...
│   │   ├── pool.json
│   │   └── candidate_pool.yaml
```

---

## 加新策略流程

```
1. registry.py — 注册新策略（1 段 StrategyMeta）
2. strategies/{id}/ — 写 api.py + coordinator.py + screener.py + ...
3. data/stock_cache/{id}/ — mkdir（或独立 data 目录）
4. components/{id}/ — 写 StockPool.tsx + ReportViewer.tsx（或 MVP 后补）
5. Layout.tsx 组件映射表 — 加 1 行

不改 main.py、不改 Sidebar、不改 config.py
```

### 高景气策略隔离
```
strategies/prosperity/     ← 独立目录
data/prosperity/           ← 独立数据（非 stock_cache 下）
/api/prosperity/*          ← 独立 API 前缀
components/prosperity/     ← 独立前端组件（MVP 后）
共享: tushare_client.py / config.py / logging.py
```

---

## 数据缓存结构

```
stock_cache/turtle/{name}_{ts_code}/
├── raw_data.yaml        # Tushare原始数据
├── computed.yaml        # 确定性计算结果 (CQ+PR)
├── qrv_input.yaml       # QRV统一数据包
├── websearch.yaml       # WebSearch结果（含置信度）
├── qrv_analysis.md      # QRV Agent Markdown报告
└── qrv_analysis.json    # QRV Agent 结构化数据
```

---

## 质量保障

- **测试**: pytest 龟龟策略单元+SPEC合规 | vitest 37 前端
- **规则版本化**: `rules/v{N}/` 目录
- **Trace**: structlog + trace_id
- **配置优先级**: `.env` > `config.py` 默认值
