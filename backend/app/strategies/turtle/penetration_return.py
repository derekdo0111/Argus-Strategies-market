"""穿透回报率计算 — v2

PR = (可支配现金均值 × 分配比率 + 回购注销) / 总市值 × 100%
硬门判定: PR ≥ 无风险利率 + 利差

v2 公式（5年逐期可支配现金）:
  可支配现金_i = n_cashflow_act_i                      # 经营CF净额
               − c_pay_acq_const_fiolta_i             # 购建固定资产（真实CAPEX）
               − n_disp_subs_oth_biz_i                # 并购子公司（取得子公司支付现金）
               − max(0, lt_eqt_invest_年末_i − lt_eqt_invest_年初_i)  # 参股净增额
               − fin_exp_i                            # 财务费用（利润表）

  可支配现金_avg = mean(可支配现金₁ ... ₅)
  可支配现金_CV  = std / |avg|           # 软门: CV < 0.5 标记警告，不淘汰

分配比率 = min(5年分红总额 / 5年可支配现金总额, 100%)

PR = (可支配现金_avg × 分配比率 + 近5年年均回购注销) / 总市值 × 100%
"""

import logging
import math
from dataclasses import dataclass, field
from statistics import mean, stdev

logger = logging.getLogger(__name__)


@dataclass
class PRResult:
    """穿透回报率计算结果 (v2)"""
    ts_code: str

    # 可支配现金（5年逐期）
    disposable_cash_values: list = field(default_factory=list)  # [y1, y2, y3, y4, y5]
    disposable_cash_avg: float = 0.0
    disposable_cash_cv: float = 0.0   # 变异系数

    # 分配比率
    total_dividend_5y: float = 0.0
    total_disposable_cash_5y: float = 0.0
    distribution_ratio: float = 0.0

    # 回购
    avg_repurchase_5y: float = 0.0

    # 软门标记（v0.3.0: CV≥0.5时标记但不淘汰）
    cv_warning: bool = False

    # PR
    pr: float = 0.0
    risk_free_rate: float = 0.0
    threshold: float = 0.0
    passed: bool = False

    # 总市值
    total_mv: float = 0.0


class PenetrationReturnCalculator:
    """穿透回报率计算器 (v2)"""

    CV_MAX = 0.5                                # 可支配现金 CV 软门（标记警告，不提前返回）
    MAX_DISTRIBUTION_RATIO = 1.0                # 分配比率上限
    MIN_VALID_YEARS = 3                         # 至少3年可支配现金为正

    def __init__(self, risk_free_rate: float = 1.7, spread: float = 1.0,
                 rule_version: str = "v2"):
        """
        Args:
            risk_free_rate: 无风险利率（%），默认1.7%（10年期国债）
            spread: PR门槛利差（%），默认1.0%
            rule_version: 规则版本

        v0.5.3: raw_data 全部金额已归一化为亿元，PR 公式无需单位换算。
        """
        self.risk_free_rate = risk_free_rate
        self.spread = spread
        self.rule_version = rule_version
        self._threshold = risk_free_rate + spread

    @property
    def threshold(self) -> float:
        return self._threshold

    # ──────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _safe_mean(values: list) -> float:
        return mean(values) if values else 0.0

    @staticmethod
    def _safe_cv(values: list) -> float:
        """变异系数 = std / |mean|, mean ≤ 0 时返回极大值"""
        if len(values) < 2:
            return float("inf")
        avg = mean(values)
        if abs(avg) < 1e-6:
            return float("inf")
        return stdev(values) / abs(avg)

    # ──────────────────────────────────────────────
    # 主计算
    # ──────────────────────────────────────────────

    def compute(self, raw_data: dict) -> PRResult:
        """计算穿透回报率 (v2: 5年逐期可支配现金)

        Args:
            raw_data: raw_data 格式字典, financials 按年份降序排列

        Returns:
            PRResult
        """
        ts_code = raw_data["meta"]["ts_code"]
        financials = raw_data.get("annual_financials", [])

        if len(financials) < 5:
            logger.warning(f"{ts_code}: 财务数据不足5年（仅{len(financials)}年），无法计算PR v2")
            result = PRResult(ts_code=ts_code)
            result.risk_free_rate = self.risk_free_rate
            result.threshold = self._threshold
            result.total_mv = raw_data["basic_info"].get("total_mv", 0)
            return result

        recent_5y = financials[:5]  # 降序, 最新在前

        result = PRResult(ts_code=ts_code)
        result.total_mv = raw_data["basic_info"].get("total_mv", 0)
        result.risk_free_rate = self.risk_free_rate
        result.threshold = self._threshold

        # ── Step 1: 逐年计算可支配现金 ──
        dc_values = []
        for i, f in enumerate(recent_5y):
            dc = self._calc_disposable_cash_for_year(f, financials, i)
            dc_values.append(dc)

        result.disposable_cash_values = dc_values
        result.disposable_cash_avg = self._safe_mean(dc_values)
        result.disposable_cash_cv = self._safe_cv(dc_values)

        # CV 软门（v0.3.0: 标记警告，不提前返回，继续算分红/回购/PR）
        if result.disposable_cash_cv >= self.CV_MAX:
            logger.info(
                f"{ts_code}: 可支配现金 CV={result.disposable_cash_cv:.3f} >= "
                f"{self.CV_MAX}, 警告（软门，继续计算，交QRV Agent综合研判）"
            )
            result.cv_warning = True

        # 均值 ≤ 0 淘汰
        if result.disposable_cash_avg <= 0:
            logger.info(f"{ts_code}: 可支配现金均值={result.disposable_cash_avg:.1f} <= 0, 淘汰")
            return result

        # ── Step 2: 分配比率（5年总额/总额）──
        result.total_disposable_cash_5y = sum(dc_values)
        result.total_dividend_5y = self._calc_5y_dividend_total(raw_data, recent_5y)

        if result.total_disposable_cash_5y > 0:
            # v0.5.3: 全部金额已归一化为亿元，直接除
            result.distribution_ratio = min(
                result.total_dividend_5y / result.total_disposable_cash_5y,
                self.MAX_DISTRIBUTION_RATIO,
            )

        # ── Step 3: 回购注销（5年）──
        result.avg_repurchase_5y = self._calc_5y_avg_repurchase(raw_data, recent_5y)

        # ── Step 4: PR ──
        # v0.5.3: 全部金额已归一化为亿元，直接计算无需换算
        if result.total_mv > 0:
            result.pr = (
                (result.disposable_cash_avg * result.distribution_ratio
                 + result.avg_repurchase_5y)
                / result.total_mv
                * 100
            )

        result.passed = result.pr >= self._threshold
        return result

    # ──────────────────────────────────────────────
    # 内部计算
    # ──────────────────────────────────────────────

    def _calc_disposable_cash_for_year(self, f: dict, all_financials: list,
                                        idx: int) -> float:
        """计算单个财年的可支配现金。

        Args:
            f: 当前财年 financials 条目
            all_financials: 全部 financials（降序）
            idx: 当前条目在 recent_5y 中的索引

        Returns:
            可支配现金（元）
        """
        cf = f.get("cashflow", {})
        inc = f.get("income", {})
        bs = f.get("balance_sheet", {})

        # ① 经营CF净额
        op_cf = cf.get("operating_cf", 0.0)
        if math.isnan(op_cf):
            op_cf = 0.0

        # ② CAPEX（购建固定资产）
        capex = cf.get("capex", 0.0)
        if math.isnan(capex):
            capex = 0.0

        # ③ 并购子公司（取得子公司支付现金）
        acq_subs = cf.get("acq_subsidiary", 0.0)
        if math.isnan(acq_subs):
            acq_subs = 0.0

        # ④ 参股净增额 = max(0, 年末长投 − 年初长投)
        #    年初长投 = 上一年度的 lt_eqt_invest
        lt_eqt_end = bs.get("lt_eqt_invest", 0.0)
        if math.isnan(lt_eqt_end):
            lt_eqt_end = 0.0

        lt_eqt_begin = 0.0
        # idx+1 = 上一年度在列表中的位置
        prev_idx = idx + 1
        if prev_idx < len(all_financials):
            prev_bs = all_financials[prev_idx].get("balance_sheet", {})
            lt_eqt_begin = prev_bs.get("lt_eqt_invest", 0.0)
            if math.isnan(lt_eqt_begin):
                lt_eqt_begin = 0.0

        lt_eqt_increase = max(0.0, lt_eqt_end - lt_eqt_begin)

        # ⑤ 财务费用（利润表）
        fin_exp = inc.get("fin_exp", 0.0)
        if math.isnan(fin_exp):
            fin_exp = 0.0

        return op_cf - capex - acq_subs - lt_eqt_increase - fin_exp

    def _calc_5y_dividend_total(self, raw_data: dict, recent_5y: list) -> float:
        """计算5年分红总额（按财年匹配，万元）"""
        fiscal_years = {f["year"] for f in recent_5y}
        dividends = raw_data.get("dividend_history", [])
        recent_dividends = [d for d in dividends if d["year"] in fiscal_years]

        year_totals = {}
        for d in recent_dividends:
            year = d["year"]
            amt = d.get("total_dividend", 0)
            year_totals[year] = year_totals.get(year, 0) + amt

        return sum(year_totals.values())

    def _calc_5y_avg_repurchase(self, raw_data: dict, recent_5y: list) -> float:
        """计算近5年年均回购注销金额（元），仅计入注销类回购"""
        fiscal_years = {f["year"] for f in recent_5y}
        repurchases = raw_data.get("repurchase_history", [])
        recent_rep = [r for r in repurchases if r["year"] in fiscal_years]

        year_totals = {}
        for r in recent_rep:
            if r.get("is_cancellation", False):
                year = r["year"]
                amt = r.get("repurchase_amount", 0)
                year_totals[year] = year_totals.get(year, 0) + amt

        if year_totals:
            return sum(year_totals.values()) / len(year_totals)
        return 0.0

    # ──────────────────────────────────────────────
    # 输出格式化
    # ──────────────────────────────────────────────

    def to_computed_format(self, result: PRResult) -> dict:
        """转为 computed.yaml 中 penetration_return 的格式"""
        return {
            "disposable_cash": {
                "values_5y": result.disposable_cash_values,
                "avg_5y": result.disposable_cash_avg,
                "cv": result.disposable_cash_cv,
                "cv_passed": result.disposable_cash_cv < self.CV_MAX,
                "cv_warning": result.cv_warning,  # v0.3.0: 软门标记
            },
            "distribution_ratio": {
                "total_dividend_5y": result.total_dividend_5y,
                "total_disposable_cash_5y": result.total_disposable_cash_5y,
                "ratio": result.distribution_ratio,
            },
            "repurchase": {
                "avg_repurchase_5y": result.avg_repurchase_5y,
            },
            "pr_result": {
                "pr": result.pr,
                "formula": "(disposable_cash_avg × distribution_ratio + repurchase) / total_mv",
                "risk_free_rate": result.risk_free_rate,
                "spread": self.spread,
                "threshold": result.threshold,
                "passed": result.passed,
            },
        }
