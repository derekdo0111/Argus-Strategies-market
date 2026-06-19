"""穿透回报率 v2 单元测试"""

import pytest
from app.strategies.turtle.penetration_return import PenetrationReturnCalculator, PRResult


def make_financial(year, revenue, net_profit, op_cf,
                   capex=2.0, acq_subs=0.0, lt_eqt_end=0.0, lt_eqt_begin=0.0,
                   fin_exp=0.5, depreciation=1.0, amortization=0.5):
    """创建一个简化财年数据条目"""
    return {
        "year": year,
        "income": {
            "revenue": revenue,
            "net_profit": net_profit,
            "fin_exp": fin_exp,
        },
        "balance_sheet": {
            "receivables": 10,
            "inventory": 15,
            "lt_eqt_invest": lt_eqt_end,
        },
        "cashflow": {
            "operating_cf": op_cf,
            "fcf": op_cf - 2.0,
            "depreciation": depreciation,
            "amortization": amortization,
            "capex": capex,
            "acq_subsidiary": acq_subs,
            "finan_exp": fin_exp,
        },
    }


def make_raw_data(ts_code, financials, dividends=None, repurchases=None, total_mv=1000.0):
    return {
        "meta": {"ts_code": ts_code, "name": "测试"},
        "basic_info": {"total_mv": total_mv},
        "annual_financials": financials,
        "dividend_history": dividends or [],
        "repurchase_history": repurchases or [],
    }


def make_stable_5y(base_op_cf=18.0):
    """生成6年稳定财务数据（前5年用于计算，第6年为边界长投提供年初值）"""
    ops = [19, 17, 20, 16, 18, 18]  # 6年, mean of first 5 = 18
    years = [2025, 2024, 2023, 2022, 2021, 2020]
    return [
        make_financial(yr, 100 + i * 5, 20 + i, op,
                       lt_eqt_end=50.0, lt_eqt_begin=50.0)
        for i, (yr, op) in enumerate(zip(years, ops))
    ]


class TestPenetrationReturnV2:
    """v2 核心测试"""

    def test_positive_pr_stable(self):
        """正常情况：5年稳定现金流 → PR通过"""
        calc = PenetrationReturnCalculator(risk_free_rate=2.5, spread=1.0)
        financials = make_stable_5y()
        dividends = [
            {"year": yr, "total_dividend": 10.0}
            for yr in [2025, 2024, 2023, 2022, 2021]
        ]
        raw = make_raw_data("000001.SZ", financials, dividends)
        result = calc.compute(raw)

        assert result.disposable_cash_avg > 0
        assert result.disposable_cash_cv < 0.5    # CV软门通过
        assert result.distribution_ratio > 0
        assert result.pr > 0
        assert result.threshold == 3.5  # 2.5 + 1.0

    def test_pr_below_threshold(self):
        """PR低于门槛 → 不通过"""
        calc = PenetrationReturnCalculator(risk_free_rate=2.5, spread=1.0)
        # 经营CF很小, 可支配现金接近0
        financials = [
            make_financial(yr, 100, 20, 3.0, capex=2.0, fin_exp=1.0)
            for yr in [2025, 2024, 2023, 2022, 2021]
        ]
        dividends = [{"year": yr, "total_dividend": 0.5} for yr in range(2021, 2026)]
        raw = make_raw_data("000001.SZ", financials, dividends, total_mv=5000.0)
        result = calc.compute(raw)

        assert result.pr < result.threshold
        assert not result.passed

    def test_cv_gate_rejects(self):
        """CV > 0.5 → 软门标记警告，不淘汰，继续计算PR"""
        calc = PenetrationReturnCalculator()
        # 大起大落的可支配现金: 正常CAPEX 2亿, 但中间一年CAPEX=80亿
        financials = [
            make_financial(2025, 100, 20, 20, capex=2),
            make_financial(2024, 100, 20, 20, capex=2),
            make_financial(2023, 100, 20, 20, capex=80),  # 大CAPEX年
            make_financial(2022, 100, 20, 20, capex=2),
            make_financial(2021, 100, 20, 20, capex=2),
        ]
        raw = make_raw_data("000001.SZ", financials, total_mv=1000.0)
        result = calc.compute(raw)

        assert result.disposable_cash_cv >= 0.5
        assert result.cv_warning is True       # v0.3.0: 软门标记
        assert result.pr == 0.0                # 无分红无回购 → PR=0
        assert not result.passed               # PR=0 < threshold

    def test_distribution_ratio_capped(self):
        """分配比率不超过100%"""
        calc = PenetrationReturnCalculator()
        financials = make_stable_5y()
        # 分红远超可支配现金
        dividends = [
            {"year": yr, "total_dividend": 1000.0}
            for yr in [2025, 2024, 2023, 2022, 2021]
        ]
        raw = make_raw_data("000001.SZ", financials, dividends)
        result = calc.compute(raw)

        assert result.distribution_ratio <= 1.0

    def test_only_cancellation_repurchase(self):
        """只有注销类回购才计入"""
        calc = PenetrationReturnCalculator()
        financials = make_stable_5y()
        repurchases = [
            {"year": 2025, "repurchase_amount": 5.0, "is_cancellation": True},
            {"year": 2024, "repurchase_amount": 3.0, "is_cancellation": False},
            {"year": 2023, "repurchase_amount": 4.0, "is_cancellation": True},
            {"year": 2022, "repurchase_amount": 2.0, "is_cancellation": False},
            {"year": 2021, "repurchase_amount": 1.0, "is_cancellation": True},
        ]
        raw = make_raw_data("000001.SZ", financials, repurchases=repurchases)
        result = calc.compute(raw)

        # 只有 2025(5), 2023(4), 2021(1) 计入: mean = 10/3 = 3.33...
        assert result.avg_repurchase_5y == pytest.approx(10.0 / 3, rel=0.1)

    def test_insufficient_years(self):
        """财务数据不足5年 → PR=0"""
        calc = PenetrationReturnCalculator()
        financials = [
            make_financial(2024, 100, 20, 18),
            make_financial(2023, 95, 19, 17),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = calc.compute(raw)

        assert result.pr == 0.0
        assert not result.passed

    def test_negative_disposable_cash_avg(self):
        """可支配现金均值为负 → 淘汰"""
        calc = PenetrationReturnCalculator()
        # 经营CF不够覆盖扣减项
        financials = [
            make_financial(yr, 100, 20, 5.0, capex=10.0, fin_exp=3.0)
            for yr in [2025, 2024, 2023, 2022, 2021]
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = calc.compute(raw)

        assert result.disposable_cash_avg < 0
        assert result.pr == 0.0
        assert not result.passed

    def test_zero_market_cap(self):
        """市值为0 → PR=0"""
        calc = PenetrationReturnCalculator()
        financials = make_stable_5y()
        raw = make_raw_data("000001.SZ", financials, total_mv=0.0)
        result = calc.compute(raw)

        assert result.pr == 0.0

    def test_lt_eqt_invest_increase(self):
        """参股净增额正确扣减"""
        calc = PenetrationReturnCalculator()
        # 长投从50增长到70 → 扣除20 (2025年)
        # 需提供6年数据：第6年的lt_eqt_invest作为2021年的年初值
        financials = [
            make_financial(2025, 100, 20, 50, lt_eqt_end=70, lt_eqt_begin=50, capex=0, fin_exp=0),
            make_financial(2024, 100, 20, 50, lt_eqt_end=50, lt_eqt_begin=50, capex=0, fin_exp=0),
            make_financial(2023, 100, 20, 50, lt_eqt_end=50, lt_eqt_begin=50, capex=0, fin_exp=0),
            make_financial(2022, 100, 20, 50, lt_eqt_end=50, lt_eqt_begin=50, capex=0, fin_exp=0),
            make_financial(2021, 100, 20, 50, lt_eqt_end=50, lt_eqt_begin=50, capex=0, fin_exp=0),
            # 2020: 为2021年提供年初长投=50，确保2021的增量=0
            make_financial(2020, 100, 20, 50, lt_eqt_end=50, lt_eqt_begin=50, capex=0, fin_exp=0),
        ]
        raw = make_raw_data("000001.SZ", financials, total_mv=1000.0)
        result = calc.compute(raw)

        # 只取前5年：2025=30, 2024=50, 2023=50, 2022=50, 2021=50 → mean=46
        assert result.disposable_cash_avg == pytest.approx(46.0, rel=0.01)

    def test_acq_subsidiary_deduction(self):
        """并购子公司正确扣减"""
        calc = PenetrationReturnCalculator()
        financials = [
            make_financial(yr, 100, 20, 50, acq_subs=10, capex=0, fin_exp=0)
            for yr in [2025, 2024, 2023, 2022, 2021]
        ]
        raw = make_raw_data("000001.SZ", financials, total_mv=1000.0)
        result = calc.compute(raw)

        # 每年: 50 - 0 - 10 - 0 - 0 = 40
        assert result.disposable_cash_avg == pytest.approx(40.0)

    def test_to_computed_format(self):
        """输出格式包含 v2 新字段"""
        calc = PenetrationReturnCalculator()
        result = PRResult(
            ts_code="000001.SZ",
            disposable_cash_values=[36, 34, 38, 32, 35],
            disposable_cash_avg=35.0,
            disposable_cash_cv=0.06,
            distribution_ratio=0.4,
            pr=6.0,
            passed=True,
        )
        fmt = calc.to_computed_format(result)

        assert fmt["disposable_cash"]["values_5y"] == [36, 34, 38, 32, 35]
        assert fmt["disposable_cash"]["cv"] == 0.06
        assert fmt["disposable_cash"]["cv_passed"] is True
        assert fmt["disposable_cash"]["cv_warning"] is False  # v0.3.0
        assert fmt["pr_result"]["pr"] == 6.0
        assert fmt["pr_result"]["passed"] is True

    def test_custom_risk_free_rate(self):
        """自定义无风险利率"""
        calc = PenetrationReturnCalculator(risk_free_rate=3.0, spread=1.0)
        assert calc.threshold == 4.0  # 3.0 + 1.0

    def test_distribution_ratio_zero_when_no_dividends(self):
        """无分红时分配比率为0"""
        calc = PenetrationReturnCalculator()
        financials = make_stable_5y()
        raw = make_raw_data("000001.SZ", financials, dividends=[])
        result = calc.compute(raw)

        assert result.distribution_ratio == 0.0
