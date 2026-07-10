"""Tushare 客户端封装

统一管理 Tushare Pro API 连接、重试、频率控制。
v0.15.0: 移除代理模式，仅直连官方 API。
"""

import logging
import time
from typing import Optional

import tushare as ts

from app.core.config import settings

logger = logging.getLogger(__name__)

# Tushare API 频率限制：每分钟最多 200 次（Pro 版）
# 保守设置：每秒 3 次
RATE_LIMIT_INTERVAL = 0.35  # 秒


class TushareClient:
    """Tushare Pro API 客户端 — 直连模式"""

    def __init__(self, token: Optional[str] = None):
        """
        Args:
            token: Tushare token，不传则从 settings 读取
        """
        self.token = token or settings.TUSHARE_TOKEN
        self._pro: Optional[ts.pro_api] = None
        self._last_call = 0.0

    @property
    def pro(self) -> ts.pro_api:
        if self._pro is None:
            ts.set_token(self.token)
            self._pro = ts.pro_api()
            logger.debug("Tushare 直连模式")
        return self._pro

    def _rate_limit(self):
        """频率控制：3次/秒"""
        elapsed = time.monotonic() - self._last_call
        if elapsed < RATE_LIMIT_INTERVAL:
            time.sleep(RATE_LIMIT_INTERVAL - elapsed)
        self._last_call = time.monotonic()

    def call(self, api_name: str, **kwargs) -> "pd.DataFrame":
        """通用 API 调用 — 直连 + 重试

        Args:
            api_name: Tushare API 函数名，如 'income', 'daily'
            **kwargs: API 参数

        Returns:
            DataFrame
        """
        import pandas as pd

        max_retries = 3
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                self._rate_limit()
                func = getattr(self.pro, api_name)
                result = func(**kwargs)
                if result is None or result.empty:
                    if attempt < 1:
                        logger.debug(f"{api_name}({kwargs}): 空结果，重试一次")
                        continue
                    logger.debug(f"{api_name}({kwargs}): 空结果")
                    return pd.DataFrame()
                logger.debug(f"{api_name}({kwargs}): {len(result)} 条")
                return result
            except Exception as e:
                logger.warning(
                    f"{api_name} 失败 (attempt {attempt + 1}/{max_retries}): {e}"
                )
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        logger.error(f"{api_name} 所有重试均失败")
        if last_error:
            raise last_error
        return pd.DataFrame()

    # === 基础数据 ===

    def get_stock_basic(self, list_status: str = "L") -> "pd.DataFrame":
        """获取全A股基本信息

        Returns:
            ts_code, name, industry, list_date, list_status
        """
        return self.call(
            "stock_basic",
            exchange="",
            list_status=list_status,
            fields="ts_code,name,industry,list_date,list_status",
        )

    def get_namechange(self, ts_code: str) -> "pd.DataFrame":
        """获取股票名称变更历史"""
        return self.call("namechange", ts_code=ts_code)

    # === 财务数据 ===

    def get_income(
        self, ts_code: str, start_date: str = "20140101", end_date: str = ""
    ) -> "pd.DataFrame":
        """利润表 — 显式字段拉取

        v0.6.1: 显式指定 fields，确保利息收入/费用端等字段不被 Tushare 默认返回截断。
        """
        return self.call(
            "income",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,end_date,report_type,revenue,n_income_attr_p,n_income,"
                   "operate_profit,basic_eps,fin_exp,total_profit,sell_exp,"
                   "admin_exp,oper_cost,rd_exp,int_income,invest_income",
        )

    def get_balance_sheet(
        self, ts_code: str, start_date: str = "20140101", end_date: str = ""
    ) -> "pd.DataFrame":
        """资产负债表 — 显式字段拉取

        v0.6.1: 显式指定 fields，确保 total_cur_assets/liab 等字段被拉取。
        """
        return self.call(
            "balancesheet",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,end_date,report_type,total_assets,total_liab,"
                   "accounts_receiv,inventories,goodwill,fix_assets,intan_assets,"
                   "lt_eqt_invest,total_hldr_eqy_exc_min_int,total_hldr_eqy_inc_min_int,"
                   "total_cur_assets,total_cur_liab,"
                   "accounts_payable,notes_payable,contract_liab,advance_receipts,"
                   "st_borrow,lt_borrow,bonds_payable,noncurrent_liab_due_in_1y",
        )

    def get_cashflow(
        self, ts_code: str, start_date: str = "20140101", end_date: str = ""
    ) -> "pd.DataFrame":
        """现金流量表 — 显式字段拉取

        v0.6.1: 显式指定 fields，确保 financing_cf/acq_subsidiary 等字段被拉取。
        字段名修正: n_cashflow_fin_act → n_cash_flows_fnc_act (Tushare 官方字段名)
        """
        return self.call(
            "cashflow",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,end_date,report_type,n_cashflow_act,"
                   "c_pay_acq_const_fiolta,free_cashflow,depr_fa_coga_dpba,"
                   "amort_intang_assets,lt_amort_deferred_exp,use_right_asset_dep,"
                   "n_cashflow_inv_act,n_cash_flows_fnc_act,n_disp_subs_oth_biz,"
                   "finan_exp,c_pay_dist_dpcp_int_exp",
        )

    def get_fina_indicator(
        self, ts_code: str, start_date: str = "20140101", end_date: str = ""
    ) -> "pd.DataFrame":
        """财务指标（ROE, ROA, 毛利率等）

        v0.6.1: 显式指定 fields，确保当前/速动比率被拉取。
        v0.9.8: 新增 revenue_yoy, net_profit_yoy, debt_to_assets 支撑景气打分全维度。
        v0.9.8-hotfix: 修正字段名 — Tushare 正确字段是 or_yoy(营收同比)/netprofit_yoy(归母净利同比)，
                       代码内部统一 rename 为 revenue_yoy/net_profit_yoy 保持下游兼容。
        """
        result = self.call(
            "fina_indicator",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,end_date,roe,roe_yearly,grossprofit_margin,"
                   "netprofit_margin,current_ratio,quick_ratio,"
                   "or_yoy,netprofit_yoy,debt_to_assets",
        )
        if not result.empty:
            result = result.rename(columns={
                "or_yoy": "revenue_yoy",
                "netprofit_yoy": "net_profit_yoy",
            })
        return result

    def get_fina_mainbz(
        self, ts_code: str, start_date: str = "20200101", end_date: str = ""
    ) -> "pd.DataFrame":
        """主营业务构成（fina_mainbz_vip，需积分权限）

        Returns:
            ts_code, end_date, bz_item (业务名称), bz_sales (收入),
            bz_profit (利润), bz_cost (成本), bz_profit_ratio (利润率),
            type (报告类型), update_flag
        """
        return self.call(
            "fina_mainbz",  # 500积分（非_vip版5000积分），按ts_code逐只查询
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,"
                   "bz_profit_ratio,type,update_flag",
        )

    def get_fina_audit(
        self, ts_code: str, start_date: str = "20140101", end_date: str = ""
    ) -> "pd.DataFrame":
        """财务审计意见"""
        return self.call(
            "fina_audit",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    # === 分红与回购 ===

    def get_dividend(self, ts_code: str) -> "pd.DataFrame":
        """分红送股数据

        v0.6.1: 显式指定 fields，确保 payout_ratio 被拉取。
        """
        return self.call(
            "dividend",
            ts_code=ts_code,
            fields="ts_code,end_date,cash_div,payout_ratio,div_proc",
        )

    def get_repurchase(self, ts_code: str) -> "pd.DataFrame":
        """回购数据

        Returns:
            ts_code, ann_date (公告日期), end_date,
            proc (进度), exp_date (截止日期),
            vol (回购数量), amount (回购金额),
            high_limit, low_limit (回购价格区间),
            rep_type (回购类型: 1股权激励/2注销)
        """
        return self.call("repurchase", ts_code=ts_code)

    # === 行情 ===

    def get_daily(
        self, ts_code: str, start_date: str = "20180101", end_date: str = ""
    ) -> "pd.DataFrame":
        """日线行情

        Returns:
            trade_date, ts_code, open, high, low, close,
            vol (成交量), amount (成交额)
        """
        return self.call(
            "daily",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def get_daily_basic(
        self, ts_code: str, start_date: str = "20180101", end_date: str = ""
    ) -> "pd.DataFrame":
        """每日指标（PE, PB, 换手率等）

        v0.6.1: 显式指定 fields，确保 pe_ttm/pb/dv_ratio/total_share/total_mv/circ_mv 被拉取。
        """
        return self.call(
            "daily_basic",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,pe_ttm,pe,pb,dv_ratio,"
                   "total_mv,circ_mv,total_share",
        )

    # === 行业分类 ===

    def get_industry(self, level: str = "L1") -> "pd.DataFrame":
        """申万行业分类

        Args:
            level: L1(一级) / L2(二级) / L3(三级)
        """
        return self.call("index_classify", level=level, src="SW2021")

    # === 概念板块 ===

    def get_concept_detail(self, concept_name: str = None) -> "pd.DataFrame":
        """获取概念板块成分股明细（免费接口，0 积分）

        Args:
            concept_name: 概念名称，如 "新能源"。为空则返回所有概念明细。

        Returns:
            含 id, concept_name, ts_code, name, start_date, end_date 的 DataFrame
        """
        kwargs = {}
        if concept_name:
            kwargs["concept_name"] = concept_name
        return self.call("concept_detail", **kwargs)

    def get_ths_index(self, exchange: str = "A", type: str = "N") -> "pd.DataFrame":
        """获取同花顺概念/行业板块列表（2000 积分可用）

        Args:
            exchange: 交易所代码，A=全部
            type: N=概念指数, I=行业指数, S=同花顺特色

        Returns:
            含 ts_code, name, count, exchange, type 的 DataFrame
        """
        return self.call("ths_index", exchange=exchange, type=type)

    def get_ths_member(self, ts_code: str) -> "pd.DataFrame":
        """获取同花顺板块成分股（需积分权限）

        Args:
            ts_code: 板块指数代码，如 '885800.TI'

        Returns:
            含 ts_code (股票代码), name (股票名称) 的 DataFrame
        """
        return self.call("ths_member", ts_code=ts_code)
