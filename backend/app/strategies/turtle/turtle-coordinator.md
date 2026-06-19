# 龟龟策略 Coordinator — 流程定义

> 规则版本: v2 | 更新: 2026-06-18 (v0.5.3)

---

## 概述

龟龟策略是一条类红利股策略。核心思路：**在现金质量有保证的前提下，通过穿透回报率筛选高回报标的**。

本文档是龟龟策略的流程说明书，给 LLM Agent 和人类开发者共同阅读。
Python 执行器 `coordinator.py` 负责实际编排，本文档定义各 Step 的输入/输出/判定标准。

---

## v0.3.0 重大变更

| 变更 | 旧 (v0.2.x) | 新 (v0.3.0) |
|------|-------------|-------------|
| CQ门 类型 | 硬门（淘汰） | **软门（标记不淘汰）** |
| PR门 类型 | 硬门（淘汰） | **软门（标记不淘汰）** |
| 基本面门 | Step 8 单独执行 | 并入 QRV Agent Q维度 |
| 估值门 | Step 9 单独执行 | 并入 QRV Agent V维度 |
| 分析Agent | 独立两个 LLM 调用 | **QRV Agent 单次调用** |
| WebSearch | 预留接口 | **5次 Tavily 搜索** |
| 数据输入 | 分散多个文件 | **统一 qrv_input.yaml** |

---

## 流程图

```
[定时任务触发]
     │
     ▼
┌─────────────────────────────────────────────────────┐
│  Step 1: 选股器 (Screener)                           │
│  全A股 → 11条件筛选 → 候选池 (~80-150只)              │
│  输出: candidate_pool.yaml                           │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 2: 数据拉取 (Data Fetch)                       │
│  候选池 → Tushare拉取全量财务数据 → 本地缓存           │
│  输出: stock_cache/{ts_code}/raw_data.yaml            │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 3: 确定性计算 (Deterministic Compute)           │
│  raw_data → 计算现金质量/PR → computed.yaml           │
│  输出: stock_cache/{ts_code}/computed.yaml            │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 4: 现金质量门 (CQ Gate) [软门]                  │
│  5子维度判定 → 标记通过/未通过（不淘汰）               │
│  输出: gate_results.cash_quality                     │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 5: 穿透回报率门 (PR Gate) [软门]                │
│  PR计算 → 标记通过/未通过（不淘汰）                   │
│  输出: 股池（全部CQ+PR计算完成的股票，按PR降序）       │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
         [股池列表更新到数据库]
               │
               ▼
      [用户点击单股触发按需分析]
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 6: 统一数据包构建 (QRV Input Builder)            │
│  整合 raw_data + computed + screener + gate_results   │
│  → qrv_input.yaml                                    │
│  输出: 完整统一数据包（供LLM消费）                      │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 7: WebSearch Agent (5次Tavily搜索)              │
│  Q(商模+护城河) + R1(外部环境) + R2(管理层+人才)      │
│  + R3(控股结构) + V(估值概述)                          │
│  输出: websearch.yaml（含置信度）                      │
│  → 追加到 qrv_input.yaml 的 websearch_results 章节    │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 7.5: WebSearch预提取 (v0.5.0新增)              │
│  websearch.yaml → WebSearchExtractor规则引擎           │
│  → 预提取: 收入结构/市占率/管理层事实/人才/政策         │
│  输出: structured_facts (注入QRV Agent数据包)          │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│  Step 8: QRV Agent v3 (取代原Step 8+9)                │
│  读取 qrv_input.yaml → DataSummarizer v2预处理         │
│  → 单次LLM调用 (10维度分析)                            │
│  输出: qrv_analysis.md + qrv_analysis.json            │
│  含 data_sufficiency 数据充分性评估                    │
└─────────────────────────────────────────────────────┘
```

---

## Step 1: 选股器

### 输入
- 全A股列表（Tushare `stock_basic`）

### 10个筛选条件 (v2026-06-15 收紧版)

| # | 条件 | 参数 | 类型 |
|---|------|------|------|
| 1 | 排除ST/退市股 | name不含ST/退 | 排除 |
| 2 | 排除强周期行业 | 行业不在[钢铁,煤炭,航运,有色,化工,造纸] | 排除 |
| 3 | 上市年限 | 上市 > 8年 | 硬性 |
| 4 | 市值 | 总市值 > 200亿 | 硬性 |
| 5 | ROE | ROE > 12% | 硬性 |
| 6 | PE | 5 < PE < 25 | 硬性 |
| 7 | 股息率 | 股息率 > 2.5% | 硬性 |
| 8 | 毛利率 | 毛利率 > 25% | 硬性 |
| 9 | 负债率 | 资产负债率 < 60% | 硬性 |
| 10 | PB | PB > 0 (隐含，排除负资产) | 硬性 |

> 已删除: 原条件10 "经营CF/净利润 > 50%" — Tushare `ocf_to_or` 字段含义错误(OCF/Revenue ≠ OCF/NetProfit)。该检查由 CQ 维度1（经营CF/净利润 近3年均值 > 0.8）精确实现，不需要重复。

### 输出
- `candidate_pool.yaml`: 候选池列表，含 ts_code, name, industry, 各指标值
- 预计规模: 80-150只

### 校验
- Python 脚本检查: 候选池非空，各条件过滤数量日志可查
- 如候选池 < 50 只或 > 200 只，记录 WARNING 但继续

---

## Step 2: 数据拉取

### 输入
- Step 1 输出的候选池

### 拉取内容
对每只候选股从 Tushare 拉取：
1. **财务三表** (近10年): `income`, `balance_sheet`, `cashflow`
2. **分红数据**: `dividend`
3. **回购数据**: `repurchase`
4. **行情数据**: `daily` (近5年)
5. **基本信息**: `stock_basic`, `namechange`

### 输出
- `stock_cache/{ts_code}/raw_data.yaml`
  - 包含以上所有原始数据（**v0.5.3: 全部金额归一化为亿元，见 `docs/TUSHARE_UNITS.md`**）
  - 结构见 `data/templates/raw_data_schema.yaml`

### 容错
- 单只拉取失败：记录 error log，跳过，继续下一只
- 单只数据不完整：标记 `data_completeness: partial`，记录缺失字段
- 整体成功率 < 90%：终止，发送告警

---

## Step 3: 确定性计算

### 输入
- `stock_cache/{ts_code}/raw_data.yaml`

### 计算项

#### 现金质量5子维度
1. **经营CF/净利润比** (近3年均值) — `avg(opCF_netProfit_ratio, 3y) > 0.8`
2. **FCF正年数** (近5年) — `count(FCF > 0, 5y) >= 4`
3. **应收/营收比** (近3年均值) — `avg(receivables_revenue_ratio, 3y) < 0.3`
4. **存货/营收稳定性** — `CV(inventory_revenue_ratio, 5y) < 0.5`
5. **经营CF波动率** — `CV(operating_cf, 5y) < 0.5`

#### 穿透回报率
- 公式详见 [Step 5: 穿透回报率门 v2](#step-5-穿透回报率门-软门-v2)
- 核心：PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%
- 可支配现金 = 经营CF − CAPEX − 并购子公司 − max(0, 长投净增) − 财务费用（5年逐期）

### 输出
- `stock_cache/{ts_code}/computed.yaml`
  - 结构见 `data/templates/computed_schema.yaml`

---

## Step 4: 现金质量门 [软门] <sup>v0.3.0</sup>

### 判定标准
5子维度判定通过/未通过。**不淘汰，仅标记**。

| 维度 | 通过条件 |
|------|---------|
| opCF/净利润 | > 0.8 |
| FCF正年数 | ≥ 4/5 |
| 应收/营收 | < 0.3 |
| 存货/营收CV | < 0.5 |
| 经营CF CV | < 0.5 |

### 输出
- `gate_results` 中 `cash_quality: {passed: bool, details: {...}}`
- 未通过的标记原因，**继续后续流程**

### 变更历史
- v0.2.x: 硬门，不通过即淘汰
- **v0.3.0**: 改为软门，标记不淘汰，交 QRV Agent 综合评价

---

## Step 5: 穿透回报率门 [软门] <sup>v0.3.0</sup> v2

### 公式

**可支配现金（5年逐期）:**
```
可支配现金_i = n_cashflow_act_i                      # 经营CF净额
             − c_pay_acq_const_fiolta_i             # 购建固定资产(CAPEX)
             − n_disp_subs_oth_biz_i                # 并购子公司
             − max(0, lt_eqt_invest_年末_i − lt_eqt_invest_年初_i)  # 参股净增额
             − fin_exp_i                            # 财务费用(利润表)

可支配现金_avg = mean(可支配现金₁ ... ₅)
可支配现金_CV  = std / |avg|          # 标记: CV ≥ 0.5 的风险
```

**分配比率:**
```
分配比率 = min(5年分红总额 / 5年可支配现金总额, 100%)
```

**PR:**
```
PR = (可支配现金_avg × 分配比率 + 近5年年均回购注销) / 总市值 × 100%
# v0.5.3: 全部金额已归一化为亿元，分母分子单位一致，直接计算无需换算
```

### 判定标准（v0.3.0 软门）
- PR < 无风险利率 + 1.0% → 标记未通过，**不淘汰**
- 可支配现金 CV ≥ 0.5 → 标记不稳定风险
- 数据不足5年 → 标记数据风险

### 字段来源
| 字段 | Tushare 表 | 说明 |
|------|-----------|------|
| n_cashflow_act | cashflow | 经营活动现金流量净额 |
| c_pay_acq_const_fiolta | cashflow | 购建固定资产、无形资产和其他长期资产支付的现金 |
| n_disp_subs_oth_biz | cashflow | 取得子公司及其他营业单位支付的现金净额 |
| lt_eqt_invest | balancesheet | 长期股权投资（需2年算增量） |
| fin_exp | income | 财务费用 |

### 输出
- 股池列表，按 PR 降序（含 CQ/PR 标记）
- 写入数据库 `stock_pool` 表

### 变更历史
- v0.2.x: 硬门，不通过即淘汰
- **v0.3.0**: 改为软门，标记不淘汰，交 QRV Agent 综合评价

---

## Step 6-8: 按需分析流程 <sup>v0.5.0 更新</sup>

> 以下 Steps 在用户点击单股时触发，非定时任务。

### Step 6: 统一数据包构建 (QRV Input Builder)

整合所有已有数据源为单一 `qrv_input.yaml`：

| 章节 | 数据源 |
|------|--------|
| company_profile | raw_data.basic_info |
| financial_data | raw_data.annual_financials |
| cq_results | computed.cash_quality |
| pr_results | computed.penetration_return |
| dividend_repurchase | raw_data.dividend_history + repurchase_history |
| gate_summary | screener + CQ + PR 汇总判定 |
| websearch_results | 初始为空，Step 7 后填充 |

- 输出: `stock_cache/{ts_code}/qrv_input.yaml`

### Step 7: WebSearch Agent <sup>v0.5.0: R2新增人才结构搜索</sup>

- **工具**: Tavily API
- **搜索模块**: 5次搜索覆盖 Q/R/V 三维度
  1. `q_websearch` — 商业模式 + 护城河 + 收入结构
  2. `r1_websearch` — 外部环境与宏观风险
  3. `r2_websearch` — 管理层 + 公司治理 + **人才结构** (新增)
  4. `r3_websearch` — 控股结构与关联交易
  5. `v_websearch` — 估值概述
- **置信度标注**: HIGH/MEDIUM/LOW/NONE
- **输出**: `websearch.yaml` → 追加到 `qrv_input.yaml` 的 websearch_results 章节

### Step 7.5: WebSearch 预提取 <sup>v0.5.0 新增</sup>

- **工具**: `websearch_extractor.py` — 规则引擎 (不调用LLM, 零成本零延迟)
- **功能**: 从 websearch snippets 预提取结构化事实
  1. revenue_segments — 各业务线名称+金额+增速
  2. market_share — 市占率+排名+竞品
  3. management_facts — 管理层变动/激励/减持/负面
  4. industry_data — 行业规模/增速/渗透率
  5. talent_structure — 员工数/研发人员/人均创收
  6. national_policy — 十四五/国产替代/信创等政策引用
  7. supply_chain — 供应商/客户集中度
- **输出**: `extracted_facts` 注入 QRV Agent 数据包 `extracted_facts` 块

### Step 8: QRV Agent v3 (取代原 Step 8+9) <sup>v0.5.0</sup>

- **v0.5.0 升级**: DataSummarizer v2 + WebSearchExtractor + industry_profiles
- **角色**: 资深CFA持证人，15年A股价值投资经验
- **输入**: `qrv_input.yaml` → **DataSummarizer v2 预处理** (A1 20+字段 + A7生意属性 + data_sufficiency) + WebSearchExtractor预提取 + 完整 websearch + 原始财务表
- **分析框架**: Q(质量) + R(韧性) + V(估值) 三维度 10模块，每模块**强制输出量化表格**
  - Q1: 生意本质+商业模式 → 生意属性表 + 收入结构表 + 盈利质量趋势表
  - Q2: 护城河+可攻破性 → 护城河指标表 + 外来者威胁评估
  - Q3: 增长引擎 → 增长驱动拆分 + 第二曲线 + CAPEX模式
  - R1: 外部环境+国家战略 → 风险清单表 + 行业周期 + 国家规划
  - R2: 管理层+人才结构 → 画像表 + 分红回购表 + 人才结构表
  - R3: 控股结构 → 股权结构表 + 关联交易
  - V1: 价值陷阱筛查 → CQ 5维度表 + 资产负债快照
  - V2: 历史分位 → 估值快照 + 历史分位 + 同行对比
  - V3: 压力测试 → PR完整计算表 + 三情景预估
- **调用方式**: 单次 LLM 调用（DeepSeek, max_tokens=32768）
- **输出**: 定量+定性结论，大量 Markdown 表格
  - `qrv_analysis.md` — Markdown 完整报告（含所有强制表格）
  - `qrv_analysis.json` — 结构化数据
- **输出铁律**: 无数字不结论、无来源不引用、表格优于段落、数据缺失就声明

---

## Coordinator 状态机

```
IDLE → SCREENING → FETCHING → COMPUTING → GATING → READY
                                                      │
                                              [用户点击单股]
                                                      │
                                              ANALYZING → DONE
```

- `IDLE`: 等待触发
- `SCREENING`: Step 1 执行中
- `FETCHING`: Step 2 执行中
- `COMPUTING`: Step 3 执行中
- `GATING`: Step 4-5 执行中
- `READY`: 股池可用
- `ANALYZING`: Step 6-8 执行中（单股）
- `DONE`: 分析完成
- `ERROR`: 任一步骤出错

### 错误处理
- 确定性计算步骤出错 → 标记 ERROR，记录 trace_id，发送告警
- LLM 调用出错 → 重试 3 次，每次间隔 5s，仍失败则标记 ERROR
- 数据拉取部分失败 → 继续，记录失败列表
