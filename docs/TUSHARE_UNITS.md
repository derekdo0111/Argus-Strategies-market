# Tushare 字段单位速查 & 归一化规则

> 版本: v0.5.3 | 更新: 2026-06-18

---

## 概述

Tushare 不同端点返回的数据单位不一致。本项目的处理策略：

**v0.5.3 起：入口归一化。所有金额在 `data_fetcher.py` 写入 raw_data.yaml 前统一归一化为亿元。**

下游模块不再需要猜测输入单位。

---

## Tushare 原始单位速查

| 端点 | 字段 | Tushare 单位 | 说明 |
|------|------|:------:|------|
| `income` | `revenue`, `net_profit`, `fin_exp`, `operate_profit`, `total_profit`, `sell_exp`, `admin_exp`, `oper_cost`, `rd_exp`, `int_income` | 元 | 利润表全部金额字段 |
| `balance_sheet` | `total_assets`, `total_liab`, `receivables`, `inventory`, `goodwill`, `fixed_assets`, `intan_assets`, `lt_eqt_invest`, `total_equity`, `total_cur_assets`, `total_cur_liab` | 元 | 资产负债表全部金额字段 |
| `cashflow` | `operating_cf`, `capex`, `acq_subsidiary`, `fcf`, `depr_amort`, `finan_exp`, `dividend_paid_cf` | 元 | 现金流量表全部金额字段 |
| `daily_basic` | `total_mv`, `circ_mv` | **万元** | |
| `daily_basic` | `total_share` | **万股** | |
| `daily_basic` | `dv_ratio` | **%（已是百分数）** | 如 3.0 = 3% |
| `daily_basic` | `pe`, `pb` | ratio | 无量纲 |
| `fina_indicator` | `roe`, `grossprofit_margin`, `netprofit_margin`, `debt_to_assets` | **%（已是百分数）** | 如 29.9 = 29.9% |
| `fina_indicator` | `current_ratio`, `quick_ratio` | ratio | 无量纲 |
| `dividend` | `cash_div` | **元/股** | |
| `dividend` → raw | `total_dividend = cash_div × total_share` | 万元 → **归一化后为亿元** | v0.5.3: 因为 total_share 归一化为亿股 |
| `repurchase` | `amount` | **万元** | |

---

## 归一化规则 (v0.5.3)

在 `data_fetcher.fetch_single_stock()` 末尾，写入 YAML 前执行：

| 来源 | 字段 | 换算 |
|------|------|:------:|
| income | 全部金额字段 | **÷ 1e8** (元 → 亿元) |
| balance_sheet | 全部金额字段 | **÷ 1e8** (元 → 亿元) |
| cashflow | 全部金额字段 | **÷ 1e8** (元 → 亿元) |
| daily_basic | `total_mv`, `circ_mv` | **÷ 1e4** (万元 → 亿元) ✓ 已做 |
| daily_basic | `total_share` | **÷ 1e4** (万股 → 亿股) |
| dividend | `total_dividend` | **÷ 1e4** (万元 → 亿元) |
| repurchase | `repurchase_amount` | **÷ 1e4** (万元 → 亿元) |
| 全部 % 值 | `roe`, `gross_margin`, `dv_ratio`, `debt_ratio` | **不动** |
| 全部 ratio | `pe`, `pb`, `current_ratio`, `quick_ratio` | **不动** |

---

## 下游模块影响

| 模块 | 影响 |
|------|------|
| `cash_quality.py` | **免疫** — 5 维度全比率计算，单位约分 |
| `penetration_return.py` | **简化** — 去掉 B=1e8 / td_yuan / dc_b / rp_b 换算变量 |
| `data_summarizer.py` | **修复** — 去掉 12 处错误的 ÷1e8 / ×100 |
| `screener.py` | **无影响** — 使用 L0 缓存的预换算数据 |

---

## 开发规范

1. 新增 Tushare 端点拉取 → 第一件事查本文档确认原始单位
2. raw_data.yaml 的金额字段 = **永远亿元**
3. raw_data.yaml 的百分比字段 = **永远百分数 (如 3.0 = 3%)**
4. 不确定单位 → 查 Tushare 官方文档，补入本文档
