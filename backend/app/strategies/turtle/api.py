"""龟龟策略 API 端点"""

import asyncio
import json
import logging
import os
import time
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Path as PathParam, Query, Response
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# 缓存目录 — 龟龟策略专属
CACHE_DIR = settings.TURTLE_CACHE_DIR

# 分析任务状态追踪 (内存)
_analysis_tasks: Dict[str, dict] = {}
_bg_tasks: set = set()  # 防止 asyncio.create_task 被 GC


class StockPoolItem(BaseModel):
    ts_code: str
    name: str
    industry: str
    pr: float
    pe: float
    pb: float
    dividend_yield: float
    market_cap: float
    cq_passed: bool = False
    pr_passed: bool = False
    has_report: bool = False
    scores: Optional[dict] = None


class StockAnalysisReport(BaseModel):
    ts_code: str
    name: str
    report_markdown: str
    generated_at: str


class GateResult(BaseModel):
    cash_quality: dict
    penetration_return: dict
    qrv_summary: Optional[str] = None
    scores: Optional[dict] = None


# ── 工具函数 ────────────────────────────────────────────

def _read_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── ts_code → 股票中文名 映射 (从 pool.json 懒加载，零目录遍历) ──

_name_map: Optional[Dict[str, str]] = None


def _load_name_map() -> Dict[str, str]:
    """从 pool.json 构建 ts_code → name 映射，只读 1 个 JSON，不遍历目录"""
    global _name_map
    if _name_map is not None:
        return _name_map
    _name_map = {}
    pool_file = CACHE_DIR / "pool.json"
    if pool_file.exists():
        try:
            with open(pool_file, "r", encoding="utf-8") as f:
                pool_data = json.load(f)
            for item in pool_data:
                ts_code = item.get("ts_code", "")
                name = item.get("name", "")
                if ts_code and name:
                    _name_map[ts_code] = name
        except Exception:
            logger.warning("pool.json 解析失败，名称映射为空", exc_info=True)
    return _name_map


def _find_stock_dir(ts_code: str) -> Optional[Path]:
    """从 ts_code + name 直拼目录路径，不在 JSON 中的才兜底扫描目录名"""
    name = _load_name_map().get(ts_code, "")
    if name:
        candidate = CACHE_DIR / f"{name}_{ts_code}"
        if candidate.is_dir():
            return candidate
    # 兜底：ts_code 结尾匹配（兼容不在股池的旧目录命名）
    for d in CACHE_DIR.iterdir():
        if d.is_dir() and d.name.endswith(f"_{ts_code}"):
            return d
    return None


# ── cache ──────────────────────────────────────────────

_pool_cache: dict = {"data": None, "timestamp": 0}
_gates_cache: Dict[str, dict] = {}   # ts_code → {"data": ..., "ts": ...}
_analysis_cache: Dict[str, dict] = {}

_POOL_CACHE_TTL = 3600     # 1 小时（个人用：只有手动刷新才变）
_ITEM_CACHE_TTL = 600      # 10 分钟 (gates / analysis)


def _cache_get(cache: dict, key: str) -> Optional[dict]:
    entry = cache.get(key)
    if entry and (time.time() - entry["ts"]) < _ITEM_CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(cache: dict, key: str, data):
    cache[key] = {"data": data, "ts": time.time()}


# ── routes ─────────────────────────────────────────────


@router.get("/status")
async def get_data_status():
    """返回数据新鲜度（pool.json 最后修改时间）"""
    pool_file = CACHE_DIR / "pool.json"
    if not pool_file.exists():
        return {"data_updated_at": None, "status": "no_data"}
    from datetime import datetime
    mtime = os.path.getmtime(pool_file)
    return {
        "data_updated_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"),
        "status": "ok",
    }


@router.get("/pool", response_model=list[StockPoolItem])
async def get_stock_pool(
    response: Response,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """获取龟龟策略股池列表（读 pool.json，1小时缓存，按 PR 降序）"""
    response.headers["Cache-Control"] = "no-store"
    now = time.time()

    # 命中缓存直接返回
    if _pool_cache["data"] is not None and (now - _pool_cache["timestamp"]) < _POOL_CACHE_TTL:
        return _pool_cache["data"][offset : offset + limit]

    pool_file = CACHE_DIR / "pool.json"
    if not pool_file.exists():
        raise HTTPException(status_code=503, detail="pool.json 不存在，请先运行策略刷新")

    try:
        with open(pool_file, "r", encoding="utf-8") as f:
            pool_data = json.load(f)
    except Exception as e:
        logger.error(f"pool.json 读取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="pool.json 读取失败")

    results = []
    for item in pool_data:
        ts_code = item.get("ts_code", "")
        if not ts_code:
            continue

        # 直接拼路径检查 has_report + scores，零目录遍历
        name = item.get("name", "")
        has_report = False
        scores = None
        if name:
            stock_dir = CACHE_DIR / f"{name}_{ts_code}"
            if stock_dir.is_dir():
                md_path = stock_dir / "qrv_analysis.md"
                has_report = md_path.exists()
                if has_report:
                    qrv_path = stock_dir / "qrv_analysis.json"
                    if qrv_path.exists():
                        try:
                            qrv = _read_yaml(qrv_path)
                            scores = qrv.get("scores")
                        except Exception:
                            logger.warning(f"{ts_code}: qrv_analysis.json 解析失败，打分卡将为空", exc_info=True)

        results.append(StockPoolItem(
            ts_code=ts_code,
            name=item.get("name", ""),
            industry=item.get("industry", ""),
            pr=item.get("pr", 0),
            pe=item.get("pe", 0),
            pb=item.get("pb", 0),
            dividend_yield=item.get("dividend_yield", 0),
            market_cap=item.get("market_cap", 0),
            cq_passed=item.get("cq_passed", False),
            pr_passed=item.get("pr_passed", False),
            has_report=has_report,
            scores=scores,
        ))

    # 按 PR 降序
    results.sort(key=lambda x: x.pr, reverse=True)

    # 写入缓存
    _pool_cache["data"] = results
    _pool_cache["timestamp"] = now

    return results[offset : offset + limit]


@router.get("/{ts_code}/analysis", response_model=StockAnalysisReport)
async def get_stock_analysis(ts_code: str = PathParam(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")):
    """获取单股 QRV 分析报告 (缓存 10 分钟)"""
    cached = _cache_get(_analysis_cache, ts_code)
    if cached:
        return StockAnalysisReport(**cached)

    stock_dir = _find_stock_dir(ts_code)
    if not stock_dir:
        raise HTTPException(status_code=404, detail=f"股票 {ts_code} 缓存不存在")

    md_path = stock_dir / "qrv_analysis.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail=f"分析报告不存在，请先触发分析")

    raw_path = stock_dir / "raw_data.yaml"
    meta = {}
    if raw_path.exists():
        try:
            meta = _read_yaml(raw_path).get("meta", {})
        except Exception:
            logger.warning(f"{ts_code}: raw_data.yaml meta 解析失败", exc_info=True)

    md_content = md_path.read_text(encoding="utf-8")

    data = {
        "ts_code": ts_code,
        "name": meta.get("name", ts_code),
        "report_markdown": md_content,
        "generated_at": meta.get("data_date", ""),
    }
    _cache_set(_analysis_cache, ts_code, data)

    return StockAnalysisReport(**data)


# ── 后台分析任务执行器 ──────────────────────────────────

async def _run_analysis_background(ts_code: str):
    """后台任务：执行单股全流程分析"""
    from .coordinator import TurtleCoordinator

    _logger = logging.getLogger(__name__)
    _logger.info(f"[{ts_code}] 🔥 后台任务已启动")

    def update_status(status: str, message: str, progress: int = 0):
        entry = _analysis_tasks.get(ts_code, {})
        _analysis_tasks[ts_code] = {
            "ts_code": ts_code,
            "status": status,
            "progress": progress,
            "message": message,
            "started_at": entry.get("started_at", ""),
        }
        _logger.info(f"[{ts_code}] 状态更新: {status} ({progress}%) - {message}")

    try:
        coordinator = TurtleCoordinator(cache_dir=CACHE_DIR)
        await coordinator.run_single_stock_full(
            ts_code=ts_code,
            force=False,
            status_callback=update_status,
        )
        update_status("done", "分析完成", 100)
        # 分析完成 → 回填 QRV 分数到股池缓存，前端立即看到分数更新
        if _pool_cache["data"] is not None:
            name = _load_name_map().get(ts_code, "")
            stock_dir = CACHE_DIR / f"{name}_{ts_code}" if name else None
            if stock_dir and stock_dir.is_dir():
                qrv_path = stock_dir / "qrv_analysis.json"
                if qrv_path.exists():
                    try:
                        qrv_data = _read_yaml(qrv_path)
                        new_scores = qrv_data.get("scores")
                        for item in _pool_cache["data"]:
                            if item.ts_code == ts_code:
                                item.scores = new_scores
                                break
                    except Exception:
                        pass
        # P2: done 状态 5 分钟后自动清理，避免内存无限膨胀
        async def _cleanup_done():
            await asyncio.sleep(300)
            _analysis_tasks.pop(ts_code, None)
        asyncio.create_task(_cleanup_done())
    except Exception as e:
        import traceback
        err_msg = f"分析失败: {str(e)}"
        update_status("error", err_msg, 0)
        _logger.error(f"[{ts_code}] 后台分析异常:\n{traceback.format_exc()}")
        async def _cleanup_error():
            await asyncio.sleep(300)
            _analysis_tasks.pop(ts_code, None)
        asyncio.create_task(_cleanup_error())


# ── routes ─────────────────────────────────────────────


@router.post("/{ts_code}/analyze")
async def trigger_stock_analysis(ts_code: str = PathParam(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")):
    """触发单股按需分析（后台异步执行）

    状态机: fetching → computing → websearch → analyzing → done / error
    前端轮询 GET /{ts_code}/analyze/status 获取进度
    """
    # 防止重复提交
    existing = _analysis_tasks.get(ts_code)
    if existing and existing.get("status") not in ("done", "error"):
        started_at = existing.get("started_at", "")
        if started_at:
            from datetime import datetime, timedelta
            try:
                start = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                if datetime.now() - start > timedelta(minutes=30):
                    logger.warning(f"[{ts_code}] 任务超时({existing['status']})，允许重新提交")
                    _analysis_tasks.pop(ts_code, None)
                    existing = None
            except ValueError:
                pass
    if existing and existing.get("status") not in ("done", "error"):
        return {
            "ts_code": ts_code,
            "message": "分析任务已在运行中",
            "status": existing["status"],
            "progress": existing.get("progress", 0),
        }

    _gates_cache.pop(ts_code, None)
    _analysis_cache.pop(ts_code, None)
    if _pool_cache["data"] is not None:
        for item in _pool_cache["data"]:
            if item.ts_code == ts_code:
                item.has_report = True
                break

    _analysis_tasks[ts_code] = {
        "ts_code": ts_code,
        "status": "fetching",
        "progress": 0,
        "message": "正在拉取财务数据...",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    logger.info(f"[{ts_code}] 📥 收到分析请求 → 创建后台任务")

    task = asyncio.create_task(_run_analysis_background(ts_code))
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)

    logger.info(f"[{ts_code}] ✅ 后台任务已创建并返回")

    return {
        "ts_code": ts_code,
        "message": "分析任务已提交",
        "status": "fetching",
        "progress": 0,
    }


@router.get("/{ts_code}/analyze/status")
async def get_analysis_status(ts_code: str = PathParam(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")):
    """查询单股分析任务进度（前端轮询用）"""
    task = _analysis_tasks.get(ts_code)
    if not task:
        return {"ts_code": ts_code, "status": "not_started"}
    return task


@router.get("/{ts_code}/gates", response_model=GateResult)
async def get_stock_gate_results(ts_code: str = PathParam(..., pattern=r"^\d{6}\.(SH|SZ|BJ)$")):
    """获取单股的门控结果 + QRV 评分 (缓存 10 分钟)"""
    cached = _cache_get(_gates_cache, ts_code)
    if cached:
        return GateResult(**cached)

    stock_dir = _find_stock_dir(ts_code)
    if not stock_dir:
        raise HTTPException(status_code=404, detail=f"股票 {ts_code} 缓存不存在")

    comp_path = stock_dir / "computed.yaml"
    if not comp_path.exists():
        raise HTTPException(status_code=404, detail="computed.yaml 不存在，请先运行数据计算")

    try:
        computed = _read_yaml(comp_path)
    except Exception as e:
        logger.error(f"{ts_code}: computed.yaml 读取失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="computed.yaml 读取失败")

    cash_quality = computed.get("cash_quality", {})
    penetration_return = computed.get("penetration_return", {})

    qrv_summary = None
    scores = None
    qrv_path = stock_dir / "qrv_analysis.json"
    if qrv_path.exists():
        try:
            qrv = _read_yaml(qrv_path)
            qrv_summary = qrv.get("summary", qrv.get("overall_assessment"))
            scores = qrv.get("scores")
        except Exception:
            logger.warning(f"{ts_code}: qrv_analysis.json gates 解析失败", exc_info=True)

    data = {
        "cash_quality": cash_quality,
        "penetration_return": penetration_return,
        "qrv_summary": qrv_summary,
        "scores": scores,
    }
    _cache_set(_gates_cache, ts_code, data)

    return GateResult(**data)
