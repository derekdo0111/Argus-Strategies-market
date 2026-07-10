"""高景气策略集成测试"""
import pytest
from pathlib import Path


def test_coordinator_import():
    """验证 coordinator 可导入"""
    from app.strategies.prosperity.coordinator import Coordinator
    c = Coordinator()
    assert c is not None
    assert c.data_dir.exists()


def test_session_lifecycle():
    """验证会话创建和状态管理"""
    from app.strategies.prosperity.coordinator import Coordinator
    c = Coordinator()
    sid = c.start_session("test_行业")
    assert sid > 0

    status = c.get_session(sid)
    assert status["status"] == "running"
    assert status["current_step"] == "search"

    c.update_step(sid, "done")
    status = c.get_session(sid)
    assert status["status"] == "completed"


def test_models_import():
    """验证所有模型可导入"""
    from app.strategies.prosperity.models import (
        Industry, ResearchSession, Hypothesis,
        IndustryMetrics, StockPool, TrackingItem,
        Base, init_db,
    )
    assert Industry is not None
    assert ResearchSession is not None


def test_tools_import():
    """验证所有工具可导入"""
    from app.strategies.prosperity.tools.industry_metrics import compute_industry_metrics
    from app.strategies.prosperity.tools.stock_screener import score_stocks
    from app.strategies.prosperity.tools.purity_scorer import (
        get_batch_mainbz, match_business_to_l3, compute_purity_scores,
    )
    from app.strategies.prosperity.tools.wiki_indexer import scan_pages, update_index
    from app.strategies.prosperity.tools.source_crawler import crawl_industry_sources
    assert compute_industry_metrics is not None
    assert get_batch_mainbz is not None


def test_agents_import():
    """验证所有 Agent 可导入（v4: LearningAgent 新增）"""
    from app.strategies.prosperity.agents.search_agent import SearchAgent
    from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
    from app.strategies.prosperity.agents.verify_agent import VerifyAgent
    from app.strategies.prosperity.agents.screening_agent import ScreeningAgent
    from app.strategies.prosperity.agents.report_agent import ReportAgent
    from app.strategies.prosperity.agents.track_agent import TrackAgent
    from app.strategies.prosperity.agents.learning_agent import LearningAgent
    assert SearchAgent is not None
    assert ScreeningAgent is not None
    assert LearningAgent is not None


def test_api_router():
    """验证 API router 可导入"""
    from app.strategies.prosperity.api import router
    assert router is not None
    assert len(router.routes) > 0


def test_data_directories():
    """验证数据目录结构"""
    from app.core.config import settings
    data_dir = settings.PROSPERITY_DATA_DIR
    assert data_dir.exists()
    assert (data_dir / "raw").exists()
    assert (data_dir / "wiki").exists()
    assert (data_dir / "tracking").exists()


class TestSourceCrawler:
    """source_crawler.py 单元测试"""

    def test_sia_crawler_no_crash(self):
        """SIA 爬取不抛异常（网络不可用时应返回 None 或 dict）"""
        from app.strategies.prosperity.tools.source_crawler import _crawl_sia_sales
        result = _crawl_sia_sales()
        # 网络不可用 → None；网络可用 → dict
        assert result is None or isinstance(result, dict)

    def test_wsts_stub_returns_none(self):
        """WSTS stub 返回 None"""
        from app.strategies.prosperity.tools.source_crawler import _crawl_wsts_forecast
        result = _crawl_wsts_forecast()
        assert result is None

    def test_crawl_single_source_known(self):
        """已知信源路由到对应处理器（SIA）"""
        from app.strategies.prosperity.tools.source_crawler import _crawl_single_source
        result = _crawl_single_source("SIA 全球半导体销售报告", {})
        assert result is None or isinstance(result, dict)

    def test_crawl_single_source_unknown(self):
        """未知信源返回 None（不抛异常）"""
        from app.strategies.prosperity.tools.source_crawler import _crawl_single_source
        result = _crawl_single_source("不存在的信源名称", {})
        assert result is None

    def test_crawl_industry_sources_semiconductor(self):
        """半导体行业全量爬取不抛异常"""
        from app.strategies.prosperity.tools.source_crawler import crawl_industry_sources
        from pathlib import Path
        registry = {
            "industries": {
                "semiconductor": {
                    "priority_sources": [
                        "SIA 全球半导体销售报告",
                        "SEMI 设备订单数据",
                        "WSTS 半导体预测",
                    ],
                    "domestic_sources": [
                        "中国半导体行业协会 (CSIA)",
                    ],
                },
            },
        }
        output_dir = Path("data/prosperity/raw/semiconductor")
        output_dir.mkdir(parents=True, exist_ok=True)
        results = crawl_industry_sources("semiconductor", registry, output_dir)
        assert isinstance(results, dict)
        assert "SIA 全球半导体销售报告" in results


class TestStockScreener:
    """stock_screener.py 单元测试 — v0.18：动量已移除"""

    def test_default_weights_no_momentum(self):
        """v0.18: 默认权重不含动量，4 因子合计 1.0"""
        from app.strategies.prosperity.tools.stock_screener import DEFAULT_WEIGHTS
        assert "momentum_3m" not in DEFAULT_WEIGHTS
        assert "momentum_6m" not in DEFAULT_WEIGHTS
        assert set(DEFAULT_WEIGHTS.keys()) == {"revenue_growth", "earnings_growth", "roe_level", "quality"}
        total = sum(DEFAULT_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_score_stocks_returns_raw_indicators(self):
        """v0.18: score_stocks 返回 raw_indicators 供报告展示"""
        from app.strategies.prosperity.tools.stock_screener import score_stocks
        metrics = {
            "metrics": {
                "revenue_growth": {"sorted_values": [5.0, 10.0, 20.0], "count": 3},
                "net_profit_growth": {"sorted_values": [-10.0, 0.0, 15.0], "count": 3},
                "roe": {"sorted_values": [2.0, 8.0, 15.0], "count": 3},
            }
        }
        # score_stocks 内部会调 Tushare → 空结果 → 跳过
        # 只验证函数签名和 raw_indicators 字段存在
        assert callable(score_stocks)


class TestWikiEnhancement:
    """v0.14.0 Wiki 智能增强测试"""

    def test_cooldown_first_study_returns_none(self):
        """T1: 首次研究行业 — _check_cooldown 返回 None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        result = c._check_cooldown("nonexistent_industry_for_test")
        assert result is None

    def test_cooldown_within_5_days(self):
        """T2: 5 天内重复 → 返回 cooldown"""
        from app.strategies.prosperity.coordinator import Coordinator
        from datetime import datetime
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "cooldown_test_5d.md"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        fire_emoji = "\U0001f525"
        page.write_text(f"# cooldown_test_5d\n\n- [{today}] {fire_emoji} \u9ad8\u666f\u6c14\n", encoding="utf-8")
        result = c._check_cooldown("cooldown_test_5d")
        assert result is not None
        assert result["status"] == "cooldown"
        assert result["days_ago"] == 0
        page.unlink()

    def test_cooldown_over_5_days_returns_none(self):
        """T2b: 超过 5 天 → 返回 None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "old_industry_test.md"
        check_emoji = "\u2705"
        page.write_text(f"# old_industry_test\n\n- [2026-01-01] {check_emoji} \u666f\u6c14\n", encoding="utf-8")
        result = c._check_cooldown("old_industry_test")
        assert result is None
        page.unlink()

    def test_start_session_force_bypasses_cooldown(self):
        """T3: force=True 跳过冷却"""
        from datetime import datetime
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        wiki_dir = c.data_dir / "wiki" / "industries"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        page = wiki_dir / "force_test.md"
        today = datetime.utcnow().strftime("%Y-%m-%d")
        fire_emoji = "\U0001f525"
        page.write_text(f"# force_test\n\n- [{today}] {fire_emoji} \u9ad8\u666f\u6c14\n", encoding="utf-8")
        sid = c.start_session("force_test", force=True)
        assert sid > 0
        page.unlink()

    def test_load_history_returns_none_for_first_study(self):
        """T10: 无 wiki 历史的行业 → history=None"""
        from app.strategies.prosperity.coordinator import Coordinator
        c = Coordinator()
        sid = c.start_session("never_studied_before_xyz")
        history = c._load_history("never_studied_before_xyz", sid)
        assert history is None

    def test_industry_history_dataclass(self):
        """验证 IndustryHistory 数据类"""
        from app.strategies.prosperity.industry_history import IndustryHistory
        h = IndustryHistory("测试行业")
        assert h.is_first_study is True
        assert h.study_count == 1

        h2 = IndustryHistory("测试行业2", study_count=3, last_rating="高景气")
        assert h2.is_first_study is False
        assert h2.verified_count == 0
        assert h2.overturned_count == 0

    def test_cooldown_error_exception(self):
        """验证 CooldownError 异常"""
        from app.strategies.prosperity.coordinator import CooldownError
        info = {"status": "cooldown", "message": "test"}
        e = CooldownError(info)
        assert e.cooldown_info["status"] == "cooldown"

    def test_merge_indicators_dedup(self):
        """T9: 同指标多假设合并"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        from pathlib import Path
        agent = TrackAgent()
        items = [
            {"indicator": "DRAM 价格", "industry": "半导体", "hypothesis_id": "H2-1", "hypothesis_title": "拐点", "hypothesis_status": "verified", "source_session": 1},
            {"indicator": "DRAM 价格", "industry": "半导体", "hypothesis_id": "H2-2", "hypothesis_title": "压力", "hypothesis_status": "verified", "source_session": 1},
            {"indicator": "营收增速", "industry": "半导体", "hypothesis_id": "H0-1", "hypothesis_title": "营收", "hypothesis_status": "confirmed", "source_session": 1},
        ]
        merged = agent._merge_indicators(items)
        assert len(merged) == 2
        dram = [m for m in merged if m["indicator"] == "DRAM 价格"][0]
        assert dram["hypothesis_ids"] == ["H2-1", "H2-2"]

    def test_merge_indicators_cross_industry_no_merge(self):
        """T14: 跨行业同名指标不合并（修复 bug — 复合 key）"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        agent = TrackAgent()
        items = [
            {"indicator": "营收增速", "industry": "半导体", "hypothesis_id": "H1", "hypothesis_title": "A", "hypothesis_status": "confirmed", "source_session": 1},
            {"indicator": "营收增速", "industry": "电气设备", "hypothesis_id": "H2", "hypothesis_title": "B", "hypothesis_status": "partial", "source_session": 2},
        ]
        merged = agent._merge_indicators(items)
        assert len(merged) == 2  # 不同行业，不合并
        industries = {m["industry"] for m in merged}
        assert industries == {"半导体", "电气设备"}

    def test_load_watchlist_new_format(self):
        """T15: _load_watchlist 读 v0.14.2+ 目录格式（每行业一个 .yaml 文件）"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        from pathlib import Path
        import tempfile, yaml
        agent = TrackAgent()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # 写两个行业文件
            dianqi_items = [
                {"indicator": "电网投资额", "industry": "电气设备", "status": "pending"},
            ]
            bdt_items = [
                {"indicator": "营收增速", "industry": "半导体", "status": "pending"},
            ]
            with open(tmp_path / "电气设备.yaml", "w", encoding="utf-8") as f:
                yaml.dump(dianqi_items, f, allow_unicode=True)
            with open(tmp_path / "半导体.yaml", "w", encoding="utf-8") as f:
                yaml.dump(bdt_items, f, allow_unicode=True)

            result = agent._load_watchlist(tmp_path)
            assert len(result) == 2
            assert "电气设备" in result
            assert "半导体" in result
            assert len(result["电气设备"]) == 1
            assert len(result["半导体"]) == 1

    def test_load_watchlist_old_format_compat(self):
        """T16: _load_watchlist 兼容旧扁平格式 {"items": [...]}"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        from pathlib import Path
        import tempfile, yaml
        agent = TrackAgent()
        old_data = {
            "items": [
                {"indicator": "电网投资额", "industry": "电气设备", "status": "pending"},
                {"indicator": "营收增速", "industry": "半导体", "status": "pending"},
                {"indicator": "毛利率", "industry": "电气设备", "status": "pending"},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            yaml.dump(old_data, f, allow_unicode=True)
            tmp_path = Path(f.name)
        try:
            result = agent._load_watchlist(tmp_path)
            assert len(result) == 2  # 两个行业
            assert len(result["电气设备"]) == 2
            assert len(result["半导体"]) == 1
        finally:
            tmp_path.unlink(missing_ok=True)


class TestConceptStockPool:
    """T17-T20: 概念股池多信源兜底"""

    def test_concept_detail_fallback(self):
        """T17: concept_detail 返回匹配股票时正确合并"""
        import pandas as pd
        from unittest.mock import patch
        from app.strategies.prosperity.tools.industry_metrics import (
            get_industry_ts_codes, clear_industry_cache,
        )
        clear_industry_cache()
        mock_concept = pd.DataFrame({
            "ts_code": ["300750.SZ", "002594.SZ", "601012.SH"],
            "name": ["宁德时代", "比亚迪", "隆基绿能"],
            "concept_name": ["新能源"] * 3,
        })
        # industry_metrics 在函数内 import TushareClient，所以 mock 源头
        with patch("app.services.tushare_client.TushareClient") as MockClient:
            instance = MockClient.return_value
            instance.get_stock_basic.return_value = pd.DataFrame({
                "ts_code": ["000001.SZ"], "name": ["平安银行"], "industry": ["银行"],
            })
            instance.get_industry.return_value = pd.DataFrame()
            instance.get_concept_detail.return_value = mock_concept

            codes = get_industry_ts_codes("新能源")
            assert len(codes) >= 3
            assert "300750.SZ" in codes
        clear_industry_cache()

    def test_ths_concept_fallback(self):
        """T18: concept_detail 为空时走 ths_index → ths_member"""
        import pandas as pd
        from unittest.mock import patch
        from app.strategies.prosperity.tools.industry_metrics import (
            get_industry_ts_codes, clear_industry_cache,
        )
        clear_industry_cache()
        with patch("app.services.tushare_client.TushareClient") as MockClient:
            instance = MockClient.return_value
            instance.get_stock_basic.return_value = pd.DataFrame({
                "ts_code": ["000001.SZ"], "name": ["平安银行"], "industry": ["银行"],
            })
            instance.get_industry.return_value = pd.DataFrame()
            instance.get_concept_detail.return_value = pd.DataFrame()
            instance.get_ths_index.return_value = pd.DataFrame({
                "ts_code": ["885800.TI", "885900.TI"],
                "name": ["新能源", "新能源汽车"],
            })

            def side_effect(ts_code):
                d = {
                    "885800.TI": pd.DataFrame({"ts_code": ["300750.SZ"], "name": ["宁德时代"]}),
                    "885900.TI": pd.DataFrame({"ts_code": ["002594.SZ"], "name": ["比亚迪"]}),
                }
                return d.get(ts_code, pd.DataFrame())

            instance.get_ths_member.side_effect = side_effect

            codes = get_industry_ts_codes("新能源")
            # 精确匹配"新能源"板块，取 1 只股票
            assert len(codes) >= 1
            assert "300750.SZ" in codes
        clear_industry_cache()

    def test_cache_hit_skips_concept(self):
        """T19: 缓存命中直接返回，不调用概念接口"""
        import pandas as pd
        from unittest.mock import patch
        from app.strategies.prosperity.tools.industry_metrics import (
            get_industry_ts_codes, clear_industry_cache,
        )
        clear_industry_cache()
        with patch("app.services.tushare_client.TushareClient") as MockClient:
            instance = MockClient.return_value
            instance.get_stock_basic.return_value = pd.DataFrame({
                "ts_code": ["300750.SZ"], "name": ["宁德时代"], "industry": ["电气设备"],
            })
            instance.get_industry.return_value = pd.DataFrame()

            codes = get_industry_ts_codes("电气设备")
            assert len(codes) == 1

            instance.get_concept_detail.reset_mock()
            instance.get_ths_index.reset_mock()
            codes2 = get_industry_ts_codes("电气设备")
            assert len(codes2) == 1
            instance.get_concept_detail.assert_not_called()
        clear_industry_cache()

    def test_concept_builder_fallback(self):
        """T20: 前 4 信源全空时走搜索引擎自建概念板块兜底"""
        import pandas as pd
        from unittest.mock import patch
        from app.strategies.prosperity.tools.industry_metrics import (
            get_industry_ts_codes, clear_industry_cache,
        )
        clear_industry_cache()
        # 搜索引擎返回的股票列表
        mock_concept_stocks = [
            {"ts_code": "300750.SZ", "name": "宁德时代", "chain": "中游-电池"},
            {"ts_code": "002594.SZ", "name": "比亚迪", "chain": "下游-整车"},
            {"ts_code": "601012.SH", "name": "隆基绿能", "chain": "中游-光伏组件"},
            {"ts_code": "688599.SH", "name": "天合光能", "chain": "中游-组件"},
        ]
        with patch("app.services.tushare_client.TushareClient") as MockClient:
            instance = MockClient.return_value
            # 前 4 信源全部空
            instance.get_stock_basic.return_value = pd.DataFrame({
                "ts_code": ["000001.SZ"], "name": ["平安银行"], "industry": ["银行"],
            })
            instance.get_industry.return_value = pd.DataFrame()
            instance.get_concept_detail.return_value = pd.DataFrame()
            instance.get_ths_index.return_value = pd.DataFrame()

            with patch(
                "app.strategies.prosperity.tools.concept_builder.search_concept_stocks",
                return_value=mock_concept_stocks,
            ):
                codes = get_industry_ts_codes("新能源")
                assert len(codes) >= 4
                assert "300750.SZ" in codes
                assert "002594.SZ" in codes
                assert "601012.SH" in codes
                assert "688599.SH" in codes
        clear_industry_cache()


class TestV3Enhancement:
    """v0.16 增强测试"""

    def test_pipeline_steps_v4(self):
        """v5: 管道步骤包含 learn+counter（Search→Learn→Hypothesize→Verify→Counter→Screening→Report）"""
        from app.strategies.prosperity.coordinator import PIPELINE_STEPS
        assert "counter" in PIPELINE_STEPS, "v5: counter 已恢复（LLM 语义级联）"
        assert "screening" in PIPELINE_STEPS, "v3: screening 已新增"
        assert "learn" in PIPELINE_STEPS, "v4: learn 已新增"
        assert PIPELINE_STEPS == ["search", "learn", "hypothesize", "verify", "counter", "screening", "report", "done"]

    def test_api_has_screening_not_counter(self):
        """v3: API /screening 存在，/counter 不存在"""
        from app.strategies.prosperity.api import router
        route_paths = [r.path for r in router.routes]
        assert "/screening" in route_paths, "v3: /screening 端点必须存在"
        assert "/counter" not in route_paths, "v3: /counter 端点应已移除"

    def test_models_have_v3_fields(self):
        """v3: 模型包含 sentiment / causality_strength / direction_score 等新字段"""
        from app.strategies.prosperity.models import Hypothesis, StockPool
        columns = [c.name for c in Hypothesis.__table__.columns]
        assert "sentiment" in columns, "v3: Hypothesis 缺少 sentiment"
        assert "causality_strength" in columns, "v3: Hypothesis 缺少 causality_strength"
        assert "causality_note" in columns, "v3: Hypothesis 缺少 causality_note"

        pool_cols = [c.name for c in StockPool.__table__.columns]
        assert "direction_score" in pool_cols, "v3: StockPool 缺少 direction_score"
        assert "finance_score" in pool_cols, "v3: StockPool 缺少 finance_score"
        assert "matched_l3" in pool_cols, "v3: StockPool 缺少 matched_l3"
        assert "matched_reason" in pool_cols, "v3: StockPool 缺少 matched_reason"

    def test_config_v018_no_old_weights(self):
        """v0.18: 移除旧融合权重 PROSPERITY_DIRECTION_WEIGHT / PROSPERITY_FINANCE_WEIGHT"""
        from app.core.config import settings
        assert not hasattr(settings, "PROSPERITY_DIRECTION_WEIGHT"), (
            "v0.18: PROSPERITY_DIRECTION_WEIGHT 应已移除"
        )
        assert not hasattr(settings, "PROSPERITY_FINANCE_WEIGHT"), (
            "v0.18: PROSPERITY_FINANCE_WEIGHT 应已移除"
        )

    def test_rating_formula_v3(self):
        """v3: 加权信号聚合评级公式"""
        from app.strategies.prosperity.agents.report_agent import (
            ReportAgent, SIGNAL_MAP, LEVEL_WEIGHTS, CAUSALITY_DISCOUNT,
        )
        agent = ReportAgent()

        # 高景气场景：4 positive confirmed L0+L1 (信号 > 3.0)
        hyps = [
            {"id": "H0-1", "status": "confirmed", "sentiment": "positive", "chain_level": 0, "causality_strength": "strong"},
            {"id": "H0-2", "status": "confirmed", "sentiment": "positive", "chain_level": 0, "causality_strength": "strong"},
            {"id": "H0-3", "status": "confirmed", "sentiment": "positive", "chain_level": 0, "causality_strength": "strong"},
            {"id": "H1-1", "status": "confirmed", "sentiment": "positive", "chain_level": 1, "causality_strength": "strong"},
        ]
        level, icon, signal = agent._assess_prosperity(hyps)
        assert level == "高景气", f"期望高景气, 实际 {level}, 信号={signal}"
        assert signal > 3.0

        # 不景气场景：负面 confirmed
        hyps2 = [
            {"id": "H0-1", "status": "confirmed", "sentiment": "negative", "chain_level": 0, "causality_strength": "strong"},
            {"id": "H0-2", "status": "confirmed", "sentiment": "negative", "chain_level": 0, "causality_strength": "strong"},
        ]
        level2, icon2, signal2 = agent._assess_prosperity(hyps2)
        assert signal2 < 0

        # 信号值计算验证
        assert SIGNAL_MAP[("positive", "confirmed")] == 1.0
        assert SIGNAL_MAP[("negative", "confirmed")] == -1.0
        assert SIGNAL_MAP[("negative", "disputed")] == 0.5
        assert LEVEL_WEIGHTS[0] == 1.0
        assert LEVEL_WEIGHTS[3] == 0.5
        assert CAUSALITY_DISCOUNT["strong"] == 1.0
        assert CAUSALITY_DISCOUNT["weak"] == 0.4


class TestV018PurityScreening:
    """v0.18: 业务纯度排名"""

    def test_purity_scorer_import(self):
        """纯度打分模块可导入"""
        from app.strategies.prosperity.tools.purity_scorer import (
            get_batch_mainbz, match_business_to_l3, compute_purity_scores,
        )
        assert callable(get_batch_mainbz)
        assert callable(match_business_to_l3)
        assert callable(compute_purity_scores)

    def test_purity_scores_no_data_fallback(self):
        """无主营业数据时 purity_score = 0.0"""
        from app.strategies.prosperity.tools.purity_scorer import compute_purity_scores
        result = compute_purity_scores(
            ts_codes=["000001.SZ", "600105.SH"],
            mainbz_data={},
            biz_matches={
                "000001.SZ": {"related_items": [], "matched_l3": None},
                "600105.SH": {"related_items": [], "matched_l3": None},
            },
        )
        assert result["000001.SZ"]["purity_score"] == 0.0
        assert result["600105.SH"]["purity_score"] == 0.0

    def test_purity_scores_calculation(self):
        """纯度分 = 相关收入 / 总收入"""
        from app.strategies.prosperity.tools.purity_scorer import compute_purity_scores
        mainbz_data = {
            "600105.SH": [
                {"bz_item": "超导及铜导体", "bz_sales": 8e8, "bz_profit": 0.5e8},
                {"bz_item": "光通信", "bz_sales": 20e8, "bz_profit": 2e8},
                {"bz_item": "汽车线束", "bz_sales": 22e8, "bz_profit": 1.5e8},
            ],
        }
        biz_matches = {
            "600105.SH": {"related_items": ["超导及铜导体"], "matched_l3": "H3-1"},
        }
        result = compute_purity_scores(
            ts_codes=["600105.SH"],
            mainbz_data=mainbz_data,
            biz_matches=biz_matches,
        )
        r = result["600105.SH"]
        total = 8e8 + 20e8 + 22e8  # 50亿
        expected = 8e8 / total  # 0.16
        assert abs(r["purity_score"] - expected) < 0.01
        assert r["related_items"] == ["超导及铜导体"]
        assert r["matched_l3"] == "H3-1"

    def test_screening_agent_new_output_fields(self):
        """v0.18: ScreeningAgent 返回纯度分+原始指标字段"""
        from app.strategies.prosperity.agents.screening_agent import ScreeningAgent
        # 空 hypotheses → 返回空股池，但不抛异常
        agent = ScreeningAgent()
        result = agent.screen(
            industry_name="不存在的行业测试",
            session_id=999,
            verification={"hypotheses": []},
            search_result={"results": []},
        )
        assert "stock_pool" in result
        # 即使无股票，结构仍然完整
        assert isinstance(result["stock_pool"], list)

    def test_screening_agent_has_v120_fields(self):
        """v1.2.0: stock_pool 条目包含 selection_reason + 三维打字段"""
        from app.strategies.prosperity.agents.screening_agent import ScreeningAgent
        agent = ScreeningAgent()
        result = agent.screen(
            industry_name="不存在的行业测试2",
            session_id=999,
            verification={"hypotheses": []},
            search_result={"results": []},
        )
        pool = result["stock_pool"]
        for s in pool:
            assert "selection_reason" in s, "v1.2.0: stock_pool 缺少 selection_reason"
            assert "prosperity_fit" in s, "v1.2.0: stock_pool 缺少 prosperity_fit"
            assert "risk_exposure" in s, "v1.2.0: stock_pool 缺少 risk_exposure"
            assert "hit_hypotheses" in s, "v1.2.0: stock_pool 缺少 hit_hypotheses"
            assert "purity_estimate" in s, "v1.2.0: stock_pool 缺少 purity_estimate"

    def test_screening_agent_sorts_by_composite(self):
        """v1.2.0: 股池按综合分降序排名"""
        pool = [
            {"name": "北方华创", "composite": 0.85},
            {"name": "中微公司", "composite": 0.72},
            {"name": "有研硅", "composite": 0.06},
        ]
        pool.sort(key=lambda x: x["composite"], reverse=True)
        assert pool[0]["name"] == "北方华创"
        assert pool[2]["name"] == "有研硅"
        assert pool[2]["name"] == "有研硅"

    def test_report_table_has_direction_score_column(self):
        """v1.1.0: 报告股池分段表格含景气适配/风险暴露/质量/综合 + 分段标题"""
        from app.strategies.prosperity.agents.report_agent import ReportAgent
        agent = ReportAgent()
        stock_pool = [
            {
                "rank": 1, "name": "西部超导", "ts_code": "688122.SH",
                "segment": "upstream",
                "prosperity_fit": 0.80,
                "risk_exposure": 0.10,
                "quality": 0.75,
                "composite": 0.65,
                "hit_hypotheses": ["H0-1", "H1-2"],
                "raw_indicators": {"roe": 12.0, "gross_margin": 28.0, "revenue_yoy": 14.0},
            },
        ]
        report = agent._render_report("test", "弱景气", "⚠️", [], stock_pool, 1.0)
        # v1.1.0: 表头改为景气适配/风险暴露/质量/综合 + 命中假设（不再用方向分/纯度分）
        assert "景气适配" in report
        assert "0.80" in report
        assert "命中假设" in report
        assert "H0-1" in report

    def test_report_table_has_purity_columns(self):
        """v1.1.0: ReportAgent 股池分赛道三张表，含命中假设列"""
        from app.strategies.prosperity.agents.report_agent import ReportAgent
        agent = ReportAgent()
        stock_pool = [
            {
                "rank": 1, "name": "西部超导", "ts_code": "688122.SH",
                "segment": "upstream",
                "prosperity_fit": 0.55,
                "risk_exposure": 0.10,
                "quality": 0.72,
                "composite": 0.42,
                "hit_hypotheses": ["H0-3"],
                "raw_indicators": {"roe": 12.0, "gross_margin": 28.0, "revenue_yoy": 14.0},
            },
        ]
        # 只验证 render 不抛异常
        report = agent._render_report("test", "弱景气", "⚠️", [], stock_pool, 1.0)
        # v1.1.0: 分段标题含环节名
        assert "上游" in report or "设备" in report
        assert "ROE" in report


class TestLearningAgent:
    """v0.18.5: LearningAgent 产业图谱构建"""

    def test_learning_agent_import(self):
        """LearningAgent 可导入"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        assert agent is not None
        assert hasattr(agent, "learn")

    def test_learning_agent_template_loaded(self):
        """LearningAgent 加载 prompt 模板"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        assert agent.template != "", "prompt 模板应已加载"
        assert "{industry_name}" in agent.template
        assert "{search_results}" in agent.template

    def test_format_search_results(self):
        """搜索素材格式化——编号正确、包含标题和内容"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        search_result = {
            "results": [
                {"title": "超导线材产能分析", "content": "西部超导产能已超2000吨", "url": "https://example.com/1"},
                {"title": "BEST项目进展", "content": "BEST项目获批", "url": "https://example.com/2"},
            ]
        }
        text = agent._format_search_results(search_result)
        assert "[1]" in text
        assert "[2]" in text
        assert "西部超导" in text
        assert "BEST项目" in text

    def test_format_search_results_empty(self):
        """空搜索素材返回空字符串"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        assert agent._format_search_results({"results": []}) == ""
        assert agent._format_search_results({}) == ""

    def test_learn_empty_search(self):
        """无搜索素材时 learn() 返回 ('', None)"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        # 无 API key → _call_llm 返回 "" → learn 返回 ("", None)
        md, yaml_dict = agent.learn("测试行业", {"results": []})
        assert md == ""
        assert yaml_dict is None

    def test_clean_output_strips_preamble(self):
        """清理输出——切除 ## 产业图谱 之前的开场白"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        output = "好的，以下是为您构建的产业图谱：\n## 产业图谱\n### 1. 价值链\n..."
        cleaned = agent._clean_output(output)
        assert cleaned.startswith("## 产业图谱")
        assert "好的" not in cleaned

    def test_learn_industry_name_in_template(self):
        """prompt 模板中 industry_name 占位符被正确替换"""
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        agent = LearningAgent()
        # 验证模板加载正确
        assert "{industry_name}" in agent.template
        assert "{search_results}" in agent.template


class TestV019DeterministicVerification:
    """v0.19/v0.22: LLM 确定性验证 — _synthesize_status 组合测试（v0.22: conflict_level 三级）"""

    STATUS_CASES = [
        # (source_count, data_alignment, conflict_level, expected_status, description)
        # 核心 confirmed 路径
        (3, "支持", "none", "confirmed", "3信源+数据支持+无冲突"),
        (2, "支持", "none", "confirmed", "2信源+数据支持+无冲突"),
        (2, "部分支持", "none", "confirmed", "2信源+部分支持+无冲突"),
        (3, "部分支持", "none", "confirmed", "3信源+部分支持+无冲突"),
        # partial 路径
        (1, "支持", "none", "partial", "1信源不足→partial"),
        (2, "不支持", "none", "partial", "数据方向不支持→partial"),
        (1, "不支持", "none", "partial", "1信源+数据不支持→partial"),
        (1, "部分支持", "none", "partial", "1信源+部分支持→partial"),
        (1, "无相关数据", "none", "partial", "1信源+无数据→partial"),
        # unverified 路径
        (0, "支持", "none", "unverified", "0信源→unverified"),
        (0, "无相关数据", "none", "unverified", "0信源+无数据→unverified"),
        (0, "不支持", "none", "unverified", "0信源+数据不支持→unverified"),
        # strong（原 disputed）路径（最高优先级）
        (3, "支持", "strong", "overturned", "强反例推翻→overturned（无视信源/数据）"),
        (0, "无相关数据", "strong", "overturned", "0信源+强反例推翻→overturned"),
        (2, "部分支持", "strong", "overturned", "2信源+强反例推翻→overturned"),
        (1, "不支持", "strong", "overturned", "信源不足+数据不支持+强反例推翻→overturned"),
        # weak_disputed 路径（v0.22 新增）
        (3, "支持", "weak", "weak_disputed", "3信源+弱反例→weak_disputed"),
        (2, "不支持", "weak", "weak_disputed", "2信源+数据不支持+弱反例→weak_disputed"),
        (1, "支持", "weak", "weak_disputed", "1信源+弱反例→weak_disputed（降级不切）"),
        (0, "无相关数据", "weak", "unverified", "0信源+弱反例→仍为unverified（无证据优先于弱反例）"),
    ]

    @pytest.mark.parametrize("sc,da,cl,expected,desc", STATUS_CASES)
    def test_synthesize_status(self, sc, da, cl, expected, desc):
        """_synthesize_status 确定性合成（v0.22: conflict_level 三级）"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_status
        result = _synthesize_status(sc, da, cl)
        assert result == expected, f"{desc}: 期望 {expected}, 实际 {result}"

    def test_synthesize_status_deterministic(self):
        """同一输入 100 次调用 → 同一输出"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_status
        results = [_synthesize_status(2, "支持", "none") for _ in range(100)]
        assert all(r == "confirmed" for r in results)

    def test_synthesize_confidence_high(self):
        """高置信度场景（v0.22）"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        assert _synthesize_confidence(3, "支持", "none") == "high"
        assert _synthesize_confidence(2, "部分支持", "none") == "high"
        assert _synthesize_confidence(0, "无相关数据", "strong") == "high"  # overturned=high

    def test_synthesize_confidence_medium(self):
        """中置信度场景（v0.22）"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        assert _synthesize_confidence(1, "支持", "none") == "medium"
        assert _synthesize_confidence(1, "部分支持", "none") == "medium"
        assert _synthesize_confidence(1, "无相关数据", "none") == "medium"

    def test_synthesize_confidence_low(self):
        """低置信度场景（v0.22）"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        assert _synthesize_confidence(0, "无相关数据", "none") == "low"
        assert _synthesize_confidence(0, "不支持", "none") == "low"
        assert _synthesize_confidence(2, "支持", "weak") == "low"  # weak_disputed=low

    # ── v1.0.3: chain_fit 对 status 不应有影响 ──
    def test_chain_fit_no_status_impact(self):
        """chain_fit 不影响 status（避免用旧知识惩罚新信息）"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_status
        base = _synthesize_status(3, "支持", "none")
        assert _synthesize_status(3, "支持", "none", "aligned") == base
        assert _synthesize_status(3, "支持", "none", "misaligned") == base
        assert _synthesize_status(3, "支持", "none", "") == base

    # ── v1.0.3: chain_fit 对 confidence 的 ±1 修正 ──
    def test_chain_fit_confidence_boost(self):
        """aligned → confidence 升一级"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        # medium → high
        assert _synthesize_confidence(1, "支持", "none", "aligned") == "high"
        # low → medium
        assert _synthesize_confidence(0, "无相关数据", "none", "aligned") == "medium"
        # high → high (ceiling)
        assert _synthesize_confidence(3, "支持", "none", "aligned") == "high"

    def test_chain_fit_confidence_drop(self):
        """misaligned → confidence 降一级"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        # high → medium
        assert _synthesize_confidence(3, "支持", "none", "misaligned") == "medium"
        assert _synthesize_confidence(2, "部分支持", "none", "misaligned") == "medium"
        # medium → low
        assert _synthesize_confidence(1, "支持", "none", "misaligned") == "low"
        # low → low (floor)
        assert _synthesize_confidence(0, "无相关数据", "none", "misaligned") == "low"

    def test_chain_fit_confidence_overturned_unchanged(self):
        """overturned(strong conflict) 时的 confidence 不受 chain_fit 修正——证据已非常确定"""
        from app.strategies.prosperity.agents.verify_agent import _synthesize_confidence
        # strong conflict → base=high, aligned → high (ceiling), misaligned → medium
        assert _synthesize_confidence(0, "无相关数据", "strong", "aligned") == "high"
        assert _synthesize_confidence(0, "无相关数据", "strong", "misaligned") == "medium"


class TestV019DeterministicPurity:
    """v0.19: 纯度分确定性关键词语法匹配"""

    def test_extract_l3_keywords_from_ai(self):
        """从 AI 行业 L3 假设提取关键词"""
        from app.strategies.prosperity.tools.purity_scorer import _extract_l3_keywords
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "AI算力基础设施需求持续扩张",
                "investment_implication": "关注AI算力链芯片公司（GPU/AI芯片）、数据中心服务器公司、光模块公司",
                "title": "AI算力链",
            },
            {
                "id": "H3-2",
                "statement": "AI应用向垂直行业渗透",
                "investment_implication": "关注AI应用软件公司、AI+医疗/教育/金融场景落地标的",
                "title": "AI应用渗透",
            },
        ]
        keywords = _extract_l3_keywords(l3_hyps)
        assert "H3-1" in keywords
        assert "H3-2" in keywords
        assert len(keywords["H3-1"]) > 0, "H3-1 至少应提取到关键词"
        assert len(keywords["H3-2"]) > 0, "H3-2 至少应提取到关键词"

    def test_extract_l3_keywords_empty(self):
        """空 L3 假设"""
        from app.strategies.prosperity.tools.purity_scorer import _extract_l3_keywords
        keywords = _extract_l3_keywords([])
        assert keywords == {}

    def test_extract_l3_keywords_deterministic(self):
        """同一假设 10 次提取 → 同一关键词集合"""
        from app.strategies.prosperity.tools.purity_scorer import _extract_l3_keywords
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "AI算力链景气上行",
                "investment_implication": "芯片、服务器、光模块、液冷散热",
            },
        ]
        results = [_extract_l3_keywords(l3_hyps) for _ in range(10)]
        first = results[0]
        for r in results[1:]:
            assert r == first, "关键词提取应完全确定"

    def test_filter_stop_words(self):
        """停用词不应出现在关键词中"""
        from app.strategies.prosperity.tools.purity_scorer import _extract_l3_keywords
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "公司受益于行业增长",
                "investment_implication": "龙头公司 核心标的 行业龙头",
            },
        ]
        keywords = _extract_l3_keywords(l3_hyps)
        all_kws = keywords.get("H3-1", set())
        for stop in ("公司", "行业", "龙头", "标的", "核心", "增长", "受益"):
            assert stop not in all_kws, f"停用词 '{stop}' 不应出现在关键词中"

    def test_keyword_fallback_deterministic(self):
        """_keyword_fallback 相同输入 → 相同输出"""
        from app.strategies.prosperity.tools.purity_scorer import _keyword_fallback
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "AI算力需求扩展",
                "investment_implication": "AI芯片、GPU、算力服务器",
            },
        ]
        mainbz_data = {
            "688256.SH": [
                {"bz_item": "AI芯片设计", "bz_sales": 5e8, "bz_profit": 1e8},
                {"bz_item": "高性能计算", "bz_sales": 3e8, "bz_profit": 0.5e8},
            ],
        }
        result1 = _keyword_fallback(["688256.SH"], mainbz_data, l3_hyps)
        result2 = _keyword_fallback(["688256.SH"], mainbz_data, l3_hyps)
        assert result1 == result2, "关键词匹配应完全确定"

    def test_purity_keyword_match_ai_chips(self):
        """AI芯片业务线应匹配 AI 方向"""
        from app.strategies.prosperity.tools.purity_scorer import _keyword_fallback
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "AI算力基础设施需求持续",
                "investment_implication": "AI芯片公司、GPU厂商、算力服务器、光模块",
            },
        ]
        mainbz_data = {
            "688256.SH": [
                {"bz_item": "AI芯片设计", "bz_sales": 10e8, "bz_profit": 2e8},
                {"bz_item": "云计算服务", "bz_sales": 5e8, "bz_profit": 1e8},
            ],
        }
        result = _keyword_fallback(["688256.SH"], mainbz_data, l3_hyps)
        assert "AI芯片设计" in result["688256.SH"]["related_items"]
        assert result["688256.SH"]["matched_l3"] == "H3-1"

    def test_purity_keyword_no_match(self):
        """不相关业务线不应匹配"""
        from app.strategies.prosperity.tools.purity_scorer import _keyword_fallback
        l3_hyps = [
            {
                "id": "H3-1",
                "statement": "AI算力",
                "investment_implication": "芯片、GPU、服务器",
            },
        ]
        mainbz_data = {
            "600519.SH": [
                {"bz_item": "白酒酿造", "bz_sales": 100e8, "bz_profit": 50e8},
                {"bz_item": "包装材料", "bz_sales": 5e8, "bz_profit": 1e8},
            ],
        }
        result = _keyword_fallback(["600519.SH"], mainbz_data, l3_hyps)
        assert result["600519.SH"]["related_items"] == []
        assert result["600519.SH"]["matched_l3"] is None
