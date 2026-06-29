"""高景气策略 Coordinator — 6 Agent 管道编排

核心职责：
1. 管理研究会话生命周期（创建/推进/完成/失败）
2. 按顺序调用 6 Agent，每步落盘
3. 提供单步执行和全流程执行两种接口
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import (
    get_session as get_db_session,
    ResearchSession,
    Industry,
    Hypothesis,
    TrackingItem,
    init_db,
    migrate_v2,
)

logger = logging.getLogger(__name__)

# 研究步骤顺序
PIPELINE_STEPS = [
    "search",
    "hypothesize",
    "verify",
    "counter",
    "report",
    "done",
]

class CooldownError(Exception):
    """5 天冷却期内拒绝研究请求"""
    def __init__(self, cooldown_info: dict):
        self.cooldown_info = cooldown_info
        super().__init__(cooldown_info.get("message", "Industry is in cooldown period"))


class Coordinator:
    """高景气策略管道编排器"""

    def __init__(self):
        self.data_dir = settings.PROSPERITY_DATA_DIR
        self.rules_dir = settings.PROSPERITY_RULES_DIR
        self.prosperity_dir = settings.PROSPERITY_DIR

        # 管道中间结果缓存：{session_id: {"search": {...}, "hypotheses": [...], ...}}
        self.pipeline_cache: dict[int, dict] = {}

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(exist_ok=True)
        (self.data_dir / "wiki").mkdir(exist_ok=True)
        for sub in ["industries", "hypotheses", "concepts", "comparisons", "synthesis"]:
            (self.data_dir / "wiki" / sub).mkdir(exist_ok=True)
        (self.data_dir / "tracking").mkdir(exist_ok=True)

        # 初始化数据库 + v2 迁移
        self.engine = init_db()
        migrate_v2(self.engine)

    # ═══════════════════════════════════════════════
    # Session 管理
    # ═══════════════════════════════════════════════

    COOLDOWN_DAYS = 5  # 冷却期天数

    def _check_cooldown(self, industry_name: str) -> Optional[dict]:
        """检查行业是否在冷却期内。返回 cooldown 信息，或 None 表示可以研究。"""
        wiki_dir = self.data_dir / "wiki" / "industries"
        page_path = wiki_dir / f"{industry_name}.md"
        if not page_path.exists():
            return None  # 无历史记录，不在冷却期

        content = page_path.read_text(encoding="utf-8")
        # 提取第一条评级行日期
        first_date_match = re.search(r"- \[(\d{4}-\d{2}-\d{2})\]", content)
        if not first_date_match:
            return None

        try:
            last_date = datetime.strptime(first_date_match.group(1), "%Y-%m-%d")
        except ValueError:
            return None

        days_ago = (datetime.utcnow() - last_date).days

        # 提取最近评级
        last_rating = ""
        rating_match = re.search(r"- \[\d{4}-\d{2}-\d{2}\]\s*(\S+)\s*(\S+)", content)
        if rating_match:
            last_rating = rating_match.group(2)

        if days_ago < self.COOLDOWN_DAYS:
            return {
                "status": "cooldown",
                "industry": industry_name,
                "days_ago": days_ago,
                "last_rating": last_rating,
                "last_study_date": last_date.isoformat(),
                "message": f"「{industry_name}」{days_ago} 天前刚完成研究（{last_rating}），"
                           f"距 {self.COOLDOWN_DAYS} 天冷却期还有 {self.COOLDOWN_DAYS - days_ago} 天。"
                           f"是否强制重新研究？",
            }
        return None

    def start_session(self, industry_name: str, force: bool = False) -> int:
        """创建新的研究会话，返回 session_id。force=True 跳过冷却检查。"""
        # 冷却检查
        if not force:
            cooldown = self._check_cooldown(industry_name)
            if cooldown:
                logger.info(f"Cooldown active for {industry_name}: {cooldown['message']}")
                raise CooldownError(cooldown)

        db = get_db_session(self.engine)
        try:
            # 查找或创建行业
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if not industry:
                industry = Industry(name=industry_name, first_study=datetime.utcnow())
                db.add(industry)
                db.flush()
            else:
                industry.last_study = datetime.utcnow()

            # 创建会话
            session = ResearchSession(
                industry_id=industry.id,
                status="running",
                current_step="search",
            )
            db.add(session)
            db.commit()

            session_id = session.id
            logger.info(f"Session {session_id} started for {industry_name}")
            return session_id
        finally:
            db.close()

    def update_step(self, session_id: int, step: str) -> None:
        """更新会话当前步骤"""
        db = get_db_session(self.engine)
        try:
            session = db.query(ResearchSession).filter_by(id=session_id).first()
            if session:
                session.current_step = step
                if step == "done":
                    session.status = "completed"
                    session.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()

    def get_session(self, session_id: int) -> Optional[dict]:
        """获取会话状态"""
        db = get_db_session(self.engine)
        try:
            session = db.query(ResearchSession).filter_by(id=session_id).first()
            if not session:
                return None
            return {
                "id": session.id,
                "industry_id": session.industry_id,
                "status": session.status,
                "current_step": session.current_step,
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            }
        finally:
            db.close()

    # ═══════════════════════════════════════════════
    # 管道执行
    # ═══════════════════════════════════════════════

    def run_full_pipeline(self, industry_name: str, force: bool = False) -> dict:
        """
        全流程执行：搜索 → 假设 → 验证 → 反推 → 报告 → 跟踪

        Returns:
            {session_id, status, steps: {...}, report_path, wiki_path}
        """
        session_id = self.start_session(industry_name, force=force)
        logger.info(f"Starting full pipeline for {industry_name} (session {session_id})")

        try:
            # Step 1: Search
            self.update_step(session_id, "search")
            search_result = self._run_search_agent(industry_name, session_id)
            self.pipeline_cache[session_id] = {"search": search_result}

            # 加载行业历史上下文
            history = self._load_history(industry_name, session_id)

            # Step 2: Hypothesize
            self.update_step(session_id, "hypothesize")
            hypotheses = self._run_hypothesize_agent(industry_name, session_id, search_result, history)
            self.pipeline_cache[session_id]["hypotheses"] = hypotheses

            # Step 3: Verify
            self.update_step(session_id, "verify")
            verification = self._run_verify_agent(industry_name, session_id, hypotheses, history)
            self.pipeline_cache[session_id]["verification"] = verification

            # Step 4: Counter
            self.update_step(session_id, "counter")
            counter_result = self._run_counter_agent(industry_name, session_id, verification, history)
            self.pipeline_cache[session_id]["counter"] = counter_result

            # Step 5: Report
            self.update_step(session_id, "report")
            report_result = self._run_report_agent(industry_name, session_id, counter_result, history)

            # Step 6: Track (needs hypotheses from counter_result, not simplified report_result)
            track_input = {**report_result, "hypotheses": counter_result.get("hypotheses", [])}
            report_result = self._run_track_agent(industry_name, session_id, track_input)

            # Done
            self.update_step(session_id, "done")

            return {
                "session_id": session_id,
                "status": "completed",
                "industry": industry_name,
                "report": report_result,
            }
        except Exception as e:
            logger.error(f"Pipeline failed for session {session_id}: {e}", exc_info=True)
            db = get_db_session(self.engine)
            try:
                session = db.query(ResearchSession).filter_by(id=session_id).first()
                if session:
                    session.status = "failed"
                    db.commit()
            finally:
                db.close()
            return {"session_id": session_id, "status": "failed", "error": str(e)}

    # ═══════════════════════════════════════════════
    # Agent 调用接口
    # ═══════════════════════════════════════════════

    def _run_search_agent(self, industry_name: str, session_id: int, history=None) -> dict:
        from app.strategies.prosperity.agents.search_agent import SearchAgent
        agent = SearchAgent(self.data_dir)
        return agent.search(industry_name, session_id, history)

    def _run_hypothesize_agent(self, industry_name: str, session_id: int, search_result: dict, history=None) -> list[dict]:
        from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
        agent = HypothesizeAgent(self.data_dir, self.rules_dir)
        return agent.form_hypotheses(industry_name, session_id, search_result, history)

    def _run_verify_agent(self, industry_name: str, session_id: int, hypotheses: list[dict], history=None) -> dict:
        from app.strategies.prosperity.agents.verify_agent import VerifyAgent
        agent = VerifyAgent(self.data_dir)
        return agent.verify(industry_name, session_id, hypotheses, history)

    def _run_counter_agent(self, industry_name: str, session_id: int, verification: dict, history=None) -> dict:
        from app.strategies.prosperity.agents.counter_agent import CounterAgent
        agent = CounterAgent(self.data_dir)
        return agent.counter(industry_name, session_id, verification, history)

    def _run_report_agent(self, industry_name: str, session_id: int, counter_result: dict, history=None) -> dict:
        from app.strategies.prosperity.agents.report_agent import ReportAgent
        agent = ReportAgent(self.data_dir)
        study_count = history.study_count if history else 1
        return agent.generate(industry_name, session_id, counter_result, study_count)

    def _run_track_agent(self, industry_name: str, session_id: int, report: dict) -> dict:
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        agent = TrackAgent(self.data_dir)
        return agent.extract_tracking(industry_name, session_id, report)

    # ═══════════════════════════════════════════════
    # 历史上下文
    # ═══════════════════════════════════════════════

    def _load_history(self, industry_name: str, session_id: int) -> Optional["IndustryHistory"]:
        """从 wiki + DB 加载行业历史上下文"""
        from app.strategies.prosperity.industry_history import IndustryHistory

        # 1. 读 wiki/industries 评级历史
        rating_history = []
        last_rating = ""
        last_study_date = None
        wiki_dir = self.data_dir / "wiki"
        industry_page = wiki_dir / "industries" / f"{industry_name}.md"
        if industry_page.exists():
            content = industry_page.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("- ["):
                    rating_history.append(line)
            if rating_history:
                date_match = re.match(r"- \[(\d{4}-\d{2}-\d{2})\]\s*(\S+)\s*(\S+)", rating_history[0])
                if date_match:
                    try:
                        last_study_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                    except ValueError:
                        pass
                    last_rating = date_match.group(3)

        # 2. 读 wiki/synthesis 结构化截取 ~3000字
        last_synthesis_excerpt = ""
        synthesis_dir = wiki_dir / "synthesis"
        if synthesis_dir.exists():
            reports = sorted(
                synthesis_dir.glob(f"*{industry_name}*景*分析.md"),
                reverse=True
            )
            if reports:
                report_content = reports[0].read_text(encoding="utf-8")
                last_synthesis_excerpt = self._extract_synthesis_excerpt(report_content)

        # 3. 查 DB Hypothesis（最近完成 session）
        previous_hypotheses = []
        study_count = 1
        db = get_db_session(self.engine)
        try:
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if industry:
                sessions = (
                    db.query(ResearchSession)
                    .filter_by(industry_id=industry.id)
                    .order_by(ResearchSession.started_at.desc())
                    .all()
                )
                past_sessions = [s for s in sessions if s.id != session_id]
                study_count = len(sessions)
                if past_sessions:
                    last_session = past_sessions[0]
                    db_hyps = (
                        db.query(Hypothesis)
                        .filter_by(session_id=last_session.id)
                        .all()
                    )
                    for h in db_hyps:
                        previous_hypotheses.append({
                            "id": h.id,
                            "title": h.title,
                            "chain_level": h.chain_level,
                            "status": h.status,
                            "confidence": h.confidence,
                            "derives_from": h.derives_from or "",
                            "time_horizon": h.time_horizon or "",
                        })

            # 4. 查 TrackingItem
            pending_items = []
            if industry:
                trackings = (
                    db.query(TrackingItem)
                    .filter_by(industry_id=industry.id, status="pending")
                    .all()
                )
                for t in trackings:
                    pending_items.append({
                        "id": t.id,
                        "item": t.item,
                        "trigger_condition": t.trigger_condition,
                        "source_session_id": t.source_session_id,
                    })
        finally:
            db.close()

        if not previous_hypotheses and not rating_history:
            return None

        cooldown_days = 0
        if last_study_date:
            cooldown_days = (datetime.utcnow() - last_study_date).days

        return IndustryHistory(
            industry_name=industry_name,
            study_count=study_count,
            last_rating=last_rating,
            last_study_date=last_study_date,
            cooldown_days=cooldown_days,
            previous_hypotheses=previous_hypotheses,
            last_synthesis_excerpt=last_synthesis_excerpt,
            rating_history=rating_history,
            pending_tracking_items=pending_items,
        )

    def _extract_synthesis_excerpt(self, report_text: str, max_chars: int = 3000) -> str:
        """从合成报告中提取结构化摘要：L0-L3 推理 + 股池方向，跳过验证/反推章节。

        Fallback: 解析失败时取报告前 max_chars 字。
        """
        lines = report_text.split("\n")
        selected = []
        char_count = 0
        include_sections = [
            "## 推理链概览", "## 现状诊断", "## 一阶推演", "## 二阶推演",
            "## 投资落点", "## 行业股池", "## 综合评级",
            "📊 现状诊断", "🔮 一阶推演", "⚖️ 二阶推演", "🎯 投资落点",
        ]
        skip_sections = ["## 验证总览", "## 反推修正", "## 跟踪"]

        in_skip = False
        for line in lines:
            is_section_header = any(line.strip().startswith(s) for s in skip_sections)
            is_include_header = any(line.strip().startswith(s) for s in include_sections)

            if is_section_header:
                in_skip = True
                continue
            if is_include_header or (
                line.strip().startswith("##") and not line.strip().startswith("###")
            ):
                in_skip = False

            if in_skip:
                continue

            if not line.strip() or line.strip().startswith("```"):
                continue
            if line.strip().startswith("graph ") or line.strip().startswith("```mermaid"):
                continue

            selected.append(line)
            char_count += len(line) + 1
            if char_count >= max_chars:
                break

        if not selected:
            char_count = 0
            for line in lines:
                if line.startswith("```") or line.startswith("graph "):
                    continue
                if not line.startswith("#") and line.strip():
                    selected.append(line)
                    char_count += len(line) + 1
                    if char_count >= max_chars:
                        break

        return "\n".join(selected)
