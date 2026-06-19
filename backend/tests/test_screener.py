"""选股器单元测试"""

import pytest
from app.strategies.turtle.screener import TurtleScreener, ScreenerStats, CYCLICAL_INDUSTRIES


def make_stock(ts_code="000001.SZ", name="平安银行", industry="银行", list_date="19910403",
               total_mv=3000.0, pe=15.0, pb=0.9, roe=13.0, dividend_yield=3.5,
               gross_margin=45.0, debt_ratio=45.0, opcf_to_netprofit=1.2):
    return {
        "ts_code": ts_code,
        "name": name,
        "industry": industry,
        "list_date": list_date,
        "total_mv": total_mv,
        "pe": pe,
        "pb": pb,
        "roe": roe,
        "dividend_yield": dividend_yield,
        "gross_margin": gross_margin,
        "debt_ratio": debt_ratio,
        "opcf_to_netprofit": opcf_to_netprofit,
    }


class TestTurtleScreener:
    def test_normal_stock_passes(self):
        screener = TurtleScreener(current_year=2026)
        stocks = [make_stock()]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 1
        assert stats.passed == 1

    def test_st_stock_excluded(self):
        screener = TurtleScreener()
        stocks = [make_stock(name="ST康美")]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0
        assert stats.fail_st == 1

    def test_delisted_stock_excluded(self):
        screener = TurtleScreener()
        stocks = [make_stock(name="退市昆机")]
        passed, _ = screener.screen(stocks)
        assert len(passed) == 0

    def test_star_st_excluded(self):
        screener = TurtleScreener()
        stocks = [make_stock(name="*ST信威")]
        passed, _ = screener.screen(stocks)
        assert len(passed) == 0

    def test_cyclical_industry_excluded(self):
        screener = TurtleScreener()
        for ind in CYCLICAL_INDUSTRIES:
            stocks = [make_stock(industry=ind)]
            passed, stats = screener.screen(stocks)
            assert len(passed) == 0, f"行业 {ind} 应被排除"

    def test_list_years_insufficient(self):
        screener = TurtleScreener(current_year=2026)
        stocks = [make_stock(list_date="20230101")]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0
        assert stats.fail_list_years == 1

    def test_list_years_exactly_8_passes(self):
        screener = TurtleScreener(current_year=2026)
        stocks = [make_stock(list_date="20180101")]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 1

    def test_list_years_under_8_fails(self):
        screener = TurtleScreener(current_year=2026)
        stocks = [make_stock(list_date="20210101")]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0
        assert stats.fail_list_years == 1

    def test_market_cap_too_small(self):
        screener = TurtleScreener()
        stocks = [make_stock(total_mv=150.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0
        assert stats.fail_market_cap == 1

    def test_market_cap_exactly_200_passes(self):
        screener = TurtleScreener()
        stocks = [make_stock(total_mv=200.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 1

    def test_roe_zero_or_negative(self):
        screener = TurtleScreener()
        stocks = [make_stock(roe=0.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0
        assert stats.fail_roe == 1

    def test_roe_below_12_fails(self):
        """新阈值 ROE > 12%"""
        screener = TurtleScreener()
        stocks = [make_stock(roe=10.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_pe_out_of_range(self):
        screener = TurtleScreener()
        # PE <= 5
        passed, stats = screener.screen([make_stock(pe=3.0)])
        assert len(passed) == 0
        # PE >= 25
        passed, stats = screener.screen([make_stock(pe=30.0)])
        assert len(passed) == 0

    def test_no_dividend(self):
        screener = TurtleScreener()
        stocks = [make_stock(dividend_yield=0.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_dividend_below_2_5_fails(self):
        """新阈值 股息率 > 2.5%"""
        screener = TurtleScreener()
        stocks = [make_stock(dividend_yield=2.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_gross_margin_too_low(self):
        screener = TurtleScreener()
        stocks = [make_stock(gross_margin=20.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_debt_ratio_too_high(self):
        screener = TurtleScreener()
        stocks = [make_stock(debt_ratio=65.0)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_opcf_not_screened(self):
        """原条件10(经营CF)已删 — OCF现在由CQ维度1精确检查，不再在选股器阶段过滤"""
        screener = TurtleScreener()
        # 即使 ocf_to_netprofit 很低，如果其他条件全满足也应通过选股器
        stocks = [make_stock(opcf_to_netprofit=0.3)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 1  # 选股器不再过滤 OCF

    def test_pb_zero_or_negative(self):
        screener = TurtleScreener()
        stocks = [make_stock(pb=-0.5)]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 0

    def test_multiple_stocks_mixed(self):
        screener = TurtleScreener()
        stocks = [
            make_stock(ts_code="000001.SZ"),
            make_stock(ts_code="000002.SZ", name="ST测试"),
            make_stock(ts_code="000003.SZ", industry="钢铁"),
        ]
        passed, stats = screener.screen(stocks)
        assert len(passed) == 1
        assert passed[0].ts_code == "000001.SZ"

    def test_fail_summary_format(self):
        screener = TurtleScreener()
        stats = ScreenerStats(total_input=100, passed=60)
        summary = screener.get_fail_summary(stats)
        assert "100" in summary
        assert "60" in summary
        assert "40" in summary  # eliminated
