# Investment Strategy — 长期记忆

## 项目位置
- `D:\project\Investment Strategy\` — 投资策略分析个人网站
- 独立项目，与 `D:\project\stock-analysis-framework\` 无关

## 核心设计
- **龟龟策略**: 类红利股，现金质量+穿透回报率，四门筛选
- **技术栈**: FastAPI + React 18 + SQLite + YAML数据缓存
- **Coordinator**: 混合模式 (turtle-coordinator.md 流程定义 + coordinator.py 编排执行)
- **全量刷新只到硬门**: 定时任务跑选股+现金质量+PR门，LLM分析按需触发
- **规则版本化**: rules/v{N}/ 目录，语义化版本

## 用户偏好
- 所有项目文件夹创建在 D:\project\ 下
- 数据源 Tushare 为主，AKShare 备用
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

## 版本号 (v0.6.15 / 2026-06-19)
- 全局版本: `pyproject.toml`, `main.py`, `config.py`, `CONTEXT.md` — 统一为 `0.6.15`
- 规则版本: 当前使用 **v2**（`rules/v2/` 目录），代码默认值统一为 `"v2"`
- `CHANGELOG.md` 从 v0.1.0 开始记录, 当前最新 v0.6.15
- `rules/v2/` 包含 turtle_pr / turtle_cash_quality / turtle_screener / turtle_qrv 四份规则
- `.env.example` 已脱敏 (2026-06-17)，v0.6.15 补全 TAVILY_API_KEY/CORS_ORIGINS/DEBUG 等 5 项

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
- `.codebuddy/rules.md` — 9 条强制规则，每次会话自动注入 (2026-06-18)
  1. 工作流：先文档后代码，闭环更新项目文件
  2. 配置：.env 最高权威
  3. 数据：Tushare 字段名一字不改，输出用中文名+股票代码
  4. 同步：公式改动=四件套（代码+规则YAML+coordinator.md+测试）
  5. 门控：硬门禁LLM，必须确定性计算
  6. 缓存：新字段=全量重拉
  7. 测试：pytest全绿才算完成，两层测试（SPEC合规+单元）
  8. 环境：PowerShell不重定向
  9. LLM输出：不虚不飘，数字说话（必含量化数据，禁止模糊定性词）

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
