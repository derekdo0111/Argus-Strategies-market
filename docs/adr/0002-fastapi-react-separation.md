# ADR-0002: FastAPI + React 分离架构

- **日期**: 2026-06-15
- **状态**: 已接受

## 上下文

需要选择后端和前端技术栈。主要考虑：
1. 数据计算密集，需要 Python 生态（Tushare、Pandas）
2. 前端需要现代交互体验（虚拟滚动、异步加载）
3. 前后端职责清晰分离

## 决策

- **后端**: FastAPI (Python)，负责数据拉取、确定性计算、LLM编排、API服务
- **前端**: React 18 + TypeScript + Vite，负责三栏布局展示、虚拟滚动、Markdown渲染
- **数据库**: SQLite，轻量级，无需独立数据库服务
- **通信**: REST API（JSON），无 WebSocket（暂不需要实时推送）

## 替代方案

- **Django + 模板渲染**: 不适合复杂前端交互，放弃
- **Next.js 全栈**: Python 数据计算生态不足，放弃
- **Go 后端**: Tushare/LLM 生态不如 Python，放弃

## 后果

- 两个独立进程，需要分别部署/开发
- 开发时需要同时启动前后端（可配置代理）
- 前端可独立部署到 CDN
