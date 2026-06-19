# Changelog

All notable changes to Investment Strategy project.

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
