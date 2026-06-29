"""CounterAgent — 反推修正（v2：推理链级联）

对 DISPUTED 假设标注 OVERTURNED（不删除），分析推翻原因。
上游推翻 → 下游自动标记 UNREACHABLE。
对 PARTIAL 假设修正边界条件或降级置信度。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import get_session as get_db_session, Hypothesis
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)


class CounterAgent:
    """反推修正 Agent（v2：支持推理链级联）"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR

    def counter(self, industry_name: str, session_id: int, verification: dict, history=None) -> dict:
        """
        反推修正（v2：级联处理）。

        操作：
        1. DISPUTED → OVERTURNED（标注不删除）
        2. 上游 OVERTURNED → 下游 UNREACHABLE
        3. PARTIAL → 降级置信度
        4. UNVERIFIED → 写入跟踪项
        """
        hypotheses = verification.get("hypotheses", [])
        logger.info(f"CounterAgent v2: processing {len(hypotheses)} hypotheses")

        # 建立 id → hypothesis 映射
        by_id = {h.get("id", ""): h for h in hypotheses}
        overturned_ids: set[str] = set()
        overturned_count = 0

        # 第一遍：处理 DISPUTED → OVERTURNED
        for h in hypotheses:
            if h.get("status") == "disputed":
                h["status"] = "overturned"
                h["overturn_reason"] = "验证证据不支持该假设"
                overturned_ids.add(h.get("id", ""))
                overturned_count += 1

        # 第二遍：级联 — 上游 overturned 导致下游 unreachable
        cascade_count = 0
        for h in hypotheses:
            h_id = h.get("id", "")
            if h_id in overturned_ids:
                continue
            derives = h.get("derives_from", [])
            if any(up_id in overturned_ids for up_id in derives):
                h["status"] = "unreachable"
                h["overturn_reason"] = f"上游假设 {[up_id for up_id in derives if up_id in overturned_ids]} 被推翻，本条不可达"
                cascade_count += 1

        # 第三遍：PARTIAL → 降级置信度
        for h in hypotheses:
            if h.get("status") == "partial":
                current = h.get("confidence", "medium")
                h["confidence"] = "low" if current == "medium" else "low"
                h["note"] = "边界条件修正：置信度降级"

        # 更新假设页
        self._update_pages(industry_name, hypotheses)

        # 更新数据库
        self._update_db(session_id, hypotheses)

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"CounterAgent v2: {overturned_count} overturned + {cascade_count} cascade-unreachable for {industry_name}")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "overturned_count": overturned_count,
            "cascade_unreachable_count": cascade_count,
            "hypotheses": hypotheses,
        }

    def _build_history_context(self, history) -> str:
        """构建反推历史上下文"""
        if history is None or history.is_first_study:
            return ""

        overturned = history.get_overturned_hypotheses()
        if not overturned:
            return ""

        lines = ["## 上次反推记录", ""]
        lines.append(f"上次研究有 {len(overturned)} 条假设被推翻：")
        for h in overturned:
            lines.append(f"- `{h.get('id', '?')}` {h.get('title', '?')}: overturned (level={h.get('chain_level', '?')})")
        lines.append("")
        lines.append("请对比本次验证结果：上次被推翻的假设，本次是否有新的支撑证据？上次反推指出的风险是否仍成立？")
        lines.append("")
        return "\n".join(lines)

    def _update_pages(self, industry_name: str, hypotheses: list[dict]) -> None:
        wiki_dir = self.data_dir / "wiki" / "hypotheses"
        for h in hypotheses:
            wiki_path = h.get("wiki_path", "")
            full_path = self.data_dir / wiki_path if wiki_path else None
            if not full_path or not full_path.exists():
                continue

            content = full_path.read_text(encoding="utf-8")
            status = h.get("status", "")
            overturn_reason = h.get("overturn_reason", "")
            note = h.get("note", "")

            block_lines = []
            if status == "overturned":
                block_lines.append(f"### ⚰️ OVERTURNED: {datetime.now().strftime('%Y-%m-%d')}")
                block_lines.append(f"推翻原因: {overturn_reason}")
            elif status == "unreachable":
                block_lines.append(f"### 🚫 UNREACHABLE: {datetime.now().strftime('%Y-%m-%d')}")
                block_lines.append(f"原因: {overturn_reason}")
            if note:
                block_lines.append(f"修正说明: {note}")
            block_lines.append("")

            counter_text = "\n".join(block_lines)
            if "## 反推\n\n（待修正）" in content:
                content = content.replace("## 反推\n\n（待修正）", f"## 反推\n{counter_text}")
            full_path.write_text(content, encoding="utf-8")

    def _update_db(self, session_id: int, hypotheses: list[dict]) -> None:
        db = get_db_session()
        try:
            db_hypotheses = db.query(Hypothesis).filter_by(session_id=session_id).all()
            title_map = {h.title: h for h in db_hypotheses}
            for h in hypotheses:
                db_h = title_map.get(h.get("title"))
                if db_h:
                    db_h.status = h.get("status", db_h.status)
                    db_h.confidence = h.get("confidence", db_h.confidence)
                    db_h.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
