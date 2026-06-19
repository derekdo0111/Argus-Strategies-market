"""龟龟策略 (Turtle Strategy)

类红利股策略：在现金质量有保证的前提下，通过穿透回报率筛选高回报标的。

模块:
- screener: 选股器（11条件）
- cash_quality: 现金质量门（5子维度硬门）
- penetration_return: 穿透回报率计算与硬门
- coordinator: 流程编排器
"""

from .screener import TurtleScreener, ScreenerResult, ScreenerStats
from .cash_quality import CashQualityGate, CashQualityResult
from .penetration_return import PenetrationReturnCalculator, PRResult
from .coordinator import TurtleCoordinator, CoordinatorState, CoordinatorContext

__all__ = [
    "TurtleScreener", "ScreenerResult", "ScreenerStats",
    "CashQualityGate", "CashQualityResult",
    "PenetrationReturnCalculator", "PRResult",
    "TurtleCoordinator", "CoordinatorState", "CoordinatorContext",
]
