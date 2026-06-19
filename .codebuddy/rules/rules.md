---
enabled: true
alwaysApply: true
---

# AI Agent 强制规则

> 每次会话自动注入。违反任一条 = 不合格。

---

## 1. 工作流：先文档，后代码，闭环管理

**必须按顺序**：

```
1. 理解 → 读 docs/CONTEXT.md + rules/v{N}/*.yaml + turtle-coordinator.md
2. 计划 → 列出改动范围（哪些文件）→ 向用户确认
3. 文档 → 先更新 CONTEXT.md / coordinator.md / rules/yaml
4. 代码 → 再改 Python 代码
5. 测试 → python -m pytest tests/ 全部通过
6. 闭环 → 更新项目文档：
   - .codebuddy/memory/YYYY-MM-DD.md（每日日志）
   - CHANGELOG.md（版本变更记录）
   - 版本号（pyproject.toml / 项目文件）
7. 有 Issue → 先写 Issue 再写代码，修复后关 Issue
```

**禁止**：
- ❌ 跳过确认直接改代码
- ❌ 先改代码后补文档（先污染后治理）
- ❌ 测试没跑完说"完成"
- ❌ 破坏性改动不记录 memory / 不更新版本号

---

## 2. 配置：`.env` 是最高权威

| | `.env` | `config.py` |
|---|--------|-------------|
| 优先级 | **最高**，覆盖默认值 | 第二，被 `.env` 覆盖 |
| 存什么 | 密钥 + 常调参数（URL/KEY/THRESHOLD） | 一切参数 + 默认值 |
| 安全 | 不入版本控制 | 入版本控制 |

**规则**：
1. 改任何阈值/参数前 → **第一步：读 `.env`**
2. `.env` 有 → 改 `.env`
3. `.env` 无 → 改 `config.py` 默认值 + 同步加到 `.env`
4. 新增可调参数 → `config.py` 默认值 + `.env` 当前值，两处同步

---

## 3. 数据：Tushare 字段名一字不改，输出用中文

### 代码层
- `data_fetcher.py` 中 `row.get()` 的 key → 必须和 Tushare API 文档**一字不差**
- `raw_data.yaml` 中 → 保留 Tushare 原始字段名
- Python 变量可简化为英文含义名，但**必须注释标注 Tushare 原始字段名**

**反例**：
- ❌ `row.get("c_pay_for_tan_il")` — 此字段不存在，正确是 `c_pay_acq_const_fiolta`
- ❌ `raw_data["interest_expense"]` — 原名是 `finan_exp`（财务费用，范围更广）

### 输出层
- 向用户展示股池时：**股票中文名 + 股票代码**，如「海澜之家 600398.SH」
- 不单独显示 Tushare 字段名（如只显示 `n_cashflow_act`）
- 字段名 → 中文含义的对照表存于 `docs/TUSHARE_FIELDS.md`

---

## 4. 同步：公式改动 = 四件套

改任何计算公式 → 必须**同时**改动：

| 文件 | 性质 |
|------|------|
| ① 计算模块 Python 代码 | 实际执行 |
| ② `rules/v{N}/*.yaml` | 规则权威定义 |
| ③ `turtle-coordinator.md` | SPEC 流程文档 |
| ④ `tests/` | 回归测试 |

**少一个 = 不完整 = 回归 Bug。**

---

## 5. 门控：硬门禁 LLM，必须是确定性计算

- **硬门**（screener / CQ / PR）：不通过即淘汰，不走后续流程
- **硬门内禁止引入 LLM 不确定性参数**（如"管理层看起来靠谱吗"、"舆论认为分红政策稳定"）
- 硬门只允许：数学公式、阈值比较、统计指标

---

## 6. 缓存：新字段 = 全量重拉

`data_fetcher.py` 新增/修改 Tushare 字段 → 所有 `raw_data.yaml` 缺少该字段 → **必须 `--full` 全量重拉**，不得用 `--compute-only` 在旧缓存上跑。

```
正确顺序：
1. 改 data_fetcher.py（加字段）
2. 跑 --full（全量重拉）
3. 跑 --compute-only（用新数据算）
```

---

## 7. 测试：不过不叫完成

- 改完代码必须 `pytest tests/` 全部通过
- 阈值变更 → 同步更新测试边界值
- 两层测试：
  - **SPEC 合规** (`test_spec_compliance.py`)：验证代码有没有按 coordinator.md 做
  - **单元测试** (`test_*.py`)：验证按 SPEC 做的代码算得对不对
- 公式改动 → SPEC 合规测试也要加对应校验

---

## 8. 环境：PowerShell 输出不重定向

Windows PowerShell 下 stdout 重定向会产生 CLIXML 乱码。

```
❌ python script.py > output.txt 2>&1
❌ python script.py | Out-File output.txt

✅ python script.py 2>&1 | Out-File -FilePath output.txt -Encoding utf8
✅ cmd /c "python script.py > output.txt 2>&1"
✅ 直接用 write_to_file 写脚本 → execute_command 看 stdout
```

---

## 9. LLM 输出：不虚不飘，数字说话

> QRV Agent 等 LLM 分析模块的输出质量铁律。

### 输入侧
- **禁止**将原始 YAML 截断后直接丢给 LLM
- **必须**先经 `data_summarizer.py` 预处理，提取关键数字表格，再传给 LLM
- CQ 门 / PR 穿透回报率 → 必须从 `computed.yaml` 回填完整 5 维度明细
- **v0.5.0**: DataSummarizer 新增 Layer 3 数据充分性评估（告诉 LLM 哪些维度可深度分析、哪些跳过）
- **v0.5.0**: 新增 `websearch_extractor.py` 从 websearch 预提取结构化事实（Layer 2）
- **v0.5.0**: 新增 `industry_profiles.yaml` 按行业动态适配额外指标

### 输出侧
- **无数字不结论**：每条判断必须附具体数字，禁止「较高」「偏低」「显著」「大幅」等模糊词
- **无来源不引用**：每个数字必须标注出处（websearch snippet 编号 N 或 data_summary 板块编号）
- **表格优于段落**：能用 Markdown 表格呈现的用表格，不要写成段落
- **数据缺失声明**：某维度缺少数据时写「数据缺失」，禁止编造

### 模块强制输出清单 (v0.5.0: 10维度)

| 模块 | 必含量化输出 |
|------|-------------|
| Q1 生意本质+商业模式 | 生意属性表(卖什么/怎么卖/上下游/收款方式/轻资产)、收入结构表、盈利质量5年趋势表(20+字段) |
| Q2 护城河+可攻破性 | 全球市占率、研发投入金额/占比、毛利率vs竞品、外来者威胁评估 |
| Q3 增长引擎 | 增长驱动拆分(量×价)、第二曲线进度、CAPEX/折旧比率 |
| R1 外部环境+国家战略 | 风险清单表(每行含影响量化)、行业周期位置、国家规划引用 |
| R2 管理层+人才结构 | 管理层画像表、分红回购历史表、人才结构表(研发人员占比/人均创收) |
| R3 控股结构 | 股权结构表、关联交易分析 |
| V1 价值陷阱 | CQ 5维度明细表(每维度具体值+门槛+判定)、资产负债快照 |
| V2 历史分位 | PE/PB/股息率当前值+历史分位(精确到百分位)+vs同行对比 |
| V3 压力测试 | PR 完整计算表、乐观/中性/悲观三情景、PR不通过原因分析 |

### 数据流
```
raw_data.yaml + computed.yaml + websearch.yaml
        ↓
  data_summarizer.py（预处理：提取关键数字表格）
        ↓
  structured_summary + 完整 websearch（不做截断）
        ↓
  LLM Prompt（含强制表格清单）
        ↓
  qrv_analysis.md + .json（含数字证据的报告）
```
