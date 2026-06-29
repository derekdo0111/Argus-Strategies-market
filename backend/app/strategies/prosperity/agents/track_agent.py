"""TrackAgent — 跟踪项提取 + 巡检

跟踪项触发时机：
- 研究完成时自动提取
- 月度定时巡检
- 研究前预检
"""

import logging
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import get_session as get_db_session, TrackingItem

logger = logging.getLogger(__name__)


class TrackAgent:
    """跟踪项 Agent"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR

    def extract_tracking(self, industry_name: str, session_id: int, report: dict) -> dict:
        """从研究结果中提取所有假设的 key_indicators → watchlist"""
        logger.info(f"TrackAgent: extracting tracking items for {industry_name}")

        all_items = []

        # 从 report 中的假设提取 ALL key_indicators（非仅 unverified/overturned）
        hypotheses = report.get("hypotheses", [])
        for h in hypotheses:
            h_id = h.get("id", "")
            title = h.get("title", "")
            status = h.get("status", "unverified")
            key_indicators = h.get("key_indicators", [])

            if not key_indicators:
                continue

            for indicator in key_indicators:
                if not indicator.strip():
                    continue
                all_items.append({
                    "indicator": indicator.strip(),
                    "industry": industry_name,
                    "hypothesis_id": h_id,
                    "hypothesis_title": title,
                    "hypothesis_status": status,
                    "source_session": session_id,
                    "check_frequency": "monthly",
                    "last_value": None,
                    "last_updated": datetime.utcnow().isoformat(),
                    "status": "pending",
                    "trigger_condition": "数值变化超过 ±20% 或方向反转时触发复核",
                })

        # 按 indicator 名合并去重
        merged = self._merge_indicators(all_items)
        logger.info(f"TrackAgent: {len(all_items)} raw indicators → {len(merged)} merged")

        # 写入 tracking/watchlist.yaml
        watchlist_path = self.data_dir / "tracking" / "watchlist.yaml"
        existing = {"items": []}
        if watchlist_path.exists():
            with open(watchlist_path, "r", encoding="utf-8") as f:
                existing = yaml.safe_load(f) or {"items": []}

        existing["items"].extend(merged)
        with open(watchlist_path, "w", encoding="utf-8") as f:
            yaml.dump(existing, f, allow_unicode=True)

        # 写入数据库
        db = get_db_session()
        try:
            for item in merged:
                db_item = TrackingItem(
                    industry_id=1,  # 简化
                    item=f"[{item.get('indicator')}] {item.get('hypothesis_ids', [])}",
                    trigger_condition=item.get("trigger_condition", ""),
                    check_date=datetime.utcnow() + timedelta(days=90),
                    source_session_id=session_id,
                )
                db.add(db_item)
            db.commit()
        finally:
            db.close()

        return {
            **report,
            "tracking_items": len(merged),
        }

    def _merge_indicators(self, items: list[dict]) -> list[dict]:
        """按 indicator 名合并去重，同一指标多个假设合并到 hypothesis_ids 列表"""
        from collections import defaultdict
        merged = defaultdict(lambda: {
            "indicator": "",
            "industry": "",
            "hypothesis_ids": [],
            "hypothesis_titles": [],
            "hypothesis_statuses": [],
            "source_session": None,
            "check_frequency": "monthly",
            "last_value": None,
            "last_updated": "",
            "status": "pending",
            "trigger_condition": "数值变化超过 ±20% 或方向反转时触发复核",
        })

        for item in items:
            key = item["indicator"]
            entry = merged[key]
            entry["indicator"] = key
            entry["industry"] = item.get("industry", "")
            entry["hypothesis_ids"].append(item.get("hypothesis_id", ""))
            entry["hypothesis_titles"].append(item.get("hypothesis_title", ""))
            entry["hypothesis_statuses"].append(item.get("hypothesis_status", ""))
            entry["source_session"] = item.get("source_session")
            entry["last_updated"] = item.get("last_updated", "")

        return list(merged.values())

    def check_watchlist(self) -> list[dict]:
        """巡检 watchlist，返回到期项目"""
        watchlist_path = self.data_dir / "tracking" / "watchlist.yaml"
        if not watchlist_path.exists():
            return []

        with open(watchlist_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {"items": []}

        now = datetime.utcnow()
        due = []
        for item in data.get("items", []):
            check_date_str = item.get("check_date", "")
            if check_date_str:
                try:
                    check_date = datetime.fromisoformat(check_date_str)
                    if check_date <= now and item.get("status") == "pending":
                        due.append(item)
                except (ValueError, TypeError):
                    pass
        return due
