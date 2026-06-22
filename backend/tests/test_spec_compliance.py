"""SPEC 合规测试 — v0.5.0

验证 coordinator.py / screener.py / qrv_agent.py 是否符合
turtle-coordinator.md + ADR 的要求。

v0.5.0 新增:
- QRV Agent prompt 含 Q3/R2人才/生意本质/data_sufficiency
- DataSummarizer A1 20+字段
"""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.strategies.turtle.coordinator import TurtleCoordinator, CoordinatorState
from app.strategies.turtle.screener import TurtleScreener, ScreenerResult


@pytest.fixture
def temp_cache_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def sample_candidates():
    return [
        ScreenerResult(
            ts_code=f"{600000 + i:06d}.SH",
            name=f"测试股{i}",
            industry="食品饮料",
            list_date="20100101",
            total_mv=200.0 + i * 10,
            pe=15.0, pb=2.0, roe=14.0,
            dividend_yield=3.0, gross_margin=40.0, debt_ratio=30.0,
        )
        for i in range(5)
    ]


@pytest.fixture
def valid_raw_data():
    return {
        "meta": {"ts_code": "600900.SH", "name": "长江电力", "data_completeness": "full"},
        "basic_info": {"total_mv": 500.0, "pe": 20.0, "pb": 2.5, "dividend_yield": 3.0,
                       "industry": "电力", "list_date": "20100101"},
        "annual_financials": [
            {
                "year": 2025, "income": {"revenue": 100.0, "net_profit": 20.0, "gross_margin": 60.0, "fin_exp": 1.0, "operate_cost": 40.0},
                "balance_sheet": {"receivables": 5.0, "inventory": 0, "lt_eqt_invest": 5.0,
                    "total_assets": 100.0, "total_liabilities": 30.0,
                    "accounts_payable": 3.0, "notes_payable": 1.0,
                    "contract_liab": 0, "advance_receipts": 0,
                    "st_borrow": 5.0, "lt_borrow": 10.0, "bonds_payable": 0, "noncurrent_liab_due_in_1y": 0},
                "cashflow": {"operating_cf": 30.0, "fcf": 20.0, "depr_amort": 10.0, "finan_exp": 1.0,
                             "capex": 5.0, "acq_subsidiary": 0, "dividend_paid_cf": 10.0},
            },
            {
                "year": 2024, "income": {"revenue": 90.0, "net_profit": 18.0, "gross_margin": 58.0, "fin_exp": 1.2, "operate_cost": 36.0},
                "balance_sheet": {"receivables": 4.5, "inventory": 0, "lt_eqt_invest": 5.0,
                    "total_assets": 90.0, "total_liabilities": 27.0,
                    "accounts_payable": 2.8, "notes_payable": 0.9,
                    "contract_liab": 0, "advance_receipts": 0,
                    "st_borrow": 5.0, "lt_borrow": 10.0, "bonds_payable": 0, "noncurrent_liab_due_in_1y": 0},
                "cashflow": {"operating_cf": 28.0, "fcf": 18.0, "depr_amort": 9.0, "finan_exp": 1.2,
                             "capex": 4.0, "acq_subsidiary": 0, "dividend_paid_cf": 9.0},
            },
            {
                "year": 2023, "income": {"revenue": 80.0, "net_profit": 15.0, "gross_margin": 55.0, "fin_exp": 1.5, "operate_cost": 32.0},
                "balance_sheet": {"receivables": 4.0, "inventory": 0, "lt_eqt_invest": 5.0,
                    "total_assets": 80.0, "total_liabilities": 24.0,
                    "accounts_payable": 2.5, "notes_payable": 0.8,
                    "contract_liab": 0, "advance_receipts": 0,
                    "st_borrow": 5.0, "lt_borrow": 10.0, "bonds_payable": 0, "noncurrent_liab_due_in_1y": 0},
                "cashflow": {"operating_cf": 25.0, "fcf": 15.0, "depr_amort": 8.0, "finan_exp": 1.5,
                             "capex": 3.0, "acq_subsidiary": 0, "dividend_paid_cf": 8.0},
            },
            {
                "year": 2022, "income": {"revenue": 70.0, "net_profit": 13.0, "gross_margin": 53.0, "fin_exp": 1.3, "operate_cost": 28.0},
                "balance_sheet": {"receivables": 3.5, "inventory": 0, "lt_eqt_invest": 5.0,
                    "total_assets": 70.0, "total_liabilities": 21.0,
                    "accounts_payable": 2.2, "notes_payable": 0.7,
                    "contract_liab": 0, "advance_receipts": 0,
                    "st_borrow": 5.0, "lt_borrow": 10.0, "bonds_payable": 0, "noncurrent_liab_due_in_1y": 0},
                "cashflow": {"operating_cf": 23.0, "fcf": 13.0, "depr_amort": 7.0, "finan_exp": 1.3,
                             "capex": 3.0, "acq_subsidiary": 0, "dividend_paid_cf": 7.0},
            },
            {
                "year": 2021, "income": {"revenue": 60.0, "net_profit": 11.0, "gross_margin": 50.0, "fin_exp": 1.0, "operate_cost": 24.0},
                "balance_sheet": {"receivables": 3.0, "inventory": 0, "lt_eqt_invest": 5.0,
                    "total_assets": 60.0, "total_liabilities": 18.0,
                    "accounts_payable": 2.0, "notes_payable": 0.5,
                    "contract_liab": 0, "advance_receipts": 0,
                    "st_borrow": 5.0, "lt_borrow": 10.0, "bonds_payable": 0, "noncurrent_liab_due_in_1y": 0},
                "cashflow": {"operating_cf": 20.0, "fcf": 10.0, "depr_amort": 6.0, "finan_exp": 1.0,
                             "capex": 2.0, "acq_subsidiary": 0, "dividend_paid_cf": 6.0},
            },
        ],
        "dividend_history": [
            # v0.5.3: total_dividend 归一化后为亿元
            {"year": 2025, "dividend_per_share": 0.8, "total_dividend": 80.0},
            {"year": 2024, "dividend_per_share": 0.75, "total_dividend": 75.0},
            {"year": 2023, "dividend_per_share": 0.7, "total_dividend": 70.0},
        ],
        "repurchase_history": [],
    }


# ════════════════════════════════════════════════════════════════════
# SPEC: Screener — 条件数量
# ════════════════════════════════════════════════════════════════════

class TestScreenerSpec:
    def test_no_opcf_to_netprofit_field(self):
        """SPEC Step1: ocf_to_netprofit 已从 ScreenerResult 移除"""
        assert "opcf_to_netprofit" not in ScreenerResult.__dataclass_fields__

    def test_opcf_not_in_fail_stats(self):
        """SPEC Step1: fail_opcf 已从 ScreenerStats 移除"""
        from app.strategies.turtle.screener import ScreenerStats
        assert "fail_opcf" not in ScreenerStats.__dataclass_fields__

    def test_opcf_not_in_summary_output(self):
        """SPEC Step1: get_fail_summary 不再包含 '经营CF/净利润' 行"""
        from app.strategies.turtle.screener import ScreenerStats
        screener = TurtleScreener()
        stats = ScreenerStats(total_input=100, passed=5)
        summary = screener.get_fail_summary(stats)
        assert "经营CF" not in summary

    def test_candidate_count_warning(self, capsys, caplog):
        """SPEC Step1 L127: 候选池 < 50 应输出告警"""
        from app.strategies.turtle.screener import ScreenerStats
        screener = TurtleScreener()
        stock = {
            "ts_code": "600001.SH", "name": "测试", "industry": "食品饮料",
            "list_date": "20100101", "total_mv": 200.0,
            "pe": 15.0, "pb": 2.0, "roe": 12.0, "dividend_yield": 3.0,
            "gross_margin": 40.0, "debt_ratio": 30.0,
        }
        stocks = [stock] * 5
        import logging
        with caplog.at_level(logging.WARNING):
            screener.screen(stocks)
        assert "候选池偏小" in caplog.text


# ════════════════════════════════════════════════════════════════════
# SPEC: Coordinator — 数据校验
# ════════════════════════════════════════════════════════════════════

class TestCoordinatorValidation:
    def test_validate_raw_data_valid(self, temp_cache_dir, valid_raw_data):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        assert coordinator._validate_raw_data(valid_raw_data, "600900.SH") is True

    def test_validate_raw_data_insufficient_financials(self, temp_cache_dir, valid_raw_data):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        data = dict(valid_raw_data)
        data["annual_financials"] = data["annual_financials"][:2]
        assert coordinator._validate_raw_data(data, "600001.SH") is False

    def test_validate_raw_data_missing_revenue(self, temp_cache_dir, valid_raw_data):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        data = dict(valid_raw_data)
        for f in data["annual_financials"]:
            del f["income"]["revenue"]
        assert coordinator._validate_raw_data(data, "600002.SH") is False

    def test_validate_raw_data_missing_total_mv(self, temp_cache_dir, valid_raw_data):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        data = dict(valid_raw_data)
        data["basic_info"]["total_mv"] = 0.0
        assert coordinator._validate_raw_data(data, "600003.SH") is False


# ════════════════════════════════════════════════════════════════════
# SPEC: candidate_pool.yaml 输出
# ════════════════════════════════════════════════════════════════════

class TestCandidatePoolOutput:
    def test_write_candidate_pool_creates_file(self, temp_cache_dir, sample_candidates):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        coordinator._write_candidate_pool(sample_candidates)
        pool_path = temp_cache_dir / "candidate_pool.yaml"
        assert pool_path.exists()
        with open(pool_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert len(data) == len(sample_candidates)
        assert data[0]["ts_code"] == sample_candidates[0].ts_code


# ════════════════════════════════════════════════════════════════════
# SPEC: Coordinator — 拉取终止
# ════════════════════════════════════════════════════════════════════

class TestFetchTermination:
    """验证 SPEC Step2 L153: 拉取成功率 < 90% 终止"""

    @pytest.mark.asyncio
    async def test_low_fetch_rate_terminates(self, temp_cache_dir, sample_candidates):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        with patch.object(coordinator, "_validate_raw_data", return_value=True):
            def fake_fetch(ts_codes, force=False, name_map=None):
                from app.services.data_fetcher import FetchStats
                stats = FetchStats(total=len(ts_codes))
                stats.success = 1
                stats.failed = len(ts_codes) - 1
                stats.failed_codes = ts_codes[1:]
                return stats

            with patch("app.services.data_fetcher.DataFetcher") as mock_cls:
                mock_f = Mock()
                mock_f.fetch_candidate_data.side_effect = fake_fetch
                mock_cls.return_value = mock_f
                stocks = [
                    {"ts_code": c.ts_code, "name": c.name, "industry": c.industry,
                     "list_date": c.list_date, "total_mv": c.total_mv,
                     "pe": c.pe, "pb": c.pb, "roe": c.roe,
                     "dividend_yield": c.dividend_yield,
                     "gross_margin": c.gross_margin, "debt_ratio": c.debt_ratio}
                    for c in sample_candidates
                ]
                pool = await coordinator.run_full_refresh(stocks=stocks, fetch_data=True)
                assert pool == []
                assert coordinator.ctx.state.value == "error"


# ════════════════════════════════════════════════════════════════════
# SPEC: Coordinator — Step Results 记录
# ════════════════════════════════════════════════════════════════════

class TestStepResultsRecording:
    """ADR-0003: 每个步骤应有 StepResult 记录"""

    @pytest.mark.asyncio
    async def test_step_results_recorded(self, temp_cache_dir, sample_candidates):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        with patch.object(coordinator, "_validate_raw_data", return_value=True):
            def fake_fetch(ts_codes, force=False, name_map=None):
                from app.services.data_fetcher import FetchStats
                stats = FetchStats(total=len(ts_codes))
                stats.success = len(ts_codes)
                return stats

            with patch("app.services.data_fetcher.DataFetcher") as mock_cls:
                mock_f = Mock()
                mock_f.fetch_candidate_data.side_effect = fake_fetch
                mock_cls.return_value = mock_f

                stocks = [
                    {"ts_code": c.ts_code, "name": c.name, "industry": c.industry,
                     "list_date": c.list_date, "total_mv": c.total_mv,
                     "pe": c.pe, "pb": c.pb, "roe": c.roe,
                     "dividend_yield": c.dividend_yield,
                     "gross_margin": c.gross_margin, "debt_ratio": c.debt_ratio}
                    for c in sample_candidates
                ]

                def fake_yaml_load(f):
                    return {
                        "meta": {"ts_code": "600000.SH", "name": "测试股0", "data_completeness": "full"},
                        "basic_info": {"total_mv": 500, "industry": "食品饮料", "list_date": "20100101"},
                        "annual_financials": [
                            {
                                "year": yr, "income": {"revenue": 100.0, "net_profit": 20.0, "fin_exp": 1.0},
                                "balance_sheet": {"receivables": 5.0, "inventory": 0, "lt_eqt_invest": 0},
                                "cashflow": {"operating_cf": 30.0, "fcf": 20.0, "depr_amort": 10.0,
                                             "finan_exp": 1.0, "capex": 5.0, "acq_subsidiary": 0},
                            }
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "dividend_history": [
                            {"year": yr, "dividend_per_share": 0.8, "total_dividend": 80.0}
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "repurchase_history": [],
                    }

                raw_dir = temp_cache_dir / sample_candidates[0].ts_code
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / "raw_data.yaml").touch()

                with patch("builtins.open", create=True):
                    with patch.object(yaml, "safe_load", side_effect=fake_yaml_load):
                        await coordinator.run_full_refresh(stocks=stocks, fetch_data=True)

        step_names = [sr.step_name for sr in coordinator.ctx.step_results]
        assert "screener" in step_names
        assert "data_fetch" in step_names
        assert "cash_quality_gate" in step_names
        assert "pr_gate" in step_names


# ════════════════════════════════════════════════════════════════════
# SPEC v0.3.0: 软门判定 (CQ/PR 标记不淘汰)
# ════════════════════════════════════════════════════════════════════

class TestSoftGateBehavior:
    """v0.3.0: CQ/PR 改为软门，所有计算完成的股票都应入池"""

    def _make_mock_raw(self, ts_code, revenue=100.0, net_profit=20.0, op_cf=30.0):
        return {
            "meta": {"ts_code": ts_code, "name": "测试", "data_completeness": "full"},
            "basic_info": {"total_mv": 500, "industry": "食品饮料", "list_date": "20100101"},
            "annual_financials": [
                {
                    "year": yr,
                    "income": {"revenue": revenue, "net_profit": net_profit, "fin_exp": 1.0},
                    "balance_sheet": {"receivables": 5.0, "inventory": 0, "lt_eqt_invest": 0},
                    "cashflow": {"operating_cf": op_cf, "fcf": op_cf * 0.5, "depr_amort": 10.0,
                                 "finan_exp": 1.0, "capex": 5.0, "acq_subsidiary": 0},
                }
                for yr in [2025, 2024, 2023, 2022, 2021]
            ],
            "dividend_history": [
                {"year": yr, "dividend_per_share": 0.8, "total_dividend": 80.0}
                for yr in [2025, 2024, 2023, 2022, 2021]
            ],
            "repurchase_history": [],
        }

    @pytest.mark.asyncio
    async def test_cq_fail_stock_still_in_pool(self, temp_cache_dir, sample_candidates):
        """v0.3.0: CQ未通过的股票仍应在股池中（标记不淘汰）"""
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)

        with patch.object(coordinator, "_validate_raw_data", return_value=True):
            stocks_for_coordinator = [
                {"ts_code": c.ts_code, "name": c.name, "industry": c.industry,
                 "list_date": c.list_date, "total_mv": c.total_mv,
                 "pe": c.pe, "pb": c.pb, "roe": c.roe,
                 "dividend_yield": c.dividend_yield,
                 "gross_margin": c.gross_margin, "debt_ratio": c.debt_ratio}
                for c in sample_candidates[:1]  # 只测1只
            ]

            # CQ 会失败: OCF/NetProfit = 0.5 → dim1 fails
            def fake_yaml_load(f):
                return self._make_mock_raw(
                    "600000.SH", revenue=100.0, net_profit=100.0, op_cf=50.0
                )

            raw_dir = temp_cache_dir / sample_candidates[0].ts_code
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "raw_data.yaml").touch()

            with patch("app.services.data_fetcher.DataFetcher") as mock_cls:
                mock_f = Mock()
                mock_f.fetch_candidate_data.return_value = Mock(
                    success_rate=100, total=1, success=1, failed=0, failed_codes=[]
                )
                mock_cls.return_value = mock_f

                with patch("builtins.open", create=True):
                    with patch.object(yaml, "safe_load", side_effect=fake_yaml_load):
                        pool = await coordinator.run_full_refresh(
                            stocks=stocks_for_coordinator, fetch_data=True,
                        )

            # v0.3.0: CQ虽失败，但股票仍在池中（软门）
            assert len(pool) == 1, f"软门应保留股票，实际池大小: {len(pool)}"
            assert "cq_passed" in pool[0], "池中应有cq_passed标记"
            assert "pr_passed" in pool[0], "池中应有pr_passed标记"
            assert "gate_summary" in pool[0], "池中应有gate_summary"

    @pytest.mark.asyncio
    async def test_pr_excluded_disposable_cash_negative(self, temp_cache_dir, sample_candidates):
        """v0.6.20: 可支配现金均值 ≤ 0 → 硬排除，不入股池"""
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)

        with patch.object(coordinator, "_validate_raw_data", return_value=True):
            stocks_for_coordinator = [
                {"ts_code": c.ts_code, "name": c.name, "industry": c.industry,
                 "list_date": c.list_date, "total_mv": c.total_mv,
                 "pe": c.pe, "pb": c.pb, "roe": c.roe,
                 "dividend_yield": c.dividend_yield,
                 "gross_margin": c.gross_margin, "debt_ratio": c.debt_ratio}
                for c in sample_candidates[:1]
            ]

            # 可支配现金为负：op_cf=5.0, capex=10.0, fin_exp=3.0
            # per year: 5 - 10 - 0 - 0 - 3 = -8 → 均值 = -8 < 0
            def fake_yaml_load(f):
                return {
                    "meta": {"ts_code": "600000.SH", "name": "测试股0", "data_completeness": "full"},
                    "basic_info": {"total_mv": 500, "industry": "食品饮料", "list_date": "20100101"},
                    "annual_financials": [
                        {
                            "year": yr,
                            "income": {"revenue": 100.0, "net_profit": 20.0, "fin_exp": 3.0},
                            "balance_sheet": {"receivables": 5.0, "inventory": 0, "lt_eqt_invest": 0},
                            "cashflow": {"operating_cf": 5.0, "fcf": -5.0, "depr_amort": 2.0,
                                         "finan_exp": 3.0, "capex": 10.0, "acq_subsidiary": 0},
                        }
                        for yr in [2025, 2024, 2023, 2022, 2021]
                    ],
                    "dividend_history": [
                        {"year": yr, "dividend_per_share": 0.5, "total_dividend": 50.0}
                        for yr in [2025, 2024, 2023, 2022, 2021]
                    ],
                    "repurchase_history": [],
                }

            raw_dir = temp_cache_dir / sample_candidates[0].ts_code
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "raw_data.yaml").touch()

            with patch("app.services.data_fetcher.DataFetcher") as mock_cls:
                mock_f = Mock()
                mock_f.fetch_candidate_data.return_value = Mock(
                    success_rate=100, total=1, success=1, failed=0, failed_codes=[]
                )
                mock_cls.return_value = mock_f

                with patch("builtins.open", create=True):
                    with patch.object(yaml, "safe_load", side_effect=fake_yaml_load):
                        pool = await coordinator.run_full_refresh(
                            stocks=stocks_for_coordinator, fetch_data=True,
                        )

            # v0.6.20: 可支配现金均值 ≤ 0 → 硬排除，不入股池
            assert len(pool) == 0, f"可支配现金为负应硬排除，实际池大小: {len(pool)}"

    @pytest.mark.asyncio
    async def test_pr_excluded_single_vs_multiple(self, temp_cache_dir, sample_candidates):
        """v0.6.20: 混合场景：正可支配现金保留，负可支配现金排除"""
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)

        with patch.object(coordinator, "_validate_raw_data", return_value=True):
            stocks_for_coordinator = [
                {"ts_code": c.ts_code, "name": c.name, "industry": c.industry,
                 "list_date": c.list_date, "total_mv": c.total_mv,
                 "pe": c.pe, "pb": c.pb, "roe": c.roe,
                 "dividend_yield": c.dividend_yield,
                 "gross_margin": c.gross_margin, "debt_ratio": c.debt_ratio}
                for c in sample_candidates[:2]
            ]

            call_count = [0]

            def two_stock_yaml_load(f):
                call_count[0] += 1
                if call_count[0] == 1:
                    # Stock 0: 正可支配现金 → 应保留
                    return {
                        "meta": {"ts_code": "600000.SH", "name": "测试股0", "data_completeness": "full"},
                        "basic_info": {"total_mv": 500, "industry": "食品饮料", "list_date": "20100101"},
                        "annual_financials": [
                            {
                                "year": yr,
                                "income": {"revenue": 100.0, "net_profit": 30.0, "fin_exp": 1.0},
                                "balance_sheet": {"receivables": 5.0, "inventory": 0, "lt_eqt_invest": 0},
                                "cashflow": {"operating_cf": 30.0, "fcf": 25.0, "depr_amort": 5.0,
                                             "finan_exp": 1.0, "capex": 5.0, "acq_subsidiary": 0},
                            }
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "dividend_history": [
                            {"year": yr, "dividend_per_share": 0.8, "total_dividend": 80.0}
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "repurchase_history": [],
                    }
                else:
                    # Stock 1: 负可支配现金 → 应排除
                    return {
                        "meta": {"ts_code": "600001.SH", "name": "测试股1", "data_completeness": "full"},
                        "basic_info": {"total_mv": 300, "industry": "化工原料", "list_date": "20100101"},
                        "annual_financials": [
                            {
                                "year": yr,
                                "income": {"revenue": 50.0, "net_profit": 5.0, "fin_exp": 3.0},
                                "balance_sheet": {"receivables": 10.0, "inventory": 0, "lt_eqt_invest": 0},
                                "cashflow": {"operating_cf": 5.0, "fcf": -5.0, "depr_amort": 2.0,
                                             "finan_exp": 3.0, "capex": 10.0, "acq_subsidiary": 0},
                            }
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "dividend_history": [
                            {"year": yr, "dividend_per_share": 0.3, "total_dividend": 30.0}
                            for yr in [2025, 2024, 2023, 2022, 2021]
                        ],
                        "repurchase_history": [],
                    }

            for c in sample_candidates[:2]:
                raw_dir = temp_cache_dir / c.ts_code
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / "raw_data.yaml").touch()

            with patch("app.services.data_fetcher.DataFetcher") as mock_cls:
                mock_f = Mock()
                mock_f.fetch_candidate_data.return_value = Mock(
                    success_rate=100, total=2, success=2, failed=0, failed_codes=[]
                )
                mock_cls.return_value = mock_f

                with patch("builtins.open", create=True):
                    with patch.object(yaml, "safe_load", side_effect=two_stock_yaml_load):
                        pool = await coordinator.run_full_refresh(
                            stocks=stocks_for_coordinator, fetch_data=True,
                        )

            # 只应保留正可支配现金的那只
            assert len(pool) == 1, f"混合场景应只保留1只，实际池大小: {len(pool)}"
            assert pool[0]["ts_code"] == "600000.SH", f"保留的应是正可支配现金股"


# ════════════════════════════════════════════════════════════════════
# SPEC v0.3.0: qrv_input.yaml 数据包结构
# ════════════════════════════════════════════════════════════════════

class TestQRVInputBuilder:
    """v0.3.0: Step 6 统一数据包构建"""

    @pytest.mark.asyncio
    async def test_qrv_input_contains_all_sections(self, temp_cache_dir, valid_raw_data):
        """qrv_input.yaml 应包含所有7个章节"""
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)

        # 准备缓存
        ts_code = "600900.SH"
        stock_dir = temp_cache_dir / ts_code
        stock_dir.mkdir(parents=True, exist_ok=True)

        # 写入 raw_data.yaml
        with open(stock_dir / "raw_data.yaml", "w", encoding="utf-8") as f:
            yaml.dump(valid_raw_data, f, allow_unicode=True)

        # 写入 computed.yaml (含CQ/PR结果)
        computed = {
            "meta": {"ts_code": ts_code, "name": "长江电力"},
            "cash_quality": {"overall_passed": True, "failed_dimensions": []},
            "penetration_return": {
                "disposable_cash": {"cv": 0.1, "cv_passed": True},
                "pr_result": {"pr": 5.0, "passed": True},
            },
        }
        with open(stock_dir / "computed.yaml", "w", encoding="utf-8") as f:
            yaml.dump(computed, f, allow_unicode=True)

        # 写入 candidate_pool.yaml
        pool_data = [{"ts_code": ts_code, "name": "长江电力", "industry": "电力"}]
        with open(temp_cache_dir / "candidate_pool.yaml", "w", encoding="utf-8") as f:
            yaml.dump(pool_data, f, allow_unicode=True)

        # 执行 _build_qrv_input
        qrv_path = await coordinator._build_qrv_input(ts_code)
        assert qrv_path is not None
        assert qrv_path.exists()

        with open(qrv_path, "r", encoding="utf-8") as f:
            qrv_input = yaml.safe_load(f)

        # 验证7个节都存在于 qrv_input
        required_sections = [
            "company_profile",
            "financial_data",
            "cq_results",
            "pr_results",
            "dividend_repurchase",
            "gate_summary",
            "websearch_results",  # 初始为空，Step7填充
        ]
        for section in required_sections:
            assert section in qrv_input, f"缺少章节: {section}"

        # 验证 company_profile 包含必要字段
        cp = qrv_input["company_profile"]
        assert cp["ts_code"] == ts_code
        assert "industry" in cp
        assert "total_mv" in cp

        # 验证 gate_summary 包含必要字段
        gs = qrv_input["gate_summary"]
        assert "screener" in gs
        assert "cash_quality" in gs
        assert "penetration_return" in gs

        # 验证 websearch_results 初始为空
        assert qrv_input["websearch_results"] == {}

    def test_qrv_input_websearch_append(self, temp_cache_dir, valid_raw_data):
        """测试 websearch_results 追加到 qrv_input.yaml"""
        ts_code = "600900.SH"
        stock_dir = temp_cache_dir / ts_code
        stock_dir.mkdir(parents=True, exist_ok=True)

        qrv_path = stock_dir / "qrv_input.yaml"
        qrv_data = {
            "meta": {"ts_code": ts_code},
            "company_profile": {"ts_code": ts_code, "name": "长江电力"},
            "websearch_results": {},
        }
        with open(qrv_path, "w", encoding="utf-8") as f:
            yaml.dump(qrv_data, f, allow_unicode=True)

        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        ws_data = {
            "q_websearch": {"description": "商模+护城河", "snippets": [{"type": "result", "content": "test"}]},
            "r1_websearch": {"description": "外部环境", "snippets": []},
        }
        coordinator._append_websearch_to_qrv_input(qrv_path, ws_data)

        with open(qrv_path, "r", encoding="utf-8") as f:
            updated = yaml.safe_load(f)

        assert "q_websearch" in updated["websearch_results"]
        assert "r1_websearch" in updated["websearch_results"]


# ════════════════════════════════════════════════════════════════════
# SPEC v0.3.0: QRV Agent 输出格式
# ════════════════════════════════════════════════════════════════════

class TestQRVAgentOutput:
    """v0.3.0: Step 8 QRV Agent 输出验证"""

    def test_qrv_agent_module_importable(self):
        """QRV Agent 模块可导入"""
        from app.strategies.turtle.qrv_agent import QRVAgent
        agent = QRVAgent()
        assert agent is not None
        assert agent.rule_version == "v2"

    def test_qrv_prompt_contains_qrv_framework(self, temp_cache_dir):
        """QRV prompt 包含 Q/R/V 三维度 (v4: 含 R4 重大事件与资本运作)"""
        from app.strategies.turtle.qrv_agent import QRVAgent
        agent = QRVAgent(cache_dir=temp_cache_dir)
        qrv_input = {
            "company_profile": {"name": "测试公司", "industry": "测试行业"},
            "financial_data": {},
            "cq_results": {"overall_passed": True},
            "pr_results": {"pr_result": {"pr": 5.0}},
            "dividend_repurchase": {},
            "gate_summary": {"screener": {"passed": True}},
            "websearch_results": {},
        }
        prompt = agent._build_prompt("测试公司", "000001.SZ", qrv_input)
        # v2 基础检查
        assert "商业模式" in prompt
        assert "护城河" in prompt
        assert "外部环境" in prompt
        assert "管理层" in prompt
        assert "估值" in prompt
        assert "000001.SZ" in prompt
        # v3 新增检查
        assert "生意本质" in prompt, "v3: 应含生意本质"
        assert "增长引擎" in prompt, "v3: 应含Q3增长引擎"
        assert "人才结构" in prompt, "v3: 应含人才结构"
        assert "data_sufficiency" in prompt, "v3: 应含data_sufficiency指引"
        # v4 新增检查
        assert "重大事件与资本运作" in prompt, "v4: 应含 R4 重大事件与资本运作"
        assert "extracted_facts" in prompt, "v4: 应含 extracted_facts 板块说明"
        assert "corporate_events" in prompt, "v4: 应含 corporate_events 引用"

    def test_llm_placeholder_when_no_key(self, temp_cache_dir):
        """LLM_API_KEY 未配置时返回占位结果"""
        from app.strategies.turtle.qrv_agent import QRVAgent
        agent = QRVAgent(cache_dir=temp_cache_dir)
        import asyncio
        result = asyncio.run(agent._call_llm("test prompt"))
        assert "markdown" in result
        assert "raw" in result
        assert "tokens" in result


# ════════════════════════════════════════════════════════════════════
# SPEC v0.3.0: 规则版本验证
# ════════════════════════════════════════════════════════════════════

class TestRuleVersion:
    """v0.3.0 规则版本应为 v2"""

    def test_coordinator_default_rule_version(self, temp_cache_dir):
        coordinator = TurtleCoordinator(cache_dir=temp_cache_dir)
        assert coordinator.rule_version == "v2"
        assert coordinator.ctx.rule_version == "v2"

    def test_qrv_rules_exist(self):
        """turtle_qrv.yaml 存在"""
        rules_dir = Path(__file__).parent.parent / "rules" / "v2" / "turtle_qrv.yaml"
        assert rules_dir.exists(), f"turtle_qrv.yaml 不存在于 {rules_dir}"

    def test_cq_pr_soft_gate_in_rules(self):
        """CQ/PR 规则文件标记为 soft"""
        # rules 在 backend/rules/v2/ 下
        rules_dir = Path(__file__).parent.parent / "rules" / "v2"

        cq_yaml = rules_dir / "turtle_cash_quality.yaml"
        with open(cq_yaml, "r", encoding="utf-8") as f:
            cq = yaml.safe_load(f)
        assert cq["gate_type"] == "soft", f"CQ gate_type 应为 soft，实际 {cq['gate_type']}"
        # v0.7.0: 8维度
        dim_ids = [d["id"] for d in cq["dimensions"]]
        assert len(dim_ids) == 8, f"CQ rules 应有 8 维度，实际 {len(dim_ids)}: {dim_ids}"
        assert "pass_condition" in cq
        assert cq["pass_condition"] == "all"

        pr_yaml = rules_dir / "turtle_pr.yaml"
        with open(pr_yaml, "r", encoding="utf-8") as f:
            pr_data = yaml.safe_load(f)
        assert pr_data["gate_type"] == "soft", f"PR gate_type 应为 soft，实际 {pr_data['gate_type']}"

    def test_cq_8dimensions_in_result(self):
        """v0.7.0: CashQualityResult 包含 dim6/7/8 字段"""
        from app.strategies.turtle.cash_quality import CashQualityResult
        result = CashQualityResult(ts_code="000001.SZ")
        # 验证字段存在
        assert hasattr(result, "dim6_passed")
        assert hasattr(result, "dim7_passed")
        assert hasattr(result, "dim8_passed")
        # 验证 failed_dimensions 包含 6/7/8
        result.dim6_passed = False
        assert 6 in result.failed_dimensions

    def test_cq_8dimensions_in_computed_format(self):
        """v0.7.0: to_computed_format 包含 dim6-8"""
        from app.strategies.turtle.cash_quality import CashQualityGate, CashQualityResult
        gate = CashQualityGate()
        result = CashQualityResult(ts_code="000001.SZ", overall_passed=True)
        fmt = gate.to_computed_format(result)
        assert "dimension_6_fcf_dividend_coverage" in fmt
        assert "dimension_7_supplier_squeeze" in fmt
        assert "dimension_8_interest_bearing_debt_trend" in fmt


# ════════════════════════════════════════════════════════════════════
# SPEC: DataFetcher — L0 缓存
# ════════════════════════════════════════════════════════════════════

class TestDataFetcherCache:
    def test_cache_path_configurable(self, temp_cache_dir):
        from app.services.data_fetcher import DataFetcher
        fetcher = DataFetcher(cache_dir=temp_cache_dir)
        cache_path = temp_cache_dir / "_stock_basic_cache.parquet"
        assert isinstance(cache_path, Path)

    def test_force_flag_bypasses_cache(self, temp_cache_dir, monkeypatch):
        from app.services.data_fetcher import DataFetcher
        cache_path = temp_cache_dir / "_stock_basic_cache.parquet"
        old_df = pd.DataFrame({"ts_code": ["000001.SZ"], "name": ["old"]})
        old_df.attrs["cache_date"] = "20000101"
        old_df.to_parquet(cache_path, index=False)

        class MockClient:
            def get_stock_basic(self, list_status=""):
                return pd.DataFrame({
                    "ts_code": ["000001.SZ", "000002.SZ"],
                    "name": ["平安银行", "万科A"],
                    "industry": ["银行", "房地产"],
                    "list_date": ["19910403", "19910129"],
                })
            def call(self, api, **kwargs):
                if api == "daily_basic":
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ", "000002.SZ"],
                        "total_mv": [2e6, 1.5e6], "circ_mv": [1e6, 8e5],
                        "pe": [5.0, 8.0], "pb": [0.7, 1.2],
                        "dv_ratio": [5.0, 3.0], "total_share": [1e6, 5e5],
                    })
                if api == "fina_indicator":
                    return pd.DataFrame({
                        "ts_code": ["000001.SZ", "000002.SZ"],
                        "end_date": ["20251231", "20251231"],
                        "roe_yearly": [10.0, 8.0],
                        "grossprofit_margin": [60.0, 25.0],
                        "debt_to_assets": [90.0, 75.0],
                    })
                return pd.DataFrame()

        fetcher = DataFetcher(cache_dir=temp_cache_dir, client=MockClient())
        result = fetcher.fetch_stock_basic(force=True)
        assert len(result) == 2
        assert "roe" in result.columns


# ════════════════════════════════════════════════════════════════════
# SPEC: v0.7.3 R4 重大事件与资本运作
# ════════════════════════════════════════════════════════════════════

class TestR4CorporateEvents:
    """v0.7.3: QRV prompt 含 R4 模块 + data_sufficiency 含 R4"""

    def test_qrv_prompt_contains_r4(self):
        """turtle_qrv.yaml prompt 含 R4 重大事件与资本运作"""
        rules_dir = Path(__file__).parent.parent / "rules" / "v2" / "turtle_qrv.yaml"
        with open(rules_dir, "r", encoding="utf-8") as f:
            content = f.read()
        assert "R4 重大事件与资本运作" in content, "turtle_qrv.yaml prompt 必须含 R4"
        assert "corporate_events" in content, "prompt 必须引用 extracted_facts.corporate_events"
        assert "定增" in content, "prompt 必须提及定增"
        assert "并购" in content, "prompt 必须提及并购"

    def test_qrv_rules_has_r4_module(self):
        """turtle_qrv.yaml analysis_framework 含 r4_corporate_events"""
        rules_dir = Path(__file__).parent.parent / "rules" / "v2" / "turtle_qrv.yaml"
        with open(rules_dir, "r", encoding="utf-8") as f:
            qrv = yaml.safe_load(f)
        framework = qrv.get("analysis_framework", {})
        resilience = framework.get("resilience", {})
        modules = resilience.get("modules", [])
        r4_ids = [m["id"] for m in modules if "r4" in m.get("id", "")]
        assert len(r4_ids) >= 1, f"analysis_framework.resilience 必须包含 r4 模块, 现有: {[m['id'] for m in modules]}"

    def test_data_sufficiency_has_r4(self):
        """data_summarizer.py data_sufficiency 含 R4_corporate_events"""
        ds_path = Path(__file__).parent.parent / "app" / "strategies" / "turtle" / "data_summarizer.py"
        with open(ds_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "R4_corporate_events" in content, "data_summarizer 的 data_sufficiency 必须包含 R4_corporate_events"

    def test_websearch_extractor_has_corporate_events(self):
        """websearch_extractor.py 含 _extract_corporate_events 方法"""
        from app.strategies.turtle.websearch_extractor import WebSearchExtractor
        extractor = WebSearchExtractor()
        assert hasattr(extractor, "_extract_corporate_events"), "WebSearchExtractor 必须有 _extract_corporate_events"
        # 验证 extract() 返回包含 corporate_events key
        result = extractor.extract({})
        assert "corporate_events" in result, "extract() 必须包含 corporate_events key"
        assert isinstance(result["corporate_events"], list), "corporate_events 应为 list"

    def test_qrv_input_schema_has_extracted_facts(self):
        """turtle_qrv.yaml input_schema 含 extracted_facts"""
        rules_dir = Path(__file__).parent.parent / "rules" / "v2" / "turtle_qrv.yaml"
        with open(rules_dir, "r", encoding="utf-8") as f:
            qrv = yaml.safe_load(f)
        sections = qrv.get("input_schema", {}).get("sections", [])
        section_names = [s.get("name", "") for s in sections]
        assert "extracted_facts" in section_names, f"input_schema 必须包含 extracted_facts 段, 现有: {section_names}"

    def test_scorecard_has_r4(self):
        """turtle_qrv.yaml 综合打分卡含 R4 行"""
        rules_dir = Path(__file__).parent.parent / "rules" / "v2" / "turtle_qrv.yaml"
        with open(rules_dir, "r", encoding="utf-8") as f:
            content = f.read()
        assert "R4 重大事件与资本运作" in content, "综合打分卡必须包含 R4 行"
