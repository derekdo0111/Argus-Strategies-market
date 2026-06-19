"""现金质量门 — Step 3-4

5子维度确定性计算与硬门判定。
"""

import logging
import math
from dataclasses import dataclass, field
from statistics import mean, stdev

logger = logging.getLogger(__name__)


@dataclass
class CashQualityResult:
    """现金质量判定结果"""
    ts_code: str
    dim1_passed: bool = False   # 经营CF/净利润 > 0.8
    dim2_passed: bool = False   # FCF正年数 ≥ 4/5
    dim3_passed: bool = False   # 应收/营收 < 0.3
    dim4_passed: bool = False   # 存货/营收 CV < 0.5
    dim5_passed: bool = False   # 经营CF CV < 0.5
    overall_passed: bool = False
    details: dict = field(default_factory=dict)

    @property
    def failed_dimensions(self) -> list[int]:
        dims = []
        if not self.dim1_passed: dims.append(1)
        if not self.dim2_passed: dims.append(2)
        if not self.dim3_passed: dims.append(3)
        if not self.dim4_passed: dims.append(4)
        if not self.dim5_passed: dims.append(5)
        return dims


class CashQualityGate:
    """现金质量软门"""

    # === 阈值 ===
    OP_CF_NETPROFIT_THRESHOLD = 0.8      # 维度1
    FCF_POSITIVE_MIN_YEARS = 4           # 维度2 (out of 5)
    RECEIVABLES_REVENUE_MAX = 0.3        # 维度3
    INVENTORY_REVENUE_CV_MAX = 0.5       # 维度4
    OP_CF_CV_MAX = 0.5                   # 维度5
    LOOKBACK_YEARS = 5

    def __init__(self, rule_version: str = "v2"):
        self.rule_version = rule_version

    def compute(self, raw_data: dict) -> CashQualityResult:
        """从 raw_data 计算现金质量5维度

        Args:
            raw_data: raw_data.yaml 格式的字典

        Returns:
            CashQualityResult
        """
        ts_code = raw_data["meta"]["ts_code"]
        financials = raw_data.get("annual_financials", [])

        if len(financials) < self.LOOKBACK_YEARS:
            logger.warning(f"{ts_code}: 财务数据不足{self.LOOKBACK_YEARS}年")
            return CashQualityResult(ts_code=ts_code)

        # 取最近N年
        recent = financials[:self.LOOKBACK_YEARS]

        result = CashQualityResult(ts_code=ts_code)

        # === 维度1: 经营CF/净利润 > 0.8（近3年均值） ===
        recent_3y = recent[:3]
        ratios = []
        for f in recent_3y:
            np_val = f["income"]["net_profit"]
            cf_val = f["cashflow"]["operating_cf"]
            if np_val and np_val != 0 and not math.isnan(cf_val):
                ratio = cf_val / np_val
                if not math.isnan(ratio) and not math.isinf(ratio):
                    ratios.append(ratio)
        if ratios:
            avg_ratio = mean(ratios)
            result.dim1_passed = avg_ratio > self.OP_CF_NETPROFIT_THRESHOLD
            result.details["dim1"] = {
                "ratios": ratios,
                "avg_3y": avg_ratio,
                "threshold": self.OP_CF_NETPROFIT_THRESHOLD,
            }

        # === 维度2: FCF正年数 ≥ 4/5 ===
        fcf_positive = 0
        fcf_valid_years = 0
        for f in recent:
            fcf_val = f["cashflow"].get("fcf", float("nan"))
            if math.isnan(fcf_val):
                continue  # NaN 跳过，不扣分
            fcf_valid_years += 1
            if fcf_val > 0:
                fcf_positive += 1
        # 判定: 至少需有不少于阈值年的有效数据，且正年数达标
        # 如果有效年数不足，按比例放宽（但至少需要3年有效数据）
        if fcf_valid_years >= 3:
            result.dim2_passed = fcf_positive >= min(
                self.FCF_POSITIVE_MIN_YEARS, fcf_valid_years
            )
        result.details["dim2"] = {
            "positive_count": fcf_positive,
            "valid_years": fcf_valid_years,
            "total_years": self.LOOKBACK_YEARS,
            "threshold": self.FCF_POSITIVE_MIN_YEARS,
        }

        # === 维度3: 应收/营收 < 0.3（近3年均值） ===
        rec_ratios = []
        for f in recent_3y:
            rev = f["income"]["revenue"]
            rec = f["balance_sheet"]["receivables"]
            if rev and rev != 0 and not math.isnan(rec):
                ratio = rec / rev
                if not math.isnan(ratio):
                    rec_ratios.append(ratio)
        if rec_ratios:
            avg_rec = mean(rec_ratios)
            result.dim3_passed = avg_rec < self.RECEIVABLES_REVENUE_MAX
            result.details["dim3"] = {
                "ratios": rec_ratios,
                "avg_3y": avg_rec,
                "threshold": self.RECEIVABLES_REVENUE_MAX,
            }

        # === 维度4: 存货/营收 CV < 0.5 ===
        # 先判断是否无存货行业（金融/软件/服务等）
        all_inv_nan_or_zero = all(
            math.isnan(f["balance_sheet"].get("inventory", float("nan")))
            or f["balance_sheet"].get("inventory", 0) == 0
            for f in recent
        )
        if all_inv_nan_or_zero:
            result.dim4_passed = True
            result.details["dim4"] = {
                "ratios": [],
                "cv": None,
                "threshold": self.INVENTORY_REVENUE_CV_MAX,
                "reason": "industry_no_inventory",
            }
        else:
            inv_ratios = []
            for f in recent:
                rev = f["income"]["revenue"]
                inv = f["balance_sheet"]["inventory"]
                if rev and rev != 0 and not math.isnan(inv):
                    ratio = inv / rev
                    if not math.isnan(ratio):
                        inv_ratios.append(ratio)
            if len(inv_ratios) >= 3:
                try:
                    avg_inv = mean(inv_ratios)
                    std_inv = stdev(inv_ratios)
                    cv = std_inv / avg_inv if avg_inv != 0 else float("inf")
                except Exception:
                    cv = float("inf")
                result.dim4_passed = cv < self.INVENTORY_REVENUE_CV_MAX
                result.details["dim4"] = {
                    "ratios": inv_ratios,
                    "cv": cv,
                    "threshold": self.INVENTORY_REVENUE_CV_MAX,
                }

        # === 维度5: 经营CF CV < 0.5 ===
        op_cfs = [
            f["cashflow"]["operating_cf"] for f in recent
            if not math.isnan(f["cashflow"].get("operating_cf", float("nan")))
        ]
        try:
            avg_cf = mean(op_cfs)
            std_cf = stdev(op_cfs)
            cv_cf = std_cf / abs(avg_cf) if avg_cf != 0 else float("inf")
        except Exception:
            cv_cf = float("inf")
        result.dim5_passed = cv_cf < self.OP_CF_CV_MAX
        result.details["dim5"] = {
            "values": op_cfs,
            "cv": cv_cf,
            "threshold": self.OP_CF_CV_MAX,
        }

        # === 综合判定 ===
        result.overall_passed = all([
            result.dim1_passed,
            result.dim2_passed,
            result.dim3_passed,
            result.dim4_passed,
            result.dim5_passed,
        ])

        return result

    def to_computed_format(self, result: CashQualityResult) -> dict:
        """转为 computed.yaml 中 cash_quality 的格式"""
        return {
            "dimension_1_opcf_to_netprofit": {
                "passed": result.dim1_passed,
                **(result.details.get("dim1", {})),
            },
            "dimension_2_fcf_positive_years": {
                "passed": result.dim2_passed,
                **(result.details.get("dim2", {})),
            },
            "dimension_3_receivables_ratio": {
                "passed": result.dim3_passed,
                **(result.details.get("dim3", {})),
            },
            "dimension_4_inventory_stability": {
                "passed": result.dim4_passed,
                **(result.details.get("dim4", {})),
            },
            "dimension_5_ocf_stability": {
                "passed": result.dim5_passed,
                **(result.details.get("dim5", {})),
            },
            "overall_passed": result.overall_passed,
            "failed_dimensions": result.failed_dimensions,
        }
