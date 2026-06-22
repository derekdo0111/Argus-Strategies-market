# Investment Strategy — 领域上下文

> 版本: v0.8.0 | 更新: 2026-06-22

---

## 项目目标

个人投资策略分析网站。用户通过左侧策略列表选择策略，中间区域展示该策略产出的股池，右侧展示单股详细分析报告。

## 核心领域语言 (Ubiquitous Language)

### 策略注册表 (Registry)
- **`app/core/registry.py`**: 所有策略元信息的唯一真相来源。加新策略只需在此注册 + 新建策略目录。
- 策略列表通过 `GET /api/strategies` 动态返回，前端 Sidebar 自动渲染。

### 策略 (Strategy)
- **龟龟策略 (Turtle Strategy)**: 类红利股策略，核心逻辑：在现金质量有保证的前提下，通过穿透回报率筛选高回报标的。
- **高景气价值股策略 (High-Prosperity Value)**: 预留策略槽位，开发中。

### 选股与门控 (龟龟策略)
- **选股器 (Screener)**: 11 条件规则引擎，从全A股中过滤出候选池。输出约 80-150 只候选。
- **门 (Gate)**: CQ/PR 为软门（标记不淘汰），判定结果交 QRV Agent 综合研判。
- **股池 (Stock Pool)**: 通过选股器 + 确定性计算的股票列表，按穿透回报率降序。可支配现金均值 ≤ 0 硬排除。

### 龟龟策略流程

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

### QRV 分析框架 (龟龟策略)

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

### 核心公式 (龟龟策略)
- **穿透回报率 (PR)**: PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%
- **可支配现金（5年逐期）**: 经营CF − CAPEX − 并购子公司 − max(0, 长投净增) − 财务费用
- **现金质量8子维度**: 见 `rules/v2/turtle_cash_quality.yaml`

---

## 技术架构 (v0.8.0 双策略平台)

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
│   │   └── prosperity/              ← 高景气策略占位
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
│       └── prosperity/              ← 高景气策略（待开发）
├── rules/
│   ├── v2/                          ← 龟龟规则
│   └── v3/                          ← 高景气规则（预留）
└── tests/

data/stock_cache/
├── turtle/                          ← 龟龟数据（42 个股）
│   ├── {name}_{ts_code}/
│   │   └── raw_data.yaml / computed.yaml / ...
│   ├── pool.json
│   └── candidate_pool.yaml
└── prosperity/                      ← 高景气预留
```

---

## 加新策略流程

```
1. registry.py — 注册新策略（1 段 StrategyMeta）
2. strategies/{id}/ — 写 api.py + coordinator.py + screener.py + ...
3. data/stock_cache/{id}/ — mkdir
4. components/{id}/ — 写 StockPool.tsx + ReportViewer.tsx
5. Layout.tsx 组件映射表 — 加 1 行

不改 main.py、不改 Sidebar、不改 config.py
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

- **测试**: pytest 98 单元+SPEC合规 | vitest 37 前端
- **规则版本化**: `rules/v{N}/` 目录
- **Trace**: structlog + trace_id
- **配置优先级**: `.env` > `config.py` 默认值
