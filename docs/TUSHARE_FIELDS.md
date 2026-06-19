# Tushare 全量字段 ↔ 中文含义 对照表

> 数据来源：Tushare 官方 API 文档 + `db_tushare.sql` (MySQL DDL)
> 
> AI Agent 输出股池时使用：**中文名 + 股票代码**（如「海澜之家 600398.SH」）
> 
> ⚠️ 标记 → 表示本项目已抓取该字段

---

## 一、stock_basic — 股票基本信息（14 字段）

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `symbol` | 股票代码 | |
| `name` | 股票名称 | → |
| `area` | 所在地域 | |
| `industry` | 所属行业 | → |
| `fullname` | 股票全称 | |
| `enname` | 英文全称 | |
| `market` | 市场类型（主板/中小板/创业板/科创板） | |
| `exchange` | 交易所代码（SSE/SZSE） | |
| `curr_type` | 交易货币 | |
| `list_status` | 上市状态（L上市 D退市 P暂停） | |
| `list_date` | 上市日期 | → |
| `delist_date` | 退市日期 | |
| `is_hs` | 沪深港通标的（N否 H沪 S深） | |

---

## 二、daily_basic — 每日指标（16 字段）

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | |
| `trade_date` | 交易日期 | |
| `close` | 当日收盘价 | |
| `turnover_rate` | 换手率（%） | |
| `turnover_rate_f` | 换手率（自由流通股） | |
| `volume_ratio` | 量比 | |
| `pe` | 市盈率（总市值/净利润） | |
| `pe_ttm` | 市盈率 TTM | |
| `pb` | 市净率 | |
| `ps` | 市销率 | |
| `ps_ttm` | 市销率 TTM | |
| `total_share` | 总股本（万股） | → |
| `float_share` | 流通股本（万股） | |
| `free_share` | 自由流通股本（万股） | |
| `total_mv` | 总市值（万元） | → |
| `circ_mv` | 流通市值（万元） | |

---

## 三、income — 利润表（64 字段）

### 基本信息

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `ann_date` | 公告日期 | |
| `f_ann_date` | 实际公告日期 | |
| `end_date` | 报告期 | → |
| `report_type` | 报告类型 | |
| `comp_type` | 公司类型（1一般工商业 2银行 3保险 4证券） | |

### 每股指标

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `basic_eps` | 基本每股收益 | → |
| `diluted_eps` | 稀释每股收益 | |

### 收入

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `total_revenue` | 营业总收入 | |
| `revenue` | 营业收入 | → |
| `int_income` | 利息收入 | |
| `prem_earned` | 已赚保费 | |
| `comm_income` | 手续费及佣金收入 | |
| `n_commis_income` | 手续费及佣金净收入 | |
| `n_oth_income` | 其他经营净收益 | |
| `n_oth_b_income` | 其他业务净收益 | |
| `prem_income` | 保险业务收入 | |
| `out_prem` | 分出保费（减） | |
| `une_prem_reser` | 提取未到期责任准备金 | |
| `reins_income` | 分保费收入 | |
| `n_sec_tb_income` | 代理买卖证券业务净收入 | |
| `n_sec_uw_income` | 证券承销业务净收入 | |
| `n_asset_mg_income` | 受托客户资产管理业务净收入 | |
| `oth_b_income` | 其他业务收入 | |
| `fv_value_chg_gain` | 公允价值变动净收益 | |
| `invest_income` | 投资净收益 | |
| `ass_invest_income` | 对联营企业和合营企业的投资收益 | |
| `forex_gain` | 汇兑净收益 | |

### 成本

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `total_cogs` | 营业总成本 | |
| `oper_cost` | 营业成本 | |
| `int_exp` | 利息支出 | |
| `comm_exp` | 手续费及佣金支出 | |
| `biz_tax_surchg` | 营业税金及附加 | |
| `sell_exp` | 销售费用 | |
| `admin_exp` | 管理费用 | |
| `fin_exp` | 财务费用 | |
| `assets_impair_loss` | 资产减值损失 | |
| `prem_refund` | 退保金 | |
| `compens_payout` | 赔付总支出 | |
| `reser_insur_liab` | 提取保险责任准备金 | |
| `div_payt` | 保户红利支出 | |
| `reins_exp` | 分保费用 | |
| `oper_exp` | 营业支出 | |
| `compens_payout_refu` | 摊回赔付支出（减） | |
| `insur_reser_refu` | 摊回保险责任准备金（减） | |
| `reins_cost_refund` | 摊回分保费用（减） | |
| `other_bus_cost` | 其他业务成本 | |

### 利润

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `operate_profit` | 营业利润 | → |
| `non_oper_income` | 营业外收入 | |
| `non_oper_exp` | 营业外支出 | |
| `nca_disploss` | 非流动资产处置净损失 | |
| `total_profit` | 利润总额 | |
| `income_tax` | 所得税费用 | |
| `n_income` | 净利润（含少数股东损益） | → fallback |
| `n_income_attr_p` | 净利润（不含少数股东损益） | → |
| `minority_gain` | 少数股东损益 | |
| `oth_compr_income` | 其他综合收益 | |
| `t_compr_income` | 综合收益总额 | |
| `compr_inc_attr_p` | 归母综合收益 | |
| `compr_inc_attr_m_s` | 少数股东综合收益 | |
| `ebit` | 息税前利润 | |
| `ebitda` | 息税折旧摊销前利润 | |
| `insurance_exp` | 保险业务支出 | |
| `undist_profit` | 年初未分配利润 | |
| `distable_profit` | 可分配利润 | |
| `update_flag` | 更新标识（0未修改 1更正过） | |

---

## 四、balancesheet — 资产负债表（~140 字段）

### 基本信息

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `ann_date` | 公告日期 | |
| `f_ann_date` | 实际公告日期 | |
| `end_date` | 报告期 | → |
| `report_type` | 报告类型 | |
| `comp_type` | 公司类型 | |
| `total_share` | 期末总股本 | |
| `cap_rese` | 资本公积金 | |
| `undi_porfit` | 未分配利润 | |
| `surplus_rese` | 盈余公积金 | |
| `special_rese` | 专项储备 | |

### 流动资产

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `money_cap` | 货币资金 | |
| `trad_asset` | 交易性金融资产 | |
| `notes_receiv` | 应收票据 | |
| `accounts_receiv` | 应收账款 | → |
| `oth_receiv` | 其他应收款 | |
| `prepayment` | 预付款项 | |
| `div_receiv` | 应收股利 | |
| `int_receiv` | 应收利息 | |
| `inventories` | 存货 | → |
| `amor_exp` | 长期待摊费用 | |
| `nca_within_1y` | 一年内到期的非流动资产 | |
| `sett_rsrv` | 结算备付金 | |
| `loanto_oth_bank_fi` | 拆出资金 | |
| `premium_receiv` | 应收保费 | |
| `reinsur_receiv` | 应收分保账款 | |
| `reinsur_res_receiv` | 应收分保合同准备金 | |
| `pur_resale_fa` | 买入返售金融资产 | |
| `oth_cur_assets` | 其他流动资产 | |
| `total_cur_assets` | 流动资产合计 | |

### 非流动资产

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `fa_avail_for_sale` | 可供出售金融资产 | |
| `htm_invest` | 持有至到期投资 | |
| `lt_eqt_invest` | 长期股权投资 | ⚠️ 待新增 |
| `invest_real_estate` | 投资性房地产 | |
| `time_deposits` | 定期存款 | |
| `oth_assets` | 其他资产 | |
| `lt_rec` | 长期应收款 | |
| `fix_assets` | 固定资产 | → |
| `cip` | 在建工程 | |
| `const_materials` | 工程物资 | |
| `fixed_assets_disp` | 固定资产清理 | |
| `produc_bio_assets` | 生产性生物资产 | |
| `oil_and_gas_assets` | 油气资产 | |
| `intan_assets` | 无形资产 | → |
| `r_and_d` | 研发支出 | |
| `goodwill` | 商誉 | → |
| `lt_amor_exp` | 长期待摊费用 | |
| `defer_tax_assets` | 递延所得税资产 | |
| `decr_in_disbur` | 发放贷款及垫款 | |
| `oth_nca` | 其他非流动资产 | |
| `total_nca` | 非流动资产合计 | |

### 金融业专用资产

| 字段名 | 中文含义 |
|--------|----------|
| `cash_reser_cb` | 现金及存放中央银行款项 |
| `depos_in_oth_bfi` | 存放同业和其它金融机构款项 |
| `prec_metals` | 贵金属 |
| `deriv_assets` | 衍生金融资产 |
| `rr_reins_une_prem` | 应收分保未到期责任准备金 |
| `rr_reins_outstd_cla` | 应收分保未决赔款准备金 |
| `rr_reins_lins_liab` | 应收分保寿险责任准备金 |
| `rr_reins_lthins_liab` | 应收分保长期健康险责任准备金 |
| `refund_depos` | 存出保证金 |
| `ph_pledge_loans` | 保户质押贷款 |
| `refund_cap_depos` | 存出资本保证金 |
| `indep_acct_assets` | 独立账户资产 |
| `client_depos` | 客户资金存款 |
| `client_prov` | 客户备付金 |
| `transac_seat_fee` | 交易席位费 |
| `invest_as_receiv` | 应收款项类投资 |

### 资产总计

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `total_assets` | 资产总计 | → |

### 流动负债

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `st_borr` | 短期借款 | |
| `cb_borr` | 向中央银行借款 | |
| `depos_ib_deposits` | 吸收存款及同业存放 | |
| `loan_oth_bank` | 拆入资金 | |
| `trading_fl` | 交易性金融负债 | |
| `notes_payable` | 应付票据 | |
| `acct_payable` | 应付账款 | |
| `adv_receipts` | 预收款项 | |
| `sold_for_repur_fa` | 卖出回购金融资产款 | |
| `comm_payable` | 应付手续费及佣金 | |
| `payroll_payable` | 应付职工薪酬 | |
| `taxes_payable` | 应交税费 | |
| `int_payable` | 应付利息 | |
| `div_payable` | 应付股利 | |
| `oth_payable` | 其他应付款 | |
| `acc_exp` | 预提费用 | |
| `deferred_inc` | 递延收益 | |
| `st_bonds_payable` | 应付短期债券 | |
| `payable_to_reinsurer` | 应付分保账款 | |
| `rsrv_insur_cont` | 保险合同准备金 | |
| `acting_trading_sec` | 代理买卖证券款 | |
| `acting_uw_sec` | 代理承销证券款 | |
| `non_cur_liab_due_1y` | 一年内到期的非流动负债 | |
| `oth_cur_liab` | 其他流动负债 | |
| `total_cur_liab` | 流动负债合计 | |

### 非流动负债

| 字段名 | 中文含义 |
|--------|----------|
| `lt_borr` | 长期借款 |
| `bond_payable` | 应付债券 |
| `lt_payable` | 长期应付款 |
| `specific_payables` | 专项应付款 |
| `estimated_liab` | 预计负债 |
| `defer_tax_liab` | 递延所得税负债 |
| `defer_inc_non_cur_liab` | 递延收益-非流动负债 |
| `oth_ncl` | 其他非流动负债 |
| `total_ncl` | 非流动负债合计 |

### 保险/金融专用负债

| 字段名 | 中文含义 |
|--------|----------|
| `depos_oth_bfi` | 同业和其它金融机构存放款项 |
| `deriv_liab` | 衍生金融负债 |
| `depos` | 吸收存款 |
| `agency_bus_liab` | 代理业务负债 |
| `oth_liab` | 其他负债 |
| `prem_receiv_adva` | 预收保费 |
| `depos_received` | 存入保证金 |
| `ph_invest` | 保户储金及投资款 |
| `reser_une_prem` | 未到期责任准备金 |
| `reser_outstd_claims` | 未决赔款准备金 |
| `reser_lins_liab` | 寿险责任准备金 |
| `reser_lthins_liab` | 长期健康险责任准备金 |
| `indept_acc_liab` | 独立账户负债 |
| `pledge_borr` | 质押借款 |
| `indem_payable` | 应付赔付款 |
| `policy_div_payable` | 应付保单红利 |

### 负债合计

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `total_liab` | 负债合计 | → |

### 所有者权益

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `treasury_share` | 库存股 | |
| `ordin_risk_reser` | 一般风险准备 | |
| `forex_differ` | 外币报表折算差额 | |
| `invest_loss_unconf` | 未确认的投资损失 | |
| `minority_int` | 少数股东权益 | |
| `total_hldr_eqy_exc_min_int` | 归母股东权益（不含少数） | → |
| `total_hldr_eqy_inc_min_int` | 归母股东权益（含少数） | → fallback |
| `total_liab_hldr_eqy` | 负债及股东权益总计 | |
| `lt_payroll_payable` | 长期应付职工薪酬 | |
| `oth_comp_income` | 其他综合收益 | |
| `oth_eqt_tools` | 其他权益工具 | |
| `oth_eqt_tools_p_shr` | 其他权益工具（优先股） | |
| `lending_funds` | 融出资金 | |
| `acc_receivable` | 应收款项 | |
| `st_fin_payable` | 应付短期融资款 | |
| `payables` | 应付款项 | |
| `hfs_assets` | 持有待售资产 | |
| `hfs_sales` | 持有待售负债 | |
| `update_flag` | 更新标识 | |

---

## 五、cashflow — 现金流量表（93 字段）

### 基本信息

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `ann_date` | 公告日期 | |
| `f_ann_date` | 实际公告日期 | |
| `end_date` | 报告期 | → |
| `report_type` | 报告类型 | |
| `comp_type` | 公司类型 | |

### 经营活动

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `c_fr_sale_sg` | 销售商品、提供劳务收到的现金 | |
| `recp_tax_rends` | 收到的税费返还 | |
| `n_depos_incr_fi` | 客户存款和同业存放款项净增加额 | |
| `n_incr_loans_cb` | 向中央银行借款净增加额 | |
| `n_inc_borr_oth_fi` | 向其他金融机构拆入资金净增加额 | |
| `prem_fr_orig_contr` | 收到原保险合同保费取得的现金 | |
| `n_incr_insured_dep` | 保户储金净增加额 | |
| `n_reinsur_prem` | 收到再保业务现金净额 | |
| `n_incr_disp_tfa` | 处置交易性金融资产净增加额 | |
| `ifc_cash_incr` | 收取利息和手续费净增加额 | |
| `n_incr_disp_faas` | 处置可供出售金融资产净增加额 | |
| `n_incr_loans_oth_bank` | 拆入资金净增加额 | |
| `n_cap_incr_repur` | 回购业务资金净增加额 | |
| `c_fr_oth_operate_a` | 收到其他与经营活动有关的现金 | |
| `c_inf_fr_operate_a` | 经营活动现金流入小计 | |
| `c_paid_goods_s` | 购买商品、接受劳务支付的现金 | |
| `c_paid_to_for_empl` | 支付给职工以及为职工支付的现金 | |
| `c_paid_for_taxes` | 支付的各项税费 | |
| `n_incr_clt_loan_adv` | 客户贷款及垫款净增加额 | |
| `n_incr_dep_cbob` | 存放央行和同业款项净增加额 | |
| `c_pay_claims_orig_inco` | 支付原保险合同赔付款项的现金 | |
| `pay_handling_chrg` | 支付手续费的现金 | |
| `pay_comm_insur_plcy` | 支付保单红利的现金 | |
| `oth_cash_pay_oper_act` | 支付其他与经营活动有关的现金 | |
| `st_cash_out_act` | 经营活动现金流出小计 | |
| `n_cashflow_act` | 经营活动产生的现金流量净额 | → |
| `net_profit` | 净利润（间接法起点） | |

### 投资活动

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `oth_recp_ral_inv_act` | 收到其他与投资活动有关的现金 | |
| `c_disp_withdrwl_invest` | 收回投资收到的现金 | |
| `c_recp_return_invest` | 取得投资收益收到的现金 | |
| `n_recp_disp_fiolta` | 处置固定资产/无形资产/长期资产收回的现金净额 | |
| `n_recp_disp_sobu` | 处置子公司及其他营业单位收到的现金净额 | |
| `stot_inflows_inv_act` | 投资活动现金流入小计 | |
| `c_pay_acq_const_fiolta` | 购建固定资产/无形资产和其他长期资产支付的现金 | ⚠️ Bug：当前用了错误字段 |
| `c_paid_invest` | 投资支付的现金 | ⚠️ 待新增 |
| `n_disp_subs_oth_biz` | 取得子公司及其他营业单位支付的现金净额 | ⚠️ 待新增 |
| `oth_pay_ral_inv_act` | 支付其他与投资活动有关的现金 | |
| `n_incr_pledge_loan` | 质押贷款净增加额 | |
| `stot_out_inv_act` | 投资活动现金流出小计 | |
| `n_cashflow_inv_act` | 投资活动产生的现金流量净额 | → |

### 筹资活动

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `c_recp_borrow` | 取得借款收到的现金 | |
| `proc_issue_bonds` | 发行债券收到的现金 | |
| `oth_cash_recp_ral_fnc_act` | 收到其他与筹资活动有关的现金 | |
| `stot_cash_in_fnc_act` | 筹资活动现金流入小计 | |
| `c_prepay_amt_borr` | 偿还债务支付的现金 | |
| `c_pay_dist_dpcp_int_exp` | 分配股利/利润或偿付利息支付的现金 | |
| `incl_dvd_profit_paid_sc_ms` | 子公司支付给少数股东的股利/利润 | |
| `oth_cashpay_ral_fnc_act` | 支付其他与筹资活动有关的现金 | |
| `stot_cashout_fnc_act` | 筹资活动现金流出小计 | |
| `n_cash_flows_fnc_act` | 筹资活动产生的现金流量净额 | → |
| `c_recp_cap_contrib` | 吸收投资收到的现金 | |
| `incl_cash_rec_saims` | 子公司吸收少数股东投资收到的现金 | |

### 汇率及现金变动

| 字段名 | 中文含义 |
|--------|----------|
| `eff_fx_flu_cash` | 汇率变动对现金的影响 |
| `n_incr_cash_cash_equ` | 现金及现金等价物净增加额 |
| `c_cash_equ_beg_period` | 期初现金及现金等价物余额 |
| `c_cash_equ_end_period` | 期末现金及现金等价物余额 |

### 间接法调节

| 字段名 | 中文含义 |
|--------|----------|
| `uncon_invest_loss` | 未确认投资损失 |
| `prov_depr_assets` | 资产减值准备 |
| `depr_fa_coga_dpba` | 固定资产折旧/油气资产折耗/生产性生物资产折旧 | → 折旧子项 |
| `amort_intang_assets` | 无形资产摊销 | → 折旧子项 |
| `lt_amort_deferred_exp` | 长期待摊费用摊销 | → 折旧子项 |
| `decr_deferred_exp` | 待摊费用减少 | |
| `incr_acc_exp` | 预提费用增加 | |
| `loss_disp_fiolta` | 处置固定/无形资产和其他长期资产的损失 | |
| `loss_scr_fa` | 固定资产报废损失 | |
| `loss_fv_chg` | 公允价值变动损失 | |
| `invest_loss` | 投资损失 | |
| `decr_def_inc_tax_assets` | 递延所得税资产减少 | |
| `incr_def_inc_tax_liab` | 递延所得税负债增加 | |
| `decr_inventories` | 存货的减少 | |
| `decr_oper_payable` | 经营性应收项目的减少 | |
| `incr_oper_payable` | 经营性应付项目的增加 | |
| `others` | 其他 | |
| `im_net_cashflow_oper_act` | 经营活动现金流量净额(间接法) | |

### 补充资料

| 字段名 | 中文含义 |
|--------|----------|
| `conv_debt_into_cap` | 债务转为资本 |
| `conv_copbonds_due_within_1y` | 一年内到期的可转换公司债券 |
| `fa_fnc_leases` | 融资租入固定资产 |
| `end_bal_cash` | 现金的期末余额 |
| `beg_bal_cash` | 现金的期初余额 |
| `end_bal_cash_equ` | 现金等价物的期末余额 |
| `beg_bal_cash_equ` | 现金等价物的期初余额 |
| `im_n_incr_cash_equ` | 现金及现金等价物净增加额(间接法) |
| `update_flag` | 更新标识 | |

### 财务费用 & 自由现金流

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `finan_exp` | 财务费用 | → ⚠️ 误名 `interest_expense` |
| `free_cashflow` | 企业自由现金流 | → |
| `use_right_asset_dep` | 使用权资产折旧 | → 折旧子项 |

---

## 六、fina_indicator — 财务指标（167 字段）

### 基本信息

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `ann_date` | 公告日期 | |
| `end_date` | 报告期 | → |

### 每股指标

| 字段名 | 中文含义 |
|--------|----------|
| `eps` | 基本每股收益 |
| `dt_eps` | 稀释每股收益 |
| `total_revenue_ps` | 每股营业总收入 |
| `revenue_ps` | 每股营业收入 |
| `capital_rese_ps` | 每股资本公积 |
| `surplus_rese_ps` | 每股盈余公积 |
| `undist_profit_ps` | 每股未分配利润 |
| `bps` | 每股净资产 |
| `ocfps` | 每股经营活动现金流量净额 |
| `retainedps` | 每股留存收益 |
| `cfps` | 每股现金流量净额 |
| `ebit_ps` | 每股息税前利润 |
| `fcff_ps` | 每股企业自由现金流量 |
| `fcfe_ps` | 每股股东自由现金流量 |
| `diluted2_eps` | 期末摊薄每股收益 |

### 利润质量

| 字段名 | 中文含义 |
|--------|----------|
| `extra_item` | 非经常性损益 |
| `profit_dedt` | 扣除非经常性损益后的净利润 |
| `op_income` | 经营活动净收益 |
| `valuechange_income` | 价值变动净收益 |
| `interst_income` | 利息费用 |
| `daa` | 折旧与摊销 |
| `ebit` | 息税前利润 |
| `ebitda` | 息税折旧摊销前利润 |
| `fcff` | 企业自由现金流量 |
| `fcfe` | 股权自由现金流量 |

### 营运/资产结构

| 字段名 | 中文含义 |
|--------|----------|
| `current_exint` | 无息流动负债 |
| `noncurrent_exint` | 无息非流动负债 |
| `interestdebt` | 带息债务 |
| `netdebt` | 净债务 |
| `tangible_asset` | 有形资产 |
| `working_capital` | 营运资金 |
| `networking_capital` | 营运流动资本 |
| `invest_capital` | 全部投入资本 |
| `retained_earnings` | 留存收益 |
| `fixed_assets` | 固定资产合计 |
| `profit_prefin_exp` | 扣除财务费用前营业利润 |
| `non_op_profit` | 非营业利润 |

### 盈利能力

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `gross_margin` | 毛利 | |
| `grossprofit_margin` | 销售毛利率 | → |
| `netprofit_margin` | 销售净利率 | |
| `cogs_of_sales` | 销售成本率 | |
| `expense_of_sales` | 销售期间费用率 | |
| `roe` | 净资产收益率 | → |
| `roe_waa` | 加权平均净资产收益率 | |
| `roe_dt` | 净资产收益率(扣非) | |
| `roa` | 总资产报酬率 | |
| `npta` | 总资产净利润 | |
| `roic` | 投入资本回报率 | |
| `roe_yearly` | 年化净资产收益率 | |
| `roa2_yearly` | 年化总资产报酬率 | |
| `roa_yearly` | 年化总资产净利率 | |
| `roa_dp` | 总资产净利率(杜邦) | |
| `roe_avg` | 平均净资产收益率 | |
| `roic_yearly` | 年化投入资本回报率 | |

### 收益结构（/营业总收入）

| 字段名 | 中文含义 |
|--------|----------|
| `profit_to_gr` | 净利润/营业总收入 |
| `saleexp_to_gr` | 销售费用/营业总收入 |
| `adminexp_of_gr` | 管理费用/营业总收入 |
| `finaexp_of_gr` | 财务费用/营业总收入 |
| `impai_ttm` | 资产减值损失/营业总收入 |
| `gc_of_gr` | 营业总成本/营业总收入 |
| `op_of_gr` | 营业利润/营业总收入 |
| `ebit_of_gr` | 息税前利润/营业总收入 |

### 利润构成

| 字段名 | 中文含义 |
|--------|----------|
| `opincome_of_ebt` | 经营活动净收益/利润总额 |
| `investincome_of_ebt` | 价值变动净收益/利润总额 |
| `n_op_profit_of_ebt` | 营业外收支净额/利润总额 |
| `tax_to_ebt` | 所得税/利润总额 |
| `dtprofit_to_profit` | 扣非净利润/净利润 |
| `op_to_ebt` | 营业利润/利润总额 |
| `nop_to_ebt` | 非营业利润/利润总额 |
| `ocf_to_profit` | 经营活动现金流量净额/营业利润 |
| `profit_to_op` | 利润总额/营业收入 |

### 现金流量关系

| 字段名 | 中文含义 |
|--------|----------|
| `salescash_to_or` | 销售商品提供劳务收到的现金/营业收入 |
| `ocf_to_or` | 经营活动现金流量净额/营业收入 |
| `ocf_to_opincome` | 经营活动现金流量净额/经营活动净收益 |
| `capitalized_to_da` | 资本支出/折旧和摊销 |

### 偿债能力

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `current_ratio` | 流动比率 | → |
| `quick_ratio` | 速动比率 | → |
| `cash_ratio` | 保守速动比率 | |
| `debt_to_assets` | 资产负债率 | |
| `assets_to_eqt` | 权益乘数 | |
| `dp_assets_to_eqt` | 权益乘数(杜邦) | |
| `debt_to_eqt` | 产权比率 | |
| `eqt_to_debt` | 归母股东权益/负债合计 | |
| `eqt_to_interestdebt` | 归母股东权益/带息债务 | |
| `tangibleasset_to_debt` | 有形资产/负债合计 | |
| `tangasset_to_intdebt` | 有形资产/带息债务 | |
| `tangibleasset_to_netdebt` | 有形资产/净债务 | |
| `ocf_to_shortdebt` | 经营活动现金流量净额/流动负债 | |
| `ocf_to_debt` | 经营活动现金流量净额/负债合计 | |
| `ocf_to_interestdebt` | 经营活动现金流量净额/带息债务 | |
| `ocf_to_netdebt` | 经营活动现金流量净额/净债务 | |
| `ebit_to_interest` | 已获利息倍数 | |
| `longdebt_to_workingcapital` | 长期债务与营运资金比率 | |
| `ebitda_to_debt` | 息税折旧摊销前利润/负债合计 | |
| `cash_to_liqdebt` | 货币资金/流动负债 | |
| `cash_to_liqdebt_withinterest` | 货币资金/带息流动负债 | |
| `op_to_liqdebt` | 营业利润/流动负债 | |
| `op_to_debt` | 营业利润/负债合计 | |

### 资产结构

| 字段名 | 中文含义 |
|--------|----------|
| `ca_to_assets` | 流动资产/总资产 |
| `nca_to_assets` | 非流动资产/总资产 |
| `tbassets_to_totalassets` | 有形资产/总资产 |
| `int_to_talcap` | 带息债务/全部投入资本 |
| `eqt_to_talcapital` | 归母股东权益/全部投入资本 |
| `currentdebt_to_debt` | 流动负债/负债合计 |
| `longdeb_to_debt` | 非流动负债/负债合计 |

### 周转率

| 字段名 | 中文含义 |
|--------|----------|
| `invturn_days` | 存货周转天数 |
| `arturn_days` | 应收账款周转天数 |
| `inv_turn` | 存货周转率 |
| `ar_turn` | 应收账款周转率 |
| `ca_turn` | 流动资产周转率 |
| `fa_turn` | 固定资产周转率 |
| `assets_turn` | 总资产周转率 |
| `turn_days` | 营业周期 |
| `total_fa_trun` | 固定资产合计周转率 |

### 同比增长率

| 字段名 | 中文含义 |
|--------|----------|
| `basic_eps_yoy` | 基本每股收益同比增长率(%) |
| `dt_eps_yoy` | 稀释每股收益同比增长率(%) |
| `cfps_yoy` | 每股经营活动现金流量净额同比增长率(%) |
| `op_yoy` | 营业利润同比增长率(%) |
| `ebt_yoy` | 利润总额同比增长率(%) |
| `netprofit_yoy` | 归母净利润同比增长率(%) |
| `dt_netprofit_yoy` | 扣非归母净利润同比增长率(%) |
| `ocf_yoy` | 经营活动现金流量净额同比增长率(%) |
| `roe_yoy` | 净资产收益率同比增长率(%) |
| `bps_yoy` | 每股净资产相对年初增长率(%) |
| `assets_yoy` | 资产总计相对年初增长率(%) |
| `eqt_yoy` | 归母股东权益相对年初增长率(%) |
| `tr_yoy` | 营业总收入同比增长率(%) |
| `or_yoy` | 营业收入同比增长率(%) |
| `equity_yoy` | 净资产同比增长率 |
| `rd_exp` | 研发费用 |

### 单季度指标（q_前缀）

| 字段名 | 中文含义 |
|--------|----------|
| `q_opincome` | 经营活动单季度净收益 |
| `q_investincome` | 价值变动单季度净收益 |
| `q_dtprofit` | 扣非后单季度净利润 |
| `q_eps` | 每股收益(单季度) |
| `q_netprofit_margin` | 销售净利率(单季度) |
| `q_gsprofit_margin` | 销售毛利率(单季度) |
| `q_exp_to_sales` | 销售期间费用率(单季度) |
| `q_profit_to_gr` | 净利润/营业总收入(单季度) |
| `q_saleexp_to_gr` | 销售费用/营业总收入(单季度) |
| `q_adminexp_to_gr` | 管理费用/营业总收入(单季度) |
| `q_finaexp_to_gr` | 财务费用/营业总收入(单季度) |
| `q_impair_to_gr_ttm` | 资产减值损失/营业总收入(单季度) |
| `q_gc_to_gr` | 营业总成本/营业总收入(单季度) |
| `q_op_to_gr` | 营业利润/营业总收入(单季度) |
| `q_roe` | 净资产收益率(单季度) |
| `q_dt_roe` | 净资产单季度收益率(扣非) |
| `q_npta` | 总资产净利润(单季度) |
| `q_opincome_to_ebt` | 经营活动净收益/利润总额(单季度) |
| `q_investincome_to_ebt` | 价值变动净收益/利润总额(单季度) |
| `q_dtprofit_to_profit` | 扣非净利润/净利润(单季度) |
| `q_salescash_to_or` | 销售商品提供劳务收到的现金/营业收入(单季度) |
| `q_ocf_to_sales` | 经营活动现金流量净额/营业收入(单季度) |
| `q_ocf_to_or` | 经营活动现金流量净额/经营活动净收益(单季度) |

### 单季度同比/环比

| 字段名 | 中文含义 |
|--------|----------|
| `q_gr_yoy` | 营业总收入同比增长率(单季度)(%) |
| `q_gr_qoq` | 营业总收入环比增长率(单季度)(%) |
| `q_sales_yoy` | 营业收入同比增长率(单季度)(%) |
| `q_sales_qoq` | 营业收入环比增长率(单季度)(%) |
| `q_op_yoy` | 营业利润同比增长率(单季度)(%) |
| `q_op_qoq` | 营业利润环比增长率(单季度)(%) |
| `q_profit_yoy` | 净利润同比增长率(单季度)(%) |
| `q_profit_qoq` | 净利润环比增长率(单季度)(%) |
| `q_netprofit_yoy` | 归母净利润同比增长率(单季度)(%) |
| `q_netprofit_qoq` | 归母净利润环比增长率(单季度)(%) |

### 其他

| 字段名 | 中文含义 |
|--------|----------|
| `update_flag` | 更新标识 |

---

## 七、dividend — 分红送转（15 字段）

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `end_date` | 分红年度/报告期 | → |
| `ann_date` | 公告日期 | |
| `div_proc` | 实施进度（预案/实施/取消） | |
| `stk_div` | 每股送转（送转股比例） | |
| `cash_div` | 每股派息（税前，元） | → |
| `cash_div_tax` | 每股派息（税后，元） | |
| `record_date` | 股权登记日 | |
| `ex_date` | 除权除息日 | |
| `pay_date` | 派息日 | |
| `div_listdate` | 红股上市日 | |
| `imp_ann_date` | 实施公告日期 | |
| `base_share` | 基准股本（万股） | |
| `payout_ratio` | 分红率 | → (自算: DPS/EPS×100) |
| `stk_div_type` | 送转形式 | |

---

## 八、repurchase — 股票回购（15 字段）

| 字段名 | 中文含义 | 状态 |
|--------|----------|------|
| `ts_code` | TS股票代码 | → |
| `ann_date` | 公告日期 | → |
| `end_date` | 截止日期 | |
| `proc` | 实施进度（预案/实施/完成） | |
| `vol` | 已回购数量（股） | → |
| `amount` | 已回购金额（元） | → |
| `high_limit` | 回购最高价（元） | |
| `low_limit` | 回购最低价（元） | |
| `rep_type` | 回购类型（1股权激励 2注销） | → |
| `rep_reason` | 回购目的 | |
| `pct_total` | 回购股份占总股本比例 | |
| `actual_vol` | 实际回购数量 | |
| `actual_amount` | 实际回购金额 | |
| `pay_type` | 支付方式（自有资金/自筹资金等） | |
| `status` | 状态（进行中/已结束） | |

---

## 已知 Bug & 待新增

| 问题 | 当前错误 | 正确值 | 版本 |
|------|---------|--------|------|
| CAPEX 字段名错误 | `c_pay_for_tan_il`（不存在） | `c_pay_acq_const_fiolta` | ✅ v0.2.0 已修复 |
| 财务费用命名误导 | `interest_expense` | `finan_exp` | ✅ v0.2.0 已修复 |
| ~~缺字段：并购子公司~~ | — | `n_disp_subs_oth_biz` | ✅ v0.6.1 已拉取 |
| ~~缺字段：分红率~~ | — | `payout_ratio` | ✅ v0.6.1 已拉取 |
| ~~缺字段：筹资现金流~~ | `n_cashflow_fin_act` | `n_cash_flows_fnc_act` | ✅ v0.6.1 已修复 |
| 缺字段：投资支付 | — | `c_paid_invest` | |
| 缺字段：长期股权投资 | — | `lt_eqt_invest` | |

### v0.6.1 修复记录
- `tushare_client.py` 6 个 API 补全 `fields` 参数: income / balancesheet / cashflow / fina_indicator / dividend / daily_basic
- `data_fetcher.py` `n_cashflow_fin_act` → `n_cash_flows_fnc_act` (Tushare 官方字段名)
- `data_fetcher.py` `_normalize_to_yi()` 新增 `NON_MONETARY` 白名单，避免百分比/比率/EPS 被错误 ÷1e8

---

## 统计

| 接口 | 字段数 |
|------|--------|
| stock_basic | 14 |
| daily_basic | 16 |
| income | 64 |
| balancesheet | ~140 |
| cashflow | 93 |
| fina_indicator | 167 |
| dividend | 15 |
| repurchase | 15 |
| **合计** | **~524** |
