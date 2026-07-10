"""HypothesizeAgent 两阶段稳定性增强 — 单元测试 + 集成测试

v0.21 新增测试：
- _aggregate_skeletons: 投票逻辑
- _fix_chain_completeness: 链完整性回填
- _validate_fill_output: 骨架校验
- _rescue_downstream_for: 下游找回
- Phase 1 + Phase 2 集成
"""

import pytest
from pathlib import Path


# ── Fixtures ──────────────────────────────────────────

@pytest.fixture
def agent(temp_cache_dir):
    """创建 HypothesizeAgent 实例（用临时目录避免污染真实数据）"""
    from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
    # 使用一个足够深的临时目录作为 data_dir（不会真的写 wiki）
    data_dir = temp_cache_dir / "prosperity_test"
    data_dir.mkdir(parents=True, exist_ok=True)
    rules_dir = Path(__file__).parent.parent / "rules" / "prosperity"
    return HypothesizeAgent(data_dir=data_dir, rules_dir=rules_dir)


# ── _aggregate_skeletons ──────────────────────────────

class TestAggregateSkeletons:
    """Phase 1 投票聚合"""

    def test_normal_all_3_agree(self, agent):
        """3 轮各有 12 条且 ID 完全一致 → 保留全部 12 条"""
        base = [
            {"id": "H0-1", "title": "AI算力需求爆发", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "产业链盈利高增", "chain_level": 0, "derives_from": []},
            {"id": "H1-1", "title": "AI基建投资扩张", "chain_level": 1, "derives_from": ["H0-1"]},
            {"id": "H1-2", "title": "存储涨价周期延续", "chain_level": 1, "derives_from": ["H0-2"]},
            {"id": "H2-1", "title": "算力投资过热风险", "chain_level": 2, "derives_from": ["H1-1"]},
            {"id": "H2-2", "title": "HBM胜出", "chain_level": 2, "derives_from": ["H1-2"]},
            {"id": "H3-1", "title": "聚焦算力核心设备", "chain_level": 3, "derives_from": ["H2-1"]},
            {"id": "H3-2", "title": "布局HBM弹性标的", "chain_level": 3, "derives_from": ["H2-2"]},
        ]
        rounds = [base, base, base]
        skeleton = agent._aggregate_skeletons(rounds)
        assert len(skeleton) == 8
        ids = {h["id"] for h in skeleton}
        assert ids == {"H0-1", "H0-2", "H1-1", "H1-2", "H2-1", "H2-2", "H3-1", "H3-2"}

    def test_partial_2_of_3(self, agent):
        """某假设在 2/3 轮出现 → 保留"""
        round1 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "T2", "chain_level": 0, "derives_from": []},
        ]
        round2 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "T2", "chain_level": 0, "derives_from": []},
            {"id": "H0-3", "title": "T3", "chain_level": 0, "derives_from": []},
        ]
        round3 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "T2", "chain_level": 0, "derives_from": []},
            {"id": "H0-3", "title": "T3", "chain_level": 0, "derives_from": []},
        ]
        skeleton = agent._aggregate_skeletons([round1, round2, round3])
        ids = {h["id"] for h in skeleton}
        assert "H0-1" in ids
        assert "H0-2" in ids
        assert "H0-3" in ids  # 2/3 → 保留

    def test_drop_single_round_only(self, agent):
        """某假设仅在 1/3 轮出现 → 丢弃"""
        round1 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
        ]
        round2 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "T2", "chain_level": 0, "derives_from": []},  # 仅此轮有
        ]
        round3 = [
            {"id": "H0-1", "title": "T1", "chain_level": 0, "derives_from": []},
        ]
        skeleton = agent._aggregate_skeletons([round1, round2, round3])
        ids = {h["id"] for h in skeleton}
        assert "H0-1" in ids
        assert "H0-2" not in ids  # 仅 1/3 → 丢弃

    def test_title_voting(self, agent):
        """同一 ID 不同 title → 选出现最多的"""
        rounds = [
            [{"id": "H0-1", "title": "版本A", "chain_level": 0, "derives_from": []}],
            [{"id": "H0-1", "title": "版本A", "chain_level": 0, "derives_from": []}],
            [{"id": "H0-1", "title": "版本B", "chain_level": 0, "derives_from": []}],
        ]
        skeleton = agent._aggregate_skeletons(rounds)
        assert skeleton[0]["title"] == "版本A"  # 2 vs 1

    def test_empty_skeleton_on_total_divergence(self, agent):
        """3 轮完全不同 → 返回空骨架"""
        rounds = [
            [{"id": "H0-1", "title": "A", "chain_level": 0, "derives_from": []}],
            [{"id": "H0-2", "title": "B", "chain_level": 0, "derives_from": []}],
            [{"id": "H0-3", "title": "C", "chain_level": 0, "derives_from": []}],
        ]
        skeleton = agent._aggregate_skeletons(rounds)
        assert len(skeleton) == 0

    def test_2_rounds_minority_rule(self, agent):
        """仅 2 轮输入时，min_votes=2 → 必须全票"""
        rounds = [
            [{"id": "H0-1", "title": "A", "chain_level": 0, "derives_from": []}],
            [{"id": "H0-1", "title": "A", "chain_level": 0, "derives_from": []},
             {"id": "H0-2", "title": "B", "chain_level": 0, "derives_from": []}],
        ]
        skeleton = agent._aggregate_skeletons(rounds)
        ids = {h["id"] for h in skeleton}
        assert "H0-1" in ids    # 2/2 → 保留
        assert "H0-2" not in ids  # 1/2 → 丢弃


# ── _fix_chain_completeness ───────────────────────────

class TestFixChainCompleteness:
    """链完整性回填"""

    def test_l1_missing_l2_rescued(self, agent):
        """L1 无 L2 → 从 all_rounds 找回"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
            # H2-1 被投票丢弃了
        ]
        all_rounds = [
            [
                {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
                {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
                {"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-1"]},
            ],
        ]
        result = agent._fix_chain_completeness(skeleton, all_rounds)
        ids = {h["id"] for h in result}
        assert "H2-1" in ids  # 被回填

    def test_l1_has_l2_no_change(self, agent):
        """L1 已有 L2 → 不修改"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
            {"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-1"]},
        ]
        result = agent._fix_chain_completeness(skeleton, [])
        assert len(result) == 3  # 不变

    def test_l2_missing_l3_rescued(self, agent):
        """L2 无 L3 → 从 all_rounds 找回"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
            {"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-1"]},
            # H3-1 被投票丢弃了
        ]
        all_rounds = [
            [
                {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
                {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
                {"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-1"]},
                {"id": "H3-1", "title": "L3", "chain_level": 3, "derives_from": ["H2-1"]},
            ],
        ]
        result = agent._fix_chain_completeness(skeleton, all_rounds)
        ids = {h["id"] for h in result}
        assert "H3-1" in ids

    def test_l0_skipped(self, agent):
        """L0 不检查链完整性"""
        skeleton = [{"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []}]
        result = agent._fix_chain_completeness(skeleton, [])
        assert len(result) == 1  # L0 不触发回填


# ── _rescue_downstream_for ────────────────────────────

class TestRescueDownstream:
    """下游找回"""

    def test_rescue_existing(self, agent):
        """下游存在 → 返回最多的"""
        all_rounds = [
            [
                {"id": "H2-1", "title": "版本A", "chain_level": 2, "derives_from": ["H1-1"]},
            ],
            [
                {"id": "H2-1", "title": "版本A", "chain_level": 2, "derives_from": ["H1-1"]},
            ],
            [
                {"id": "H2-2", "title": "版本B", "chain_level": 2, "derives_from": ["H1-1"]},
            ],
        ]
        rescued = agent._rescue_downstream_for("H1-1", all_rounds, 2)
        assert rescued is not None
        assert rescued["id"] == "H2-1"  # 2 vs 1 → 选 H2-1

    def test_rescue_none(self, agent):
        """没有匹配的下游 → None"""
        all_rounds = [
            [{"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-2"]}],
        ]
        rescued = agent._rescue_downstream_for("H1-1", all_rounds, 2)
        assert rescued is None

    def test_rescue_wrong_level(self, agent):
        """目标层级不匹配 → None"""
        all_rounds = [
            [{"id": "H2-1", "title": "L2", "chain_level": 2, "derives_from": ["H1-1"]}],
        ]
        rescued = agent._rescue_downstream_for("H1-1", all_rounds, 3)  # 找 L3 但只有 L2
        assert rescued is None


# ── _validate_fill_output ─────────────────────────────

class TestValidateFillOutput:
    """Phase 2 骨架校验"""

    def test_perfect_match(self, agent):
        """填充输出与骨架完全一致 → 通过"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
        ]
        filled = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": [],
             "statement": "test", "sentiment": "positive"},
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"],
             "statement": "test2", "sentiment": "positive"},
        ]
        assert agent._validate_fill_output(filled, skeleton) is True

    def test_missing_id(self, agent):
        """填充少了一条 → 失败"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
            {"id": "H0-2", "title": "L0b", "chain_level": 0, "derives_from": []},
        ]
        filled = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": [],
             "statement": "test"},
        ]
        assert agent._validate_fill_output(filled, skeleton) is False

    def test_extra_id(self, agent):
        """填充多了一条 → 失败"""
        skeleton = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": []},
        ]
        filled = [
            {"id": "H0-1", "title": "L0", "chain_level": 0, "derives_from": [],
             "statement": "test"},
            {"id": "H0-2", "title": "L0b", "chain_level": 0, "derives_from": [],
             "statement": "extra"},
        ]
        assert agent._validate_fill_output(filled, skeleton) is False

    def test_derives_from_changed(self, agent):
        """derives_from 被 LLM 修改 → 失败"""
        skeleton = [
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1"]},
        ]
        filled = [
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-2"],
             "statement": "test"},
        ]
        assert agent._validate_fill_output(filled, skeleton) is False

    def test_derives_from_order_independent(self, agent):
        """derives_from 顺序无关 → 通过"""
        skeleton = [
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-1", "H0-2"]},
        ]
        filled = [
            {"id": "H1-1", "title": "L1", "chain_level": 1, "derives_from": ["H0-2", "H0-1"],
             "statement": "test"},
        ]
        assert agent._validate_fill_output(filled, skeleton) is True


# ── _build_search_results_text ────────────────────────

class TestBuildSearchResultsText:
    """搜索结果文本构建"""

    def test_basic(self, agent):
        search_result = {
            "results": [
                {"title": "T1", "content": "C1" * 50, "url": "http://a.com"},
                {"title": "T2", "content": "C2" * 50, "url": "http://b.com"},
            ],
            "new_count": 0,
            "old_count": 0,
        }
        text = agent._build_search_results_text(search_result)
        assert "T1" in text
        assert "T2" in text
        assert "http://a.com" in text

    def test_new_old_split(self, agent):
        search_result = {
            "results": [
                {"title": "新1", "content": "C" * 50, "url": ""},
                {"title": "旧1", "content": "C" * 50, "url": ""},
            ],
            "new_count": 1,
            "old_count": 1,
        }
        text = agent._build_search_results_text(search_result)
        assert "本期新情报" in text
        assert "上次已覆盖" in text


# ── 降级模式 ─────────────────────────────────────────

class TestFallbackMode:
    """单轮降级模式"""

    def test_rounds_0_triggers_fallback(self, agent, monkeypatch):
        """PROSPERITY_HYPOTHESIZE_ROUNDS=0 → 走 _form_single_round"""
        monkeypatch.setattr("app.strategies.prosperity.agents.hypothesize_agent.settings.PROSPERITY_HYPOTHESIZE_ROUNDS", 0)
        # 验证调用成功（不真的调 LLM）
        search_result = {"results": [], "new_count": 0, "old_count": 0}
        result = agent.form_hypotheses("test", 1, search_result, None)
        assert isinstance(result, list)
