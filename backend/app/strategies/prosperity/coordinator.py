"""Prosperity Strategy Coordinator - 6 Agent Pipeline (v4)

Core responsibilities:
1. Manage research session lifecycle (create/advance/complete/fail)
2. Invoke 6 Agents in order, persist state at each step
3. Provide single-step and full-pipeline execution interfaces

v4 changes: LearningAgent added as Phase 1.5 (Search → Learn → Hypothesize).
Pipeline: Search → Learn → Hypothesize → Verify → Screening → Report + Track.
"""

import logging
import re
import time
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
    migrate_v3,
    migrate_v4,
)

logger = logging.getLogger(__name__)

# Research step order (v5: 7 steps, CounterAgent added as Phase 3.5)
PIPELINE_STEPS = [
    "search",
    "learn",
    "hypothesize",
    "verify",
    "counter",      # v0.10.0: LLM 语义级联裁决（Phase 3.5）
    "screening",
    "report",
    "done",
]

class CooldownError(Exception):
    """Raised when industry is within 5-day cooldown period."""
    def __init__(self, cooldown_info: dict):
        self.cooldown_info = cooldown_info
        super().__init__(cooldown_info.get("message", "Industry is in cooldown period"))


class Coordinator:
    """Prosperity Strategy Pipeline Coordinator"""

    def __init__(self):
        self.data_dir = settings.PROSPERITY_DATA_DIR
        self.rules_dir = settings.PROSPERITY_RULES_DIR
        self.prosperity_dir = settings.PROSPERITY_DIR

        # Pipeline intermediate cache: {session_id: {"search": {...}, "hypotheses": [...], ...}}
        self.pipeline_cache: dict[int, dict] = {}

        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(exist_ok=True)
        (self.data_dir / "wiki").mkdir(exist_ok=True)
        for sub in ["industries", "hypotheses", "concepts", "comparisons", "synthesis"]:
            (self.data_dir / "wiki" / sub).mkdir(exist_ok=True)
        (self.data_dir / "tracking").mkdir(exist_ok=True)

        # Initialize DB + v2 + v3 + v4 migrations
        self.engine = init_db()
        migrate_v2(self.engine)
        migrate_v3(self.engine)
        migrate_v4(self.engine)

    # ===========================================
    # Session Management
    # ===========================================

    COOLDOWN_DAYS = 5

    def _check_cooldown(self, industry_name: str) -> Optional[dict]:
        """Check if industry is in cooldown period. Returns cooldown info or None."""
        wiki_dir = self.data_dir / "wiki" / "industries"
        page_path = wiki_dir / f"{industry_name}.md"
        if not page_path.exists():
            return None

        content = page_path.read_text(encoding="utf-8")
        first_date_match = re.search(r"- \[(\d{4}-\d{2}-\d{2})\]", content)
        if not first_date_match:
            return None

        try:
            last_date = datetime.strptime(first_date_match.group(1), "%Y-%m-%d")
        except ValueError:
            return None

        days_ago = (datetime.utcnow() - last_date).days

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
                "message": (
                    f"{industry_name} was studied {days_ago} days ago ({last_rating}). "
                    f"Cooldown: {self.COOLDOWN_DAYS - days_ago} days remaining. Force?"
                ),
            }
        return None

    def start_session(self, industry_name: str, force: bool = False) -> int:
        """Create a new research session. Returns session_id. force=True skips cooldown check."""
        if not force:
            cooldown = self._check_cooldown(industry_name)
            if cooldown:
                logger.info(f"Cooldown active for {industry_name}: {cooldown['message']}")
                raise CooldownError(cooldown)

        db = get_db_session(self.engine)
        try:
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if not industry:
                industry = Industry(name=industry_name, first_study=datetime.utcnow())
                db.add(industry)
                db.flush()
            else:
                industry.last_study = datetime.utcnow()

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
        """Update session current step."""
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
        """Get session status."""
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

    # ===========================================
    # Industry Size Check (v0.23.6: 交互式子板块推荐)
    # ===========================================

    def check_industry_size(self, industry_name: str) -> dict:
        """预检行业成分股数量，超阈值返回子板块推荐。

        在 run_full_pipeline() 前调用，交给 CLI/API 层决策。

        Returns:
            {
                "name": str,                # 原始行业名
                "count": int,               # 成分股数量
                "overflow": bool,           # 是否超过阈值
                "threshold": int,           # 当前阈值
                "subconcepts": [            # 推荐子板块（overcrow=True 时非空）
                    {name, ts_code, count, score}, ...
                ],
            }
        """
        from app.strategies.prosperity.tools.industry_metrics import get_industry_ts_codes
        from app.strategies.prosperity.tools.concept_index import suggest_subconcepts

        ts_codes = get_industry_ts_codes(industry_name)
        count = len(ts_codes)
        threshold = settings.PROSPERITY_SCREENING_THRESHOLD

        result = {
            "name": industry_name,
            "count": count,
            "overflow": count > threshold,
            "threshold": threshold,
            "subconcepts": [],
        }

        if result["overflow"]:
            subconcepts = suggest_subconcepts(industry_name)
            # 额外过滤：确认子板块成分股数 <= threshold
            viable = [s for s in subconcepts if s["count"] <= threshold]
            if not viable:
                viable = subconcepts  # 全部超限 → 仍然展示，让用户选
            result["subconcepts"] = viable

        return result

    # ===========================================
    # Pipeline Execution
    # ===========================================

    def run_full_pipeline(self, industry_name: str, force: bool = False,
                          progress_callback=None) -> dict:
        """
        Full pipeline (v3): Search -> Hypothesize -> Verify -> Screening -> Report -> Track

        Args:
            progress_callback: optional fn(step_name, phase, detail)

        Returns:
            {session_id, status, steps: {...}, report_path, wiki_path}
        """
        def _p(step_name: str, phase: str, detail: str = ""):
            msg = f"[{step_name}] {phase}"
            if detail:
                msg += f" -- {detail}"
            elapsed = time.time() - t_start[0]
            ts = f"+{elapsed:.0f}s"
            full_msg = f"  {ts:>8s}  {msg}"
            print(full_msg)
            logger.info(msg)
            if progress_callback:
                progress_callback(step_name, phase, detail)

        t_start = [time.time()]
        session_id = self.start_session(industry_name, force=force)

        print(f"\n>>> Prosperity Pipeline: {industry_name} (session {session_id})")
        print(f"{'-' * 60}")

        try:
            # Pre-check: TrackAgent 巡检
            _p("pre-check", "start", "checking watchlist for changes")
            pre_check = self._run_track_pre_check(industry_name)
            if pre_check["triggered_count"] > 0:
                _p("pre-check", "warning",
                   f"{pre_check['triggered_count']} indicators triggered!")
                for item in pre_check["triggered_items"]:
                    _p("pre-check", "triggered", item.get("change_summary", ""))
            else:
                _p("pre-check", "done", f"all {pre_check['checked_count']} indicators normal")

            # Step 1: Search
            _p("1/6 search", "start", "text + data search")
            self.update_step(session_id, "search")
            search_result = self._run_search_agent(industry_name, session_id)
            n_results = len(search_result.get("results", []))
            _p("1/6 search", "done", f"{n_results} results")

            self.pipeline_cache[session_id] = {"search": search_result}

            # Phase 1.5: Learn — 首次研究时构建产业图谱，后续复用
            _p("learn", "start", "building industry knowledge model")
            self.update_step(session_id, "learn")
            self._run_learning_agent(industry_name, search_result)

            history = self._load_history(industry_name, session_id)
            chain_model = self._load_chain_model(industry_name)  # v1.0: 加载产业链拓扑 YAML

            # Step 2: Hypothesize
            _p("2/6 hypothesize", "start", "LLM generating hypotheses")
            self.update_step(session_id, "hypothesize")
            hypotheses = self._run_hypothesize_agent(industry_name, session_id, search_result, history, chain_model)
            self.pipeline_cache[session_id]["hypotheses"] = hypotheses
            _p("2/6 hypothesize", "done", f"{len(hypotheses)} hypotheses generated")

            # Step 3: Verify (LLM-based, with counter-evidence search)
            _p("3/6 verify", "start", "LLM serial chain verification + counter searches...")
            self.update_step(session_id, "verify")
            verification = self._run_verify_agent(industry_name, session_id, hypotheses, search_result, history, chain_model)
            self.pipeline_cache[session_id]["verification"] = verification
            statuses = verification.get("statuses", {})
            _p("3/6 verify", "done",
               f"confirmed={statuses.get('confirmed',0)} partial={statuses.get('partial',0)} "
               f"disputed={statuses.get('disputed',0)} unverified={statuses.get('unverified',0)}")

            # Step 3.5: CounterAgent — LLM 语义级联裁决（v0.10.0, v1.0: +history +chain_model）
            _p("4/6 counter", "start", "LLM semantic cascade + sentiment adjustment...")
            self.update_step(session_id, "counter")
            verified_hypotheses = verification.get("hypotheses", [])
            cascade_result = self._run_counter_agent(industry_name, session_id, verified_hypotheses, history, chain_model)
            verification["hypotheses"] = cascade_result
            # 重新统计级联后状态
            cascade_statuses = {}
            for h in cascade_result:
                s = h.get("status", "unverified")
                cascade_statuses[s] = cascade_statuses.get(s, 0) + 1
            _p("4/6 counter", "done",
               f"overturned={cascade_statuses.get('overturned',0)} "
               f"weak_disputed={cascade_statuses.get('weak_disputed',0)} "
               f"unreachable={cascade_statuses.get('unreachable',0)} "
               f"remaining={len(cascade_result)-cascade_statuses.get('unreachable',0)}")

            # Step 4: Screening (LLM direction match + financial scoring)
            _p("5/6 screening", "start", "LLM direction match + financial scoring fusion")
            self.update_step(session_id, "screening")
            screening_result = self._run_screening_agent(industry_name, session_id, verification, search_result, history, chain_model)
            self.pipeline_cache[session_id]["screening"] = screening_result
            _p("5/6 screening", "done", f"stock pool: {len(screening_result.get('stock_pool', []))} stocks")

            # Step 5: Report
            _p("6/6 report", "start", "generating prosperity report")
            self.update_step(session_id, "report")
            report_result = self._run_report_agent(industry_name, session_id, verification, screening_result, history)
            _p("6/6 report", "done")

            # Track (bonus step)
            _p("track", "start", "extracting tracking items")
            track_input = {**report_result, "hypotheses": verification.get("hypotheses", [])}
            report_result = self._run_track_agent(industry_name, session_id, track_input)
            _p("track", "done")

            # Done
            self.update_step(session_id, "done")

            total_elapsed = time.time() - t_start[0]
            rating = report_result.get("rating", "?")
            print(f"{'-' * 60}")
            print(f"[OK] Pipeline complete [{industry_name}]: rating={rating}  elapsed={total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
            print()

            return {
                "session_id": session_id,
                "status": "completed",
                "industry": industry_name,
                "report": report_result,
            }
        except Exception as e:
            total_elapsed = time.time() - t_start[0]
            logger.error(f"Pipeline failed for session {session_id}: {e}", exc_info=True)
            print(f"\n[FAIL] Pipeline failed (session {session_id}): {e}")
            db = get_db_session(self.engine)
            try:
                session = db.query(ResearchSession).filter_by(id=session_id).first()
                if session:
                    session.status = "failed"
                    db.commit()
            finally:
                db.close()
            return {"session_id": session_id, "status": "failed", "error": str(e)}

    # ===========================================
    # Agent Invocation
    # ===========================================

    def _run_learning_agent(self, industry_name: str, search_result: dict) -> None:
        """Phase 1.5: 构建产业图谱，写入 wiki 页面 + 伴生 YAML 结构化文件。

        仅在首次研究时执行。已有「## 产业图谱」节的行业跳过。
        v1.0: 同步输出 Markdown + YAML 双文件。
        """
        from app.strategies.prosperity.agents.learning_agent import LearningAgent
        import yaml as yaml_lib

        wiki_page = self.data_dir / "wiki" / "industries" / f"{industry_name}.md"
        yaml_page = self.data_dir / "wiki" / "industries" / f"{industry_name}.yaml"

        # 已有产业图谱 + YAML → 跳过
        if wiki_page.exists() and yaml_page.exists():
            content = wiki_page.read_text(encoding="utf-8")
            if "## 产业图谱" in content:
                print("  [learning] skip — 产业图谱+YAML 已存在")
                logger.info(f"LearningAgent: model already exists for {industry_name}, skipping")
                return

        # 生成产业图谱
        agent = LearningAgent(self.rules_dir)
        model_md, yaml_dict = agent.learn(industry_name, search_result)

        if not model_md:
            print("  [learning] warning — 产业图谱生成失败")
            logger.warning(f"LearningAgent: empty output for {industry_name}")
            return

        # 写入 Markdown 页面
        if wiki_page.exists():
            content = wiki_page.read_text(encoding="utf-8")
        else:
            content = f"# {industry_name}\n\n## 景气评级历史\n\n"

        wiki_page.write_text(content + "\n" + model_md, encoding="utf-8")
        md_len = len(model_md)

        # 写入 YAML 伴生文件
        yaml_len = 0
        if yaml_dict:
            yaml_page.write_text(
                yaml_lib.dump(yaml_dict, allow_unicode=True, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            yaml_len = yaml_page.stat().st_size
            print(f"  [learning] done — 产业图谱 + YAML 已写入（md={md_len}字符, yaml={yaml_len}字节）")
        else:
            print(f"  [learning] done — 产业图谱已写入（md={md_len}字符, yaml=未生成）")
            logger.warning(f"LearningAgent: YAML not generated for {industry_name}")

        logger.info(f"LearningAgent: model written to {wiki_page}")

    def _run_search_agent(self, industry_name: str, session_id: int, history=None) -> dict:
        from app.strategies.prosperity.agents.search_agent import SearchAgent
        agent = SearchAgent(self.data_dir)
        return agent.search(industry_name, session_id, history)

    def _run_hypothesize_agent(self, industry_name: str, session_id: int, search_result: dict, history=None, chain_model=None) -> list[dict]:
        from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent
        agent = HypothesizeAgent(self.data_dir, self.rules_dir)
        return agent.form_hypotheses(industry_name, session_id, search_result, history, chain_model)

    def _run_verify_agent(self, industry_name: str, session_id: int, hypotheses: list[dict], search_result: dict, history=None, chain_model=None) -> dict:
        from app.strategies.prosperity.agents.verify_agent import VerifyAgent
        agent = VerifyAgent(self.data_dir)
        # v0.10.0: 跳过内建级联安全网，由 CounterAgent (Phase 3.5) 接管
        return agent.verify(industry_name, session_id, hypotheses, search_result, history, chain_model, skip_cascade=True)

    def _run_counter_agent(self, industry_name: str, session_id: int, verified_hypotheses: list[dict], history=None, chain_model=None) -> list[dict]:
        """Phase 3.5: CounterAgent LLM 语义级联裁决（v0.10.0, v1.0: +history +chain_model）"""
        from app.strategies.prosperity.agents.counter_agent import CounterAgent
        agent = CounterAgent(self.data_dir, self.rules_dir)
        return agent.cascade(industry_name, session_id, verified_hypotheses, history, chain_model)

    def _run_screening_agent(self, industry_name: str, session_id: int, verification: dict, search_result: dict, history=None, chain_model=None) -> dict:
        from app.strategies.prosperity.agents.screening_agent import ScreeningAgent
        agent = ScreeningAgent(self.data_dir)
        return agent.screen(industry_name, session_id, verification, search_result, history, chain_model)

    def _run_report_agent(self, industry_name: str, session_id: int, verification: dict, screening_result: dict, history=None) -> dict:
        from app.strategies.prosperity.agents.report_agent import ReportAgent
        agent = ReportAgent(self.data_dir)
        study_count = history.study_count if history else 1
        return agent.generate(industry_name, session_id, verification, screening_result, study_count)

    def _run_track_agent(self, industry_name: str, session_id: int, report: dict) -> dict:
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        agent = TrackAgent(self.data_dir)
        return agent.extract_tracking(industry_name, session_id, report)

    def _run_track_pre_check(self, industry_name: str) -> dict:
        """研究前预检：检查行业 watchlist 是否有触发项"""
        from app.strategies.prosperity.agents.track_agent import TrackAgent
        agent = TrackAgent(self.data_dir)
        return agent.check_industry(industry_name)

    # ===========================================
    # History Context
    # ===========================================

    def _load_chain_model(self, industry_name: str) -> Optional[dict]:
        """加载产业链拓扑 YAML（v1.0 Wiki-Centric Phase 1）。

        首次研究时 YAML 不存在 → 返回 None，各 agent 降级到当前行为。
        后续研究时自动加载，跨 run 复用。
        """
        yaml_path = self.data_dir / "wiki" / "industries" / f"{industry_name}.yaml"
        if yaml_path.exists():
            import yaml
            try:
                return yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to load chain model YAML: {e}")
        return None

    def _load_history(self, industry_name: str, session_id: int) -> Optional["IndustryHistory"]:
        """Load industry history context from wiki + DB."""
        from app.strategies.prosperity.industry_history import IndustryHistory

        # 1. Read wiki/industries rating history
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

        # 2. Read wiki/synthesis excerpt (~3000 chars)
        last_synthesis_excerpt = ""
        synthesis_dir = wiki_dir / "synthesis"
        if synthesis_dir.exists():
            reports = sorted(
                synthesis_dir.glob(f"*{industry_name}*"),
                reverse=True
            )
            if reports:
                report_content = reports[0].read_text(encoding="utf-8")
                last_synthesis_excerpt = self._extract_synthesis_excerpt(report_content)

        # 3. Query DB Hypothesis (most recently completed session)
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

            # 4. Query TrackingItem
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
        """Extract structured summary from synthesis report (L0-L3 + stock pool, skip verify/counter sections).

        Fallback: take first max_chars chars on parse failure.
        """
        lines = report_text.split("\n")
        selected = []
        char_count = 0
        include_sections = [
            "## ", "📊 ", "🔮 ", "⚖️ ", "🎯 ",
        ]
        skip_sections = ["## Verification", "## Counter", "## Tracking"]

        in_skip = False
        for line in lines:
            is_skip = any(line.strip().startswith(s) for s in skip_sections)
            is_new_h2 = line.strip().startswith("##") and not line.strip().startswith("###")

            if is_skip:
                in_skip = True
                continue
            if is_new_h2:
                in_skip = False

            if in_skip:
                continue
            if not line.strip() or line.strip().startswith("```"):
                continue
            if "graph " in line or "mermaid" in line:
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
