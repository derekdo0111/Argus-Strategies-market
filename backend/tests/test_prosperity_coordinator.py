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
    from app.strategies.prosperity.tools.wiki_indexer import scan_pages, update_index
    from app.strategies.prosperity.tools.source_crawler import crawl_industry_sources
    assert compute_industry_metrics is not None


def test_agents_import():
    """验证所有 Agent 可导入"""
    from app.strategies.prosperity.agents.search_agent import SearchAgent
    from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
    from app.strategies.prosperity.agents.verify_agent import VerifyAgent
    from app.strategies.prosperity.agents.counter_agent import CounterAgent
    from app.strategies.prosperity.agents.report_agent import ReportAgent
    from app.strategies.prosperity.agents.track_agent import TrackAgent
    assert SearchAgent is not None


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
    """stock_screener.py 单元测试"""

    def test_momentum_score_fallback(self):
        """无效代码应返回中性分 0.5 而非抛异常"""
        from app.strategies.prosperity.tools.stock_screener import _momentum_score
        result = _momentum_score("INVALID.CODE", days=60)
        assert result == 0.5

    def test_momentum_score_valid(self):
        """有效代码不抛异常"""
        from app.strategies.prosperity.tools.stock_screener import _momentum_score
        result = _momentum_score("000001.SZ", days=60)
        assert 0.0 <= result <= 1.0

    def test_momentum_cache_hit(self):
        """缓存命中不重复调 Tushare"""
        from app.strategies.prosperity.tools.stock_screener import (
            _momentum_score, _momentum_cache
        )
        _momentum_cache.clear()
        r1 = _momentum_score("000001.SZ", days=60)
        # 再次调用应从缓存返回
        r2 = _momentum_score("000001.SZ", days=60)
        assert r1 == r2


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
