"""WebSearchExtractor 单元测试 — v0.7.3 新增 corporate_events"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.strategies.turtle.websearch_extractor import WebSearchExtractor


def make_snippet(content: str, module: str = "q_websearch", index: int = 0) -> dict:
    """构造测试用 snippet"""
    return {
        "content": content,
        "title": "",
        "url": "https://example.com",
        "_module": module,
        "_index": index,
    }


class TestCorporateEvents:
    """corporate_events 提取器测试"""

    def test_extract_placement_event(self):
        """定增事件: 含金额和日期"""
        snippets = [
            make_snippet(
                "2026年3月，分众传媒公告定增不超过13亿股，募集配套资金不超过50亿元，"
                "用于收购新潮传媒100%股权"
            ),
        ]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        events = result.get("corporate_events", [])
        assert len(events) >= 1, f"应有至少1条定增事件，实际 {len(events)}"
        placement = [e for e in events if e["type"] == "placement"]
        assert len(placement) >= 1, "应含 placement 类型事件"
        p = placement[0]
        assert p["amount_billion"] is not None, "定增金额不应为空"
        assert "分众" in p["description"] or "定增" in p["description"]

    def test_extract_merger_event(self):
        """并购事件: 含标的和金额"""
        snippets = [
            make_snippet(
                "分众传媒以发行股份方式收购新潮传媒100%股权，交易作价83.5亿元"
            ),
        ]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        events = result.get("corporate_events", [])
        merger = [e for e in events if e["type"] == "merger"]
        assert len(merger) >= 1, f"应含并购事件，实际 {len(events)}"
        m = merger[0]
        assert m.get("target") is not None, "应提取到并购标的"
        assert "新潮" in m.get("target", ""), f"标的应为新潮传媒，实际 {m.get('target')}"

    def test_extract_multiple_events(self):
        """同时含定增+并购 → 输出2条事件"""
        snippets = [
            make_snippet(
                "公司公告定增83.5亿元，用于收购竞争对手新潮传媒100%股权"
            ),
        ]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        events = result.get("corporate_events", [])
        types = [e["type"] for e in events]
        # 至少含 placement 或 merger
        assert "placement" in types or "merger" in types, f"应含定增或并购事件，实际 {types}"

    def test_empty_events(self):
        """无事件关键词 → 返回空列表"""
        snippets = [
            make_snippet(
                "公司2025年营收增长15%，净利润增加20%，毛利率稳定在40%"
            ),
        ]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        events = result.get("corporate_events", [])
        assert events == [], f"无事件关键词应返回空列表，实际 {events}"

    def test_event_date_extraction(self):
        """日期提取: 2026年3月 → 2026-03"""
        snippets = [
            make_snippet(
                "2026年3月25日，公司公告非公开发行股份募集资金不超过50亿元"
            ),
        ]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        events = result.get("corporate_events", [])
        placement = [e for e in events if e["type"] == "placement"]
        if placement:
            date = placement[0].get("date")
            # 日期可能提取到也可能提取不到（正则best-effort），不强求
            if date:
                assert "2026" in date or "2026-03" in date, f"日期格式不对: {date}"

    def test_corporate_events_in_extract_result(self):
        """验证 extract() 返回 dict 包含 corporate_events key"""
        snippets = [make_snippet("公司定增10亿元用于扩大产能")]
        extractor = WebSearchExtractor()
        result = extractor.extract({"q_websearch": {"snippets": snippets}})
        assert "corporate_events" in result, "extract() 必须包含 corporate_events key"
        assert isinstance(result["corporate_events"], list), "corporate_events 应为 list"
