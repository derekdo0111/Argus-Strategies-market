# Argus-Strategies-market

## 个人投资策略分析平台 | v1.2.2

### 龟龟策略 ✅ 运行中
全流程 A 股分析工具：选股 → 软门筛选 → QRV 深度报告，从全市场自动筛选出高质量标的并生成 10 维度量化报告。

<img width="1897" height="860" alt="1" src="https://github.com/user-attachments/assets/a582817b-1b47-442a-abda-ce7a38339cdd" />

### 高景气策略 ✅ 运行中
LLM 多 Agent 认知循环体系：搜索 → 产业学习 → 假设形成 → 交叉验证 → 反推修正 → 精选股池 → 综合报告。基于产业链拓扑和 Wiki-Centric 知识复用，实现假设驱动的行业景气分析。
**前端 UI**: 四层推理链脑图（L0 现状→L1 推演→L2 矛盾→L3 落点）+ 扇区概念板块导航 + 上中下游股票面板 + 六维 SVG 雷达图，色系与全局设计系统统一。
<img width="1862" height="855" alt="image" src="https://github.com/user-attachments/assets/557e32d1-72b6-4d3a-b48c-7de784f74842" />

---

## 核心策略

### 龟龟策略 (Turtle Strategy)

在现金质量有保证的前提下，通过**穿透回报率**筛选高回报标的。

```
全A股 → 选股器(市值/ROE/PE/PB/股息率/毛利率/负债率) → CQ门(现金质量8维) → PR门(穿透回报率) → QRV深度分析
```

- **选股器**: 8 阈值初筛，约 80-150 只候选
- **CQ 门** (软门): 经营现金流/自由现金流/应收账款/存货/减值率/FCF分红覆盖/供应商挤压/有息负债趋势 8 维度
- **PR 门** (软门): 穿透回报率 = (可支配现金 × 分配比率 + 回购注销) / 总市值
- **QRV Agent**: LLM 综合分析，Q 质量(生意本质+护城河+增长) + R 韧性(外部环境+管理层+控股) + V 估值(价值陷阱+历史分位+压力测试)

### 高景气策略 (Prosperity Strategy)

基于 LLM 的 7 阶段推理链驱动分析：

```
搜索 → 产业学习(构建Wiki) → 假设形成(L0-L3) → 交叉验证(3轮投票) → 反推修正(级联裁决) → 精选股池(分段LLM) → 综合报告
```

- **SearchAgent**: Tavily 定向搜索 + 行业 registry
- **LearningAgent**: 首次构建产业图谱 YAML，后续零成本复用
- **HypothesizeAgent**: 4 层因果推理链 (现状→一阶→二阶→投资落点)
- **VerifyAgent**: 3 轮并行 LLM 交叉验证 + 字段级聚合
- **CounterAgent**: 语义级联裁决 + 反推修正
- **ScreeningAgent**: 程序化预筛 → 分段 LLM 精选 → 三维打分
- **ReportAgent**: Mermaid 推理链图 + 分章节叙事

---

## 技术栈

| 层 | 技术 |
|---|------|
| **前端** | React 18 + TypeScript + Vite 6 |
| **状态** | React Query v5 (缓存/轮询) + Zustand |
| **Markdown** | react-markdown + remark-gfm + rehype-raw + rehype-sanitize |
| **后端** | Python 3.11 + FastAPI + Uvicorn |
| **数据** | Tushare (主) + AKShare (备) + YAML 本地缓存 |
| **LLM** | DeepSeek V4 (OpenAI 兼容) |
| **搜索** | Tavily API |
| **测试** | pytest 98 测试 + Playwright E2E 13 用例 |

---

## 项目结构

```
├── backend/                FastAPI 后端
│   ├── app/
│   │   ├── api/            REST 端点 (stocks, strategies)
│   │   ├── core/           配置 / 日志 / trace_id
│   │   ├── strategies/turtle/       龟龟策略 (选股器/CQ/PR/Coordinator)
│   │   ├── strategies/prosperity/   高景气策略 (7 阶段推理链 / 多 Agent)
│   │   └── services/                QRV Agent / WebSearch / 数据拉取 / DataSummarizer
│   ├── rules/v2/           规则定义 (screener/cq/pr/qrv)
│   ├── tests/              98 个测试用例
│   └── .env.example        环境变量模板
├── frontend/               React SPA
│   ├── src/
│   │   ├── components/
│   │   │   ├── turtle/       龟龟策略 UI（股池/报告/打分卡）
│   │   │   └── prosperity/   高景气 UI（脑图/股票面板/扇区导航/雷达图）
│   │   └── hooks/          API hooks + 轮询
│   ├── mockups/            UI 设计原型
│   └── tests/e2e/          Playwright E2E (13 用例)
├── start.bat               一键启动后端+前端
├── data/
│   ├── stock_cache/        个股缓存 (raw/computed/websearch/qrv_analysis)
│   └── templates/          数据 Schema
├── docs/                   项目文档 + ADR
├── scripts/                运维脚本
└── CHANGELOG.md            版本变更记录
```

---

## 快速开始

### 1. 环境准备

```bash
# Python 3.11+
cd backend
pip install poetry
poetry install

# Node.js 18+
cd frontend
npm install
```

### 2. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env 填入你的 API Key:
#   TUSHARE_TOKEN    — Tushare Pro token (tushare.pro)
#   LLM_API_KEY       — DeepSeek API key
#   TAVILY_API_KEY    — Tavily search key
```

### 3. 拉取数据（首次）

```bash
cd backend
python -m scripts.run_turtle_refresh --full
```

### 4. 启动服务

```bash
# 一键启动（推荐）
start.bat

# 或分别启动：
# 后端 (端口 8000)
cd backend
uvicorn app.main:app --reload

# 前端 (端口 5173)
cd frontend
npm run dev
```

浏览器打开 `http://localhost:5173`

---

## 常用命令

```bash
# 运行全部测试
cd backend && pytest tests/ -v

# 前端 E2E 测试
cd frontend && npm test

# 单股分析
cd backend && python -m scripts.run_single_stock_analysis --ts_code 600519.SH

# 诊断脚本（4步独立测试）
cd backend && python -m scripts.diagnose_analyze 600900.SH
```

---

## 测试

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元测试 | 98 | 选股器 / CQ / PR / SPEC 合规 / DataSummarizer / WebSearchExtractor |
| E2E | 13 | Playwright Chromium, `page.route()` 零后端依赖 |

---

## 版本策略

- **代码版本**: `pyproject.toml` / `CHANGELOG.md`
- **规则版本化**: `rules/v{N}/` 语义化迭代，当前 v2
- **数据缓存**: 新增字段需 `--full` 全量重拉

---

## 部署

- 本地开发: `uvicorn` + `vite`
- 服务器: 通过 Lighthouse 集成一键部署（需 Docker）

---

## 许可证

个人项目，仅供学习参考。数据来源 Tushare/AKShare 请遵守其使用条款。
