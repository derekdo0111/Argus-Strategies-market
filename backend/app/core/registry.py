"""策略注册表 — 加新策略只需在此注册 + 新建策略目录

所有策略元信息的唯一真相来源：
- main.py 遍历注册表自动挂载 API 路由
- api/strategies.py 从注册表读取策略列表
- 前端 Sidebar 通过 GET /api/strategies 动态渲染
- Layout 组件映射表按 component_dir 分发

加新策略流程：
1. 在 STRATEGIES 字典里加一段注册项
2. mkdir strategies/{id}/ + 写 api.py / coordinator.py / ...
3. mkdir data/stock_cache/{id}/
4. 前端写 components/{component_dir}/
5. Layout.tsx 映射表加一行
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyMeta:
    id: str
    name: str
    icon: str
    description: str
    status: str           # "active" | "inactive"
    api_prefix: str       # 如 "/api/turtle"
    cache_dir: str        # 相对于 data/stock_cache/ 的子目录名，如 "turtle"
    rules_dir: str        # 规则目录名，如 "rules/v2"
    rules_version: str    # 规则版本号，如 "v2"
    component_dir: str    # 前端组件目录名，如 "turtle"
    badge: Optional[str] = None  # 侧栏标签，如 "开发中"


STRATEGIES: dict[str, StrategyMeta] = {
    "turtle": StrategyMeta(
        id="turtle",
        name="龟龟策略",
        icon="turtle",
        description="类红利股策略：现金质量保证 + 穿透回报率筛选",
        status="active",
        api_prefix="/api/turtle",
        cache_dir="turtle",
        rules_dir="rules/v2",
        rules_version="v2",
        component_dir="turtle",
    ),
    # 高景气价值策略 — 开发完成后取消注释即激活
    # "high_prosperity": StrategyMeta(
    #     id="high_prosperity",
    #     name="高景气价值股策略",
    #     icon="growth",
    #     description="寻找景气上行期的价值标的",
    #     status="inactive",
    #     api_prefix="/api/prosperity",
    #     cache_dir="prosperity",
    #     rules_dir="rules/v3",
    #     rules_version="v3",
    #     component_dir="prosperity",
    #     badge="开发中",
    # ),
}


def active_strategies() -> dict[str, StrategyMeta]:
    """返回 status == 'active' 的策略"""
    return {k: v for k, v in STRATEGIES.items() if v.status == "active"}


def strategy_list() -> list[dict]:
    """返回前端策略列表所需的字段"""
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "status": m.status,
            "icon": m.icon,
            "badge": m.badge,
        }
        for m in STRATEGIES.values()
    ]
