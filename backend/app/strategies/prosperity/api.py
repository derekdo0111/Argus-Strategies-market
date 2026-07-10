"""高景气策略 — Web API 端点"""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.strategies.prosperity.coordinator import Coordinator
from app.strategies.prosperity.models import get_session as get_db_session, Hypothesis

logger = logging.getLogger(__name__)
router = APIRouter()

coordinator = Coordinator()


class AnalyzeRequest(BaseModel):
    industry: str


class StepRequest(BaseModel):
    """分步请求 — 需要 session_id 定位已创建的会话"""
    industry: str
    session_id: int


class SessionResponse(BaseModel):
    session_id: int
    status: str
    current_step: str = None


class HistoryResponse(BaseModel):
    sessions: list[dict]


@router.post("/analyze")
async def start_analysis(req: AnalyzeRequest):
    """启动全流程行业分析"""
    try:
        result = coordinator.run_full_pipeline(req.industry)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def step_search(req: AnalyzeRequest):
    """单独执行情报搜索（分步模式第一步，也兼容旧接口）"""
    session_id = coordinator.start_session(req.industry)
    result = coordinator._run_search_agent(req.industry, session_id)
    coordinator.pipeline_cache[session_id] = {"search": result}
    coordinator.update_step(session_id, "search")
    return {"session_id": session_id, "result": result}


@router.post("/hypothesize")
async def step_hypothesize(req: StepRequest):
    """单独执行假设形成（需要先执行 search）"""
    # 验证会话存在
    session = coordinator.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 获取搜索缓存
    cache = coordinator.pipeline_cache.get(req.session_id, {})
    search_result = cache.get("search")
    if not search_result:
        raise HTTPException(status_code=400, detail="No search result cached. Run /search first.")

    try:
        hypotheses = coordinator._run_hypothesize_agent(
            req.industry, req.session_id, search_result
        )
        coordinator.pipeline_cache.setdefault(req.session_id, {})["hypotheses"] = hypotheses
        coordinator.update_step(req.session_id, "hypothesize")
        return {
            "session_id": req.session_id,
            "hypotheses_count": len(hypotheses),
            "hypotheses": hypotheses,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify")
async def step_verify(req: StepRequest):
    """单独执行交叉验证（需要先执行 hypothesize）"""
    session = coordinator.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 尝试从缓存获取 hypotheses，找不到则从 DB 加载
    cache = coordinator.pipeline_cache.get(req.session_id, {})
    hypotheses = cache.get("hypotheses")

    if not hypotheses:
        # 从 DB 加载
        db = get_db_session()
        try:
            db_hyps = db.query(Hypothesis).filter_by(session_id=req.session_id).all()
            if not db_hyps:
                raise HTTPException(status_code=400, detail="No hypotheses found. Run /hypothesize first.")
            hypotheses = [
                {
                    "id": h.title.split("] ")[0].strip("[") if "] " in h.title else h.title,
                    "title": h.title,
                    "chain_level": h.chain_level or 0,
                    "derives_from": h.derives_from.split(",") if h.derives_from else [],
                    "status": h.status,
                    "confidence": h.confidence,
                }
                for h in db_hyps
            ]
        finally:
            db.close()

    if not hypotheses:
        raise HTTPException(status_code=400, detail="No hypotheses found. Run /hypothesize first.")

    try:
        search_result = cache.get("search", {})
        verification = coordinator._run_verify_agent(
            req.industry, req.session_id, hypotheses, search_result
        )
        coordinator.pipeline_cache.setdefault(req.session_id, {})["verification"] = verification
        coordinator.update_step(req.session_id, "verify")
        return verification
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/screening")
async def step_screening(req: StepRequest):
    """单独执行股池筛选（需要先执行 verify）"""
    session = coordinator.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cache = coordinator.pipeline_cache.get(req.session_id, {})
    verification = cache.get("verification")
    search_result = cache.get("search")

    if not verification:
        raise HTTPException(status_code=400, detail="No verification result. Run /verify first.")

    try:
        screening_result = coordinator._run_screening_agent(
            req.industry, req.session_id, verification, search_result or {}
        )
        coordinator.pipeline_cache.setdefault(req.session_id, {})["screening"] = screening_result
        coordinator.update_step(req.session_id, "screening")
        return screening_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/report")
async def step_report(req: StepRequest):
    """单独执行报告生成（需要先执行 screening）"""
    session = coordinator.get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    cache = coordinator.pipeline_cache.get(req.session_id, {})
    verification = cache.get("verification")
    screening_result = cache.get("screening")

    if not verification:
        raise HTTPException(status_code=400, detail="No verification result. Run /verify first.")
    if not screening_result:
        raise HTTPException(status_code=400, detail="No screening result. Run /screening first.")

    try:
        report_result = coordinator._run_report_agent(
            req.industry, req.session_id, verification, screening_result
        )
        coordinator.update_step(req.session_id, "report")
        return report_result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/lint")
async def lint_knowledge_base():
    """知识库巡检"""
    from app.strategies.prosperity.tools.wiki_indexer import update_index, find_orphans, scan_pages
    from app.core.config import settings

    wiki_dir = settings.PROSPERITY_DATA_DIR / "wiki"
    update_index(wiki_dir)
    orphans = find_orphans(wiki_dir)
    pages = scan_pages(wiki_dir)

    # 巡检跟踪项
    from app.strategies.prosperity.agents.track_agent import TrackAgent
    track_agent = TrackAgent()
    due_items = track_agent.check_watchlist()

    return {
        "total_pages": len(pages),
        "orphans": orphans,
        "due_tracking_items": len(due_items),
        "due_details": due_items,
    }


@router.get("/session/status")
async def session_status(session_id: int):
    """查询会话状态"""
    status = coordinator.get_session(session_id)
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
    return status


@router.get("/history")
async def history(industry: str = None) -> HistoryResponse:
    """查询历史记录"""
    from app.strategies.prosperity.models import get_session as get_db_session, ResearchSession
    db = get_db_session()
    try:
        query = db.query(ResearchSession)
        sessions = query.order_by(ResearchSession.started_at.desc()).limit(50).all()
        return HistoryResponse(sessions=[
            {"id": s.id, "industry_id": s.industry_id, "status": s.status,
             "started_at": s.started_at.isoformat() if s.started_at else None}
            for s in sessions
        ])
    finally:
        db.close()
