"""策略相关 API — 从 registry 读取，单一真相来源"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.registry import STRATEGIES as REGISTRY

router = APIRouter()


class StrategyInfo(BaseModel):
    id: str
    name: str
    description: str
    status: str  # active | inactive
    icon: str = ""
    badge: str | None = None


@router.get("", response_model=list[StrategyInfo])
async def list_strategies():
    """获取所有策略列表（从注册表动态读取）"""
    from app.core.registry import strategy_list as _list
    return [StrategyInfo(**s) for s in _list()]


@router.get("/{strategy_id}", response_model=StrategyInfo)
async def get_strategy(strategy_id: str):
    """获取单个策略信息"""
    meta = REGISTRY.get(strategy_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="策略不存在")
    return StrategyInfo(
        id=meta.id,
        name=meta.name,
        description=meta.description,
        status=meta.status,
        icon=meta.icon,
        badge=meta.badge,
    )


@router.post("/{strategy_id}/refresh")
async def trigger_refresh(strategy_id: str):
    """触发策略全量刷新（当前版本不支持 API 触发，请用命令行脚本）"""
    from app.core.registry import active_strategies as _active
    if strategy_id not in _active():
        raise HTTPException(status_code=400, detail="策略不可用或不存在")

    raise HTTPException(
        status_code=501,
        detail="当前版本不支持API触发全量刷新。请通过命令行运行: python scripts/run_turtle_refresh.py"
    )
