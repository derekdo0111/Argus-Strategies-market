"""现金质量门单元测试"""

import pytest
from app.strategies.turtle.cash_quality import CashQualityGate, CashQualityResult


def make_financial(year, revenue, net_profit, op_cf, fcf, receivables, inventory,
                    depreciation=1.0, amortization=0.5, interest=0.5):
    return {
        "year": year,
        "income": {
            "revenue": revenue,
            "net_profit": net_profit,
        },
        "balance_sheet": {
            "receivables": receivables,
            "inventory": inventory,
        },
        "cashflow": {
            "operating_cf": op_cf,
            "fcf": fcf,
            "depreciation": depreciation,
            "amortization": amortization,
            "finan_exp": interest,
        },
    }


def make_raw_data(ts_code, financials):
    return {
        "meta": {"ts_code": ts_code, "name": "测试"},
        "annual_financials": financials,
    }


class TestCashQualityGate:
    def test_all_dimensions_pass(self):
        """全部维度通过的理想情况"""
        gate = CashQualityGate()
        financials = [
            make_financial(2024, 100, 20, 18, 5, 10, 15),
            make_financial(2023, 95, 19, 17, 4, 9, 14),
            make_financial(2022, 90, 18, 16, 3, 8, 13),
            make_financial(2021, 85, 17, 15, 2, 8, 12),
            make_financial(2020, 80, 16, 14, 1, 7, 11),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = gate.compute(raw)
        assert result.overall_passed
        assert result.dim1_passed
        assert result.dim2_passed
        assert result.dim3_passed
        assert result.dim4_passed
        assert result.dim5_passed

    def test_dim1_opcf_netprofit_fails(self):
        """经营CF/净利润不达标"""
        gate = CashQualityGate()
        financials = [
            make_financial(2024, 100, 20, 10, 5, 10, 15),  # ratio=0.5
            make_financial(2023, 95, 19, 10, 4, 9, 14),
            make_financial(2022, 90, 18, 10, 3, 8, 13),
            make_financial(2021, 85, 17, 15, 2, 8, 12),
            make_financial(2020, 80, 16, 14, 1, 7, 11),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = gate.compute(raw)
        assert not result.dim1_passed
        assert not result.overall_passed
        assert 1 in result.failed_dimensions

    def test_dim2_fcf_positive_fails(self):
        """FCF正年数不达标"""
        gate = CashQualityGate()
        financials = [
            make_financial(2024, 100, 20, 18, -1, 10, 15),
            make_financial(2023, 95, 19, 17, -1, 9, 14),
            make_financial(2022, 90, 18, 16, -1, 8, 13),
            make_financial(2021, 85, 17, 15, 1, 8, 12),
            make_financial(2020, 80, 16, 14, 1, 7, 11),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = gate.compute(raw)
        assert not result.dim2_passed
        assert 2 in result.failed_dimensions

    def test_dim3_receivables_fails(self):
        """应收/营收比过高"""
        gate = CashQualityGate()
        financials = [
            make_financial(2024, 100, 20, 18, 5, 40, 15),  # ratio=0.4
            make_financial(2023, 95, 19, 17, 4, 38, 14),
            make_financial(2022, 90, 18, 16, 3, 36, 13),
            make_financial(2021, 85, 17, 15, 2, 8, 12),
            make_financial(2020, 80, 16, 14, 1, 7, 11),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = gate.compute(raw)
        assert not result.dim3_passed
        assert 3 in result.failed_dimensions

    def test_insufficient_data(self):
        """数据不足5年"""
        gate = CashQualityGate()
        financials = [
            make_financial(2024, 100, 20, 18, 5, 10, 15),
            make_financial(2023, 95, 19, 17, 4, 9, 14),
        ]
        raw = make_raw_data("000001.SZ", financials)
        result = gate.compute(raw)
        assert not result.overall_passed

    def test_to_computed_format(self):
        gate = CashQualityGate()
        result = CashQualityResult(ts_code="000001.SZ", overall_passed=True)
        fmt = gate.to_computed_format(result)
        assert fmt["overall_passed"]
        assert "failed_dimensions" in fmt
