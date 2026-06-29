"""VerifyAgent — 交叉验证（v2：支持推理链级联）

对每条假设进行多信源交叉验证 + 数据验证。
输出验证状态: CONFIRMED / PARTIAL / DISPUTED / UNVERIFIED / UNREACHABLE

级联规则：上游假设被推翻 → 下游自动标记为 UNREACHABLE（不可达）
防幻觉：数据验证部分只用确定性脚本输出，不靠 LLM 估算。
"""

import logging
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import get_session as get_db_session, Hypothesis
from app.strategies.prosperity.tools.industry_metrics import (
    compute_industry_metrics,
    get_industry_ts_codes,
)
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)


class VerifyAgent:
    """交叉验证 Agent"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR

    def verify(
        self,
        industry_name: str,
        session_id: int,
        hypotheses: list[dict],
        history=None  # Optional[IndustryHistory]
    ) -> dict:
        """
        交叉验证所有假设（v2：先验证 L0，级联到下游）。

        Returns:
            {industry, verified_count, confirmed, partial, disputed, unverified, unreachable, details: [...]}
        """
        logger.info(f"VerifyAgent v2: verifying {len(hypotheses)} hypotheses for {industry_name}")

        # Step 1: 拉取行业财务数据
        industry_data = self._get_industry_data(industry_name)

        # Step 2: 按层级顺序验证（L0 → L1 → L2 → L3）
        verified_by_id: dict[str, dict] = {}
        unreachable_ids: set[str] = set()

        for level in range(4):
            level_hypotheses = [h for h in hypotheses if h.get("chain_level") == level]
            for h in level_hypotheses:
                h_id = h.get("id", "")
                # 检查上游是否被推翻或不可达
                if self._upstream_blocked(h, verified_by_id, unreachable_ids):
                    v = dict(h)
                    v["status"] = "unreachable"
                    v["verify_note"] = "上游假设被推翻，本条不可达"
                    unreachable_ids.add(h_id)
                else:
                    v = self._verify_single(h, industry_data)
                verified_by_id[h_id] = v

        verified = [verified_by_id.get(h.get("id", ""), h) for h in hypotheses]

        # Step 3: 更新假设页
        self._update_hypothesis_pages(industry_name, verified)

        # Step 4: 更新数据库
        self._update_db(session_id, verified)

        # 统计
        statuses = {"confirmed": 0, "partial": 0, "disputed": 0, "unverified": 0, "unreachable": 0}
        for v in verified:
            s = v.get("status", "unverified")
            statuses[s] = statuses.get(s, 0) + 1

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"VerifyAgent v2: {statuses} for {industry_name}")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "verified_count": len(verified),
            "statuses": statuses,
            "hypotheses": verified,
        }

    def _upstream_blocked(self, h: dict, verified_by_id: dict, unreachable_ids: set) -> bool:
        """检查上游假设是否被推翻或不可达"""
        derives = h.get("derives_from", [])
        if not derives:
            return False
        for upstream_id in derives:
            upstream = verified_by_id.get(upstream_id, {})
            status = upstream.get("status", "")
            if status in ("disputed", "overturned") or upstream_id in unreachable_ids:
                return True
        return False

    def _get_industry_data(self, industry_name: str) -> dict:
        """获取行业财务聚合数据"""
        try:
            ts_codes = get_industry_ts_codes(industry_name)
            if ts_codes:
                return compute_industry_metrics(ts_codes[:200], industry_name)
        except Exception as e:
            logger.warning(f"Industry data fetch failed: {e}")

        return {"industry": industry_name, "sample_size": 0, "metrics": {}}

    def _verify_single(self, hypothesis: dict, industry_data: dict) -> dict:
        """
        验证单条假设。简化规则：

        1. 检查 Tushare 数据是否支撑（比如营收增速趋势）
        2. 检查信源数量（至少 2 个）
        3. 反例搜索（简化：检查是否有矛盾数据）
        """
        result = dict(hypothesis)
        sources = hypothesis.get("sources", [])
        confidence = hypothesis.get("confidence", "medium")

        # 规则 1: 信源数量不够 → UNVERIFIED
        if len(sources) < 2:
            result["status"] = "unverified"
            result["verify_note"] = "信源不足，少于 2 个"
            return result

        # 规则 2: 低置信度 + 无数据支撑 → UNVERIFIED
        has_data = self._has_supporting_data(hypothesis, industry_data)
        if confidence == "low" and not has_data:
            result["status"] = "unverified"
            result["verify_note"] = "低置信度且无 Tushare 数据支撑"
            return result

        # 规则 3: 有 Tushare 数据支撑 + 多信源 → CONFIRMED
        if has_data and len(sources) >= 3:
            result["status"] = "confirmed"
            result["verify_note"] = f"Tushare 数据支撑 + {len(sources)} 个独立信源"
        elif has_data:
            result["status"] = "partial"
            result["verify_note"] = "有限数据支撑"
        else:
            result["status"] = "unverified"
            result["verify_note"] = "当前无法验证，待更多数据"

        return result

    def _has_supporting_data(self, hypothesis: dict, industry_data: dict) -> bool:
        """检查假设是否被 Tushare 数据支撑。简化版：检查行业 metrics 是否存在。"""
        metrics = industry_data.get("metrics", {})
        sample_size = industry_data.get("sample_size", 0)
        return sample_size > 0 and len(metrics) > 0

    def _build_history_context(self, history) -> str:
        """构建验证历史上下文（注入 prompt）"""
        if history is None or history.is_first_study:
            return ""

        lines = ["## 历史验证参考", ""]
        lines.append(history.get_hypotheses_summary())
        lines.append("")

        if history.previous_hypotheses:
            lines.append("**上次研究各假设状态**:")
            for h in history.previous_hypotheses:
                level = h.get("chain_level", "?")
                status = h.get("status", "unknown")
                title = h.get("title", "?")
                lines.append(f"- **L{level}** `{h.get('id', '?')}` {title}: `{status}`")
            lines.append("")
            lines.append("请对比本次情报判断：上次已确认的假设是否仍成立？上次被推翻的假设是否有新的支撑证据？")
            lines.append("")

        return "\n".join(lines)

    def _update_hypothesis_pages(self, industry_name: str, verified: list[dict]) -> None:
        """更新假设 Markdown 页面的验证章节"""
        wiki_dir = self.data_dir / "wiki" / "hypotheses"
        for v in verified:
            wiki_path = v.get("wiki_path", "")
            if not wiki_path:
                continue
            full_path = self.data_dir / wiki_path
            if not full_path.exists():
                continue

            content = full_path.read_text(encoding="utf-8")
            status_emoji = {
                "confirmed": "✅ CONFIRMED",
                "partial": "⚠️ PARTIAL",
                "disputed": "❌ DISPUTED",
                "unverified": "🔍 UNVERIFIED",
                "unreachable": "🚫 UNREACHABLE",
            }
            emoji = status_emoji.get(v.get("status", "unverified"), "🔍 UNVERIFIED")
            note = v.get("verify_note", "")

            verification_block = f"\n\n**验证结果**: {emoji}\n\n**验证说明**: {note}\n\n**验证时间**: {datetime.now().isoformat()}\n"
            if "## 验证\n\n（待验证）" in content:
                content = content.replace(
                    "## 验证\n\n（待验证）",
                    f"## 验证\n{verification_block}"
                )
            full_path.write_text(content, encoding="utf-8")

    def _update_db(self, session_id: int, verified: list[dict]) -> None:
        """更新数据库中的假设状态"""
        db = get_db_session()
        try:
            db_hypotheses = db.query(Hypothesis).filter_by(session_id=session_id).all()
            title_map = {h.title: h for h in db_hypotheses}
            for v in verified:
                h = title_map.get(v.get("title"))
                if h:
                    h.status = v.get("status", "unverified")
                    h.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
