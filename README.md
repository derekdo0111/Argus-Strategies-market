# Investment Strategy

> 个人投资策略分析平台 | v0.6.15
>龟龟策略-->已实现    目前实现的策略基于（类红利股）的全流程 A 股分析工具：选股 → 硬门筛选 → QRV 深度报告，从全市场自动筛选出高质量标的并生成 10 维度量化报告。
>高景气价值策略 -->待开发
> 
<img width="1865" height="842" alt="image" src="https://github.com/user-attachments/assets/88fd0d42-7017-4599-9814-6521989a6e09" />

---

## 核心策略

### 龟龟策略 (Turtle Strategy)

在现金质量有保证的前提下，通过**穿透回报率**筛选高回报标的。

```
全A股 → 选股器(市值/ROE/PE/PB/股息率/毛利率/负债率) → CQ门(现金质量5维) → PR门(穿透回报率) → QRV深度分析
```

- **选股器**: 8 阈值初筛，约 80-150 只候选
- **CQ 门** (软门): 经营现金流/自由现金流/应收账款/存货/减值率 5 维度
- **PR 门** (软门): 穿透回报率 = (可支配现金 × 分配比率 + 回购注销) / 总市值
- **QRV Agent**: LLM 综合分析，Q 质量(生意本质+护城河+增长) + R 韧性(外部环境+管理层+控股) + V 估值(价值陷阱+历史分位+压力测试)

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
| **测试** | pytest 76 测试 + Playwright E2E 13 用例 |

---

## 项目结构

```
├── backend/                FastAPI 后端
│   ├── app/
│   │   ├── api/            REST 端点 (stocks, strategies)
│   │   ├── core/           配置 / 日志 / trace_id
│   │   ├── strategies/turtle/  龟龟策略 (选股器/CQ/PR/Coordinator)
│   │   └── services/       QRV Agent / WebSearch / 数据拉取 / DataSummarizer
│   ├── rules/v2/           规则定义 (screener/cq/pr/qrv)
│   ├── tests/              76 个测试用例
│   └── .env.example        环境变量模板
├── frontend/               React SPA
│   ├── src/
│   │   ├── components/     布局/侧栏/股池/报告查看器/打分卡
│   │   └── hooks/          API hooks + 轮询
│   └── tests/e2e/          Playwright E2E (13 用例)
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
| 单元测试 | 76 | 选股器 / CQ / PR / SPEC 合规 / DataSummarizer |
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
