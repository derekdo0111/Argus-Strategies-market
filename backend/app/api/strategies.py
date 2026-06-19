"""策略相关 API"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class StrategyInfo(BaseModel):
    id: str
    name: str
    description: str
    status: str  # active | inactive


# 已注册策略
STRATEGIES = [
    StrategyInfo(
        id="turtle",
        name="龟龟策略",
        description="类红利股策略：现金质量保证 + 穿透回报率筛选",
        status="active",
    ),
    StrategyInfo(
        id="high_prosperity",
        name="高景气价值股策略",
        description="寻找景气上行期的价值标的",
        status="inactive",
    ),
]


@router.get("", response_model=list[StrategyInfo])
async def list_strategies():
    """获取所有策略列表"""
    return STRATEGIES


@router.get("/{strategy_id}", response_model=StrategyInfo)
async def get_strategy(strategy_id: str):
    """获取单个策略信息"""
    for s in STRATEGIES:
        if s.id == strategy_id:
            return s
    raise HTTPException(status_code=404, detail="策略不存在")


@router.post("/{strategy_id}/refresh")
async def trigger_refresh(strategy_id: str):
    """触发策略全量刷新（当前版本不支持 API 触发，请用命令行脚本）"""
    if strategy_id not in [s.id for s in STRATEGIES if s.status == "active"]:
        raise HTTPException(status_code=400, detail="策略不可用或不存在")

    raise HTTPException(
        status_code=501,
        detail="当前版本不支持API触发全量刷新。请通过命令行运行: python scripts/run_turtle_refresh.py"
    )
