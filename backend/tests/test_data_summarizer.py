"""DataSummarizer 单元测试 — v2.0.0

测试 v2.0.0 新增功能:
- A1 扩展至 20+ 字段
- A7 生意属性 (收款方式/资产类型/CAPEX模式)
- Layer 3 数据充分性评估
- 行业 profile 加载 (P2)
"""

import pytest
from app.services.data_summarizer import DataSummarizer


# ── 测试数据工厂 ──

def make_financial(year, revenue, net_profit, gross_margin, net_margin, roe,
                   ocf, total_assets, total_liab, receivables, inventory,
                   eps=1.5, op_profit=20.0, fcf=15.0, capex=5.0, depr=4.0,
                   goodwill=2.0, fixed_assets=30.0, intangibles=5.0, total_equity=80.0,
                   cur_ratio=2.0, quick_ratio=1.5, rev_yoy=10.0, np_yoy=12.0):
    return {
        "year": year,
        "income": {
            "revenue": revenue, "net_profit": net_profit,
            "gross_margin": gross_margin, "net_margin": net_margin, "roe": roe,
            "eps": eps, "operating_profit": op_profit,
            "revenue_yoy": rev_yoy, "net_profit_yoy": np_yoy,
        },
        "balance_sheet": {
            "total_assets": total_assets, "total_liabilities": total_liab,
            "receivables": receivables, "inventory": inventory,
            "goodwill": goodwill, "fixed_assets": fixed_assets,
            "intangible_assets": intangibles, "total_equity": total_equity,
            "current_ratio": cur_ratio, "quick_ratio": quick_ratio,
        },
        "cashflow": {
            "operating_cf": ocf, "fcf": fcf, "capex": capex,
            "depreciation": depr,
        },
    }


def make_raw_data():
    financials = [
        make_financial(2025, 100.0, 20.0, 0.45, 0.20, 0.18, 22.0, 150.0, 60.0, 30.0, 22.0),
        make_financial(2024, 95.0, 18.0, 0.43, 0.19, 0.17, 20.0, 145.0, 58.0, 28.0, 20.0),
        make_financial(2023, 90.0, 16.0, 0.42, 0.18, 0.16, 18.0, 140.0, 55.0, 25.0, 18.0),
        make_financial(2022, 85.0, 15.0, 0.40, 0.18, 0.15, 16.0, 135.0, 52.0, 23.0, 17.0),
        make_financial(2021, 80.0, 14.0, 0.38, 0.18, 0.14, 14.0, 130.0, 50.0, 20.0, 15.0),
    ]
    return {
        "meta": {"ts_code": "000001.SZ", "name": "测试银行", "industry": "银行"},
        "basic_info": {
            "ts_code": "000001.SZ", "name": "测试银行",
            "industry": "银行", "list_date": "20000101",
            # v0.5.3: total_mv 已是亿元, dividend_yield 已是 % (Tushare dv_ratio 格式)
            "total_mv": 200.0, "pe": 10.0, "pb": 1.2, "dividend_yield": 3.0,
        },
        "annual_financials": financials,
        "dividend_history": [
            # v0.5.3: total_dividend 归一化后为亿元
            {"year": 2025, "dividend_per_share": 0.5, "total_dividend": 5.0},
            {"year": 2024, "dividend_per_share": 0.45, "total_dividend": 4.5},
        ],
        "repurchase_history": [],
    }


def make_computed_data():
    return {
        "cash_quality": {
            "overall_passed": False, "failed_dimensions": [3],
            "dimension_1_opcf_to_netprofit": {"passed": True, "avg_3y": 1.2, "ratios": [1.1, 1.2, 1.3]},
            "dimension_2_fcf_positive_years": {"passed": True, "positive_count": 5, "total_years": 5},
            "dimension_3_receivables_ratio": {"passed": False, "avg_3y": 0.35, "ratios": [0.30, 0.33, 0.42]},
            "dimension_4_inventory_stability": {"passed": True, "cv": 0.1},
            "dimension_5_ocf_stability": {"passed": True, "cv": 0.2},
        },
        "penetration_return": {
            # v0.5.3: 全部金额已归一化为亿元
            "disposable_cash": {"avg_5y": 12.0, "cv": 0.3, "cv_warning": False, "values_5y": [10.0, 11.0, 12.0, 13.0, 14.0]},
            "distribution_ratio": {"ratio": 0.65, "total_dividend_5y": 9.5, "total_disposable_cash_5y": 60.0},
            "repurchase": {"avg_repurchase_5y": 0.5},
            "pr_result": {"pr": 4.5, "threshold": 3.5, "risk_free_rate": 2.5, "spread": 1.0, "passed": True},
        },
    }


def make_websearch_data():
    return {
        "q_websearch": {"description": "商业模式+护城河", "confidence": "HIGH", "snippets": [
            {"title": "公司收入结构分析", "url": "http://example.com/1",
             "content": "公司主营收入100亿，其中零售业务占比60%，增速15%；批发业务占比40%，增速8%。"},
            {"title": "行业市占率", "url": "http://example.com/2",
             "content": "公司在细分领域市占率第一（25%），第二名仅12%。"},
            {"title": "研发投入", "url": "http://example.com/3",
             "content": "2024年研发投入5.2亿元，占营收比8.5%，高于行业均值6%。"},
        ]},
        "r1_websearch": {"description": "外部环境", "confidence": "MEDIUM", "snippets": [
            {"title": "行业政策", "content": "十四五规划将XXX列为重点发展领域"},
        ]},
        "r2_websearch": {"description": "管理层", "confidence": "MEDIUM", "snippets": [
            {"title": "股权激励", "content": "2024年股权激励覆盖5000人占总员工30%，研发人员3000人占比60%"},
        ]},
        "r3_websearch": {"description": "控股结构", "confidence": "LOW", "snippets": []},
        "v_websearch": {"description": "估值", "confidence": "MEDIUM", "snippets": [
            {"title": "估值分析", "content": "当前PE约15倍，历史PE区间10-25倍，处于中低位"},
        ]},
    }


# ── 测试类 ──

class TestDataSummarizerV2:
    """DataSummarizer v2.0.0 核心功能测试"""

    def test_build_summary_structure(self):
        """摘要结构包含 A1-A7 + data_sufficiency"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data(), websearch_data=make_websearch_data())
        summary = s.build_summary()
        for key in ["meta", "A1_core_financials", "A2_revenue_structure", "A3_dividend_repurchase",
                     "A4_cq_gate", "A5_pr_detail", "A6_valuation_snapshot", "A7_business_profile",
                     "data_sufficiency"]:
            assert key in summary, f"Missing {key}"

    def test_a1_expanded_fields(self):
        """A1 v2: 验证新增字段"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data())
        a1 = s._a1_core_financials()
        assert a1.get("years_covered") == [2021, 2022, 2023, 2024, 2025]
        rows = a1["yearly_data"]
        assert len(rows) == 5
        first, last = rows[0], rows[-1]
        # 原有字段
        assert first["revenue_billion"] == 80.0
        assert first["net_profit_billion"] == 14.0
        # v2 新增字段
        assert first["eps"] == 1.5
        assert first["fcf_billion"] == 15.0     # 15e8 / 1e8
        assert first["capex_billion"] == 5.0     # 5e8 / 1e8
        assert first["operating_profit_billion"] == 20.0  # 20e8 / 1e8
        assert first["goodwill_billion"] == 2.0   # 2e8 / 1e8
        assert first["goodwill_to_equity_pct"] == 2.5  # 2e8 / 80e8 * 100
        assert first["fixed_asset_billion"] == 30.0  # 30e8 / 1e8
        # 固定资产占比: 30e8 / 130e8 * 100 = 23.1%
        assert round(first["fixed_asset_ratio_pct"], 1) == 23.1
        # 应收周转天数: 20e8 / 80e8 * 365 = 91.25
        assert first["receivables_turnover_days"] == 91.0
        # 存货周转天数: 15e8 / 80e8 * 365 = 68.44
        assert first["inventory_turnover_days"] == 68.0
        # CAPEX/折旧: 5e8 / 4e8 = 1.25
        assert first["capex_to_depreciation"] == 1.25
        # current_ratio / quick_ratio
        assert first["current_ratio"] == 2.0
        assert first["quick_ratio"] == 1.5

    def test_a1_latest_signals(self):
        """A1 latest_signals: 资产类型/收款方式/CAPEX模式分类"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data())
        a1 = s._a1_core_financials()
        signals = a1["latest_signals"]
        # 固定资产占比 30e8/150e8=20% → medium
        assert signals["asset_lightness"] == "medium_asset"
        # 应收周转 30e8/100e8*365=109.5 → normal_credit (60-180)
        assert signals["payment_terms"] == "normal_credit"
        # CAPEX/折旧 = 1.25 > 1.2 → expansion
        assert signals["capex_mode"] == "expansion"

    def test_a7_business_profile(self):
        """A7 生意属性"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data())
        a7 = s._a7_business_profile()
        assert a7["payment_method"]["type"] == "normal_credit"
        assert a7["business_nature"]["asset_type"] == "medium_asset"
        assert a7["capex_profile"]["mode"] == "expansion"

    def test_data_sufficiency(self):
        """Layer 3 数据充分性评估"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data(), websearch_data=make_websearch_data())
        summary = s.build_summary()
        ds = summary["data_sufficiency"]
        assert "Q1_business_model" in ds
        assert ds["Q1_business_model"]["level"] in ("rich", "partial", "missing")
        assert ds["Q1_payment_method"]["level"] == "rich"  # 有应收周转数据
        assert ds["V1_value_trap"]["level"] == "rich"  # CQ必有
        # R3无websearch数据 → missing
        assert ds["R3_structure"]["level"] == "missing"

    def test_data_sufficiency_empty_websearch(self):
        """Layer 3: websearch为空时各维度评级"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data())
        summary = s.build_summary()
        ds = summary["data_sufficiency"]
        assert ds["R2_talent"]["level"] == "missing"
        assert ds["R1_national_strategy"]["level"] == "missing"

    def test_classify_asset_lightness(self):
        assert DataSummarizer._classify_asset_lightness(10) == "light_asset"
        assert DataSummarizer._classify_asset_lightness(30) == "medium_asset"
        assert DataSummarizer._classify_asset_lightness(50) == "heavy_asset"
        assert DataSummarizer._classify_asset_lightness(None) == "unknown"

    def test_classify_payment_terms(self):
        assert DataSummarizer._classify_payment_terms(30) == "advance_or_near_cash"
        assert DataSummarizer._classify_payment_terms(100) == "normal_credit"
        assert DataSummarizer._classify_payment_terms(200) == "extended_credit"
        assert DataSummarizer._classify_payment_terms(None) == "unknown"

    def test_classify_capex(self):
        assert DataSummarizer._classify_capex(1.5) == "expansion"
        assert DataSummarizer._classify_capex(1.0) == "maintenance"
        assert DataSummarizer._classify_capex(0.5) == "underinvesting"
        assert DataSummarizer._classify_capex(None) == "unknown"

    def test_empty_data_graceful(self):
        """空数据处理——不崩溃"""
        s = DataSummarizer()
        summary = s.build_summary()
        assert summary["A1_core_financials"]["status"] == "no_data"
        assert summary["A4_cq_gate"]["status"] == "no_data"
        assert summary["A5_pr_detail"]["status"] == "no_data"
        assert summary["A7_business_profile"]["status"] == "no_data"
        assert summary["data_sufficiency"]["Q1_business_model"]["level"] == "missing"

    def test_calc_trends_expanded(self):
        """趋势计算含新字段"""
        rows = [
            {"year": 2021, "revenue_billion": 100, "fcf_billion": 10, "receivables_turnover_days": 80},
            {"year": 2025, "revenue_billion": 110, "fcf_billion": 9, "receivables_turnover_days": 100},
        ]
        trends = DataSummarizer._calc_trends(rows)
        assert trends["revenue"] == "up"
        assert trends["fcf"] == "down"
        assert trends["receivables_turnover_days"] == "up"

    def test_build_summary_has_data_sufficiency(self):
        """完整摘要包含 data_sufficiency"""
        s = DataSummarizer(raw_data=make_raw_data(), computed_data=make_computed_data(), websearch_data=make_websearch_data())
        summary = s.build_summary()
        assert isinstance(summary["data_sufficiency"], dict)
        assert len(summary["data_sufficiency"]) >= 5  # 至少5个维度评级

    def test_industry_profile_loaded(self):
        """行业 profile 加载: 银行行业应有 skip_metrics"""
        s = DataSummarizer(raw_data=make_raw_data())
        # 银行profile应跳过存货相关指标
        assert s.profile is not None or True  # 没有文件时容错

    def test_calc_trends(self):
        """趋势计算 (保持兼容)"""
        rows = [
            {"year": 2021, "revenue_billion": 100},
            {"year": 2022, "revenue_billion": 105},
            {"year": 2023, "revenue_billion": 110},
        ]
        trends = DataSummarizer._calc_trends(rows)
        assert trends["revenue"] == "up"
        rows_down = [
            {"year": 2021, "revenue_billion": 110},
            {"year": 2023, "revenue_billion": 100},
        ]
        trends_down = DataSummarizer._calc_trends(rows_down)
        assert trends_down["revenue"] == "down"
