"""IndustryHistory — 行业历史上下文，跨 Agent 共享"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class IndustryHistory:
    """行业历史上下文，Coordinator 预加载后逐级传入 6 Agent"""
    industry_name: str
    study_count: int = 1                    # 第几次研究（含本次），首次=1
    last_rating: str = ""                   # "高景气" | "景气" | "弱景气" | "不景气"
    last_study_date: Optional[datetime] = None
    cooldown_days: int = 0                  # 距上次天数，0 表示首次

    # DB Hypothesis（最近一次 session 的全部假设）
    previous_hypotheses: list[dict] = field(default_factory=list)
    # [{id, title, chain_level, status, confidence, key_indicators, derives_from, time_horizon}]

    # wiki/synthesis 结构化截取（L0-L3推理 + 股池方向，不含验证/反推细节）
    last_synthesis_excerpt: str = ""

    # wiki/industries 评级历史
    rating_history: list[str] = field(default_factory=list)
    # ["- [2026-06-29] 🔥 高景气 — [查看报告](...)"]

    # DB TrackingItem
    pending_tracking_items: list[dict] = field(default_factory=list)

    @property
    def is_first_study(self) -> bool:
        return self.study_count <= 1

    @property
    def verified_count(self) -> int:
        return sum(1 for h in self.previous_hypotheses if h.get("status") == "confirmed")

    @property
    def overturned_count(self) -> int:
        return sum(1 for h in self.previous_hypotheses if h.get("status") == "overturned")

    def get_overturned_hypotheses(self) -> list[dict]:
        return [h for h in self.previous_hypotheses if h.get("status") == "overturned"]

    def get_hypotheses_summary(self) -> str:
        """生成假设状态分布摘要，供 Agent prompt 使用"""
        if not self.previous_hypotheses:
            return "（无历史假设）"
        status_counts = {}
        for h in self.previous_hypotheses:
            s = h.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1
        parts = [f"{k}:{v}" for k, v in status_counts.items()]
        return f"共 {len(self.previous_hypotheses)} 条假设，" + "， ".join(parts)
