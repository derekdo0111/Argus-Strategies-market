"""龟龟策略选股器 — Step 1

10个筛选条件，从全A股中过滤出候选池。
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# === 强周期行业列表 ===
CYCLICAL_INDUSTRIES = {
    "钢铁", "煤炭", "航运", "有色", "化工", "造纸",
    "石油石化", "建筑材料", "基础化工",
}


@dataclass
class ScreenerResult:
    """选股结果"""
    ts_code: str
    name: str
    industry: str
    list_date: str
    total_mv: float          # 总市值（亿）
    pe: float
    pb: float
    roe: float
    dividend_yield: float    # 股息率（%）
    gross_margin: float      # 毛利率（%）
    debt_ratio: float        # 资产负债率（%）
    passed: bool = True
    fail_reasons: list[str] = field(default_factory=list)


@dataclass
class ScreenerStats:
    """选股统计"""
    total_input: int = 0
    fail_st: int = 0
    fail_cyclical: int = 0
    fail_list_years: int = 0
    fail_market_cap: int = 0
    fail_roe: int = 0
    fail_pe: int = 0
    fail_dividend: int = 0
    fail_gross_margin: int = 0
    fail_debt_ratio: int = 0
    fail_pb: int = 0
    passed: int = 0

    @property
    def total_eliminated(self) -> int:
        return self.total_input - self.passed


class TurtleScreener:
    """龟龟策略选股器"""

    # ST/退市标记关键词
    ST_KEYWORDS = ("ST", "退", "*ST")

    def __init__(self, current_year: int = 2026):
        from app.core.config import settings

        self.current_year = current_year
        # 阈值从 settings 读取，.env 可覆盖，未设则用默认值
        self.MIN_LIST_YEARS = getattr(settings, "TURTLE_MIN_LIST_YEARS", 8)
        self.MIN_MARKET_CAP_BILLION = getattr(settings, "TURTLE_MIN_MARKET_CAP", 200.0)
        self.MIN_ROE = getattr(settings, "TURTLE_MIN_ROE", 12.0)
        self.MIN_PE = getattr(settings, "TURTLE_MIN_PE", 5.0)
        self.MAX_PE = getattr(settings, "TURTLE_MAX_PE", 25.0)
        self.MIN_DIVIDEND_YIELD = getattr(settings, "TURTLE_MIN_DIVIDEND_YIELD", 2.5)
        self.MIN_GROSS_MARGIN = getattr(settings, "TURTLE_MIN_GROSS_MARGIN", 25.0)
        self.MAX_DEBT_RATIO = getattr(settings, "TURTLE_MAX_DEBT_RATIO", 60.0)
        self.MIN_PB = 0.0

    def screen(self, stocks: list[dict]) -> tuple[list[ScreenerResult], ScreenerStats]:
        """执行选股

        Args:
            stocks: Tushare stock_basic 格式的股票列表
                    每条含: ts_code, name, industry, list_date,
                           total_mv, pe, pb, roe, dividend_yield,
                           gross_margin, debt_ratio, opcf_to_netprofit

        Returns:
            (通过列表, 统计信息)
        """
        stats = ScreenerStats(total_input=len(stocks))
        results = []

        for s in stocks:
            r = ScreenerResult(
                ts_code=s.get("ts_code", ""),
                name=s.get("name", ""),
                industry=s.get("industry", ""),
                list_date=s.get("list_date", ""),
                total_mv=s.get("total_mv", 0.0),
                pe=s.get("pe", 0.0),
                pb=s.get("pb", 0.0),
                roe=s.get("roe", 0.0),
                dividend_yield=s.get("dividend_yield", 0.0),
                gross_margin=s.get("gross_margin", 0.0),
                debt_ratio=s.get("debt_ratio", 0.0),
            )

            # 条件1: 排除ST/退市
            if any(kw in r.name for kw in self.ST_KEYWORDS):
                r.passed = False
                r.fail_reasons.append("ST或退市股")
                stats.fail_st += 1
                results.append(r)
                continue

            # 条件2: 排除强周期行业
            if r.industry in CYCLICAL_INDUSTRIES:
                r.passed = False
                r.fail_reasons.append(f"强周期行业: {r.industry}")
                stats.fail_cyclical += 1
                results.append(r)
                continue

            # 条件3: 上市年限 > 8年
            try:
                list_year = int(r.list_date[:4])
                if self.current_year - list_year < self.MIN_LIST_YEARS:
                    r.passed = False
                    r.fail_reasons.append(f"上市不足{self.MIN_LIST_YEARS}年")
                    stats.fail_list_years += 1
                    results.append(r)
                    continue
            except (ValueError, TypeError):
                r.passed = False
                r.fail_reasons.append("上市日期无效")
                stats.fail_list_years += 1
                results.append(r)
                continue

            # 条件4: 市值 > 200亿
            if r.total_mv < self.MIN_MARKET_CAP_BILLION:
                r.passed = False
                r.fail_reasons.append(f"市值不足{self.MIN_MARKET_CAP_BILLION}亿")
                stats.fail_market_cap += 1
                results.append(r)
                continue

            # 条件5: ROE > 12%
            if r.roe <= self.MIN_ROE:
                r.passed = False
                r.fail_reasons.append(f"ROE <= {self.MIN_ROE}%")
                stats.fail_roe += 1
                results.append(r)
                continue

            # 条件6: 5 < PE < 25
            if r.pe <= self.MIN_PE or r.pe >= self.MAX_PE:
                r.passed = False
                r.fail_reasons.append(f"PE不在({self.MIN_PE}, {self.MAX_PE})区间")
                stats.fail_pe += 1
                results.append(r)
                continue

            # 条件7: 股息率 > 2.5%
            if r.dividend_yield <= self.MIN_DIVIDEND_YIELD:
                r.passed = False
                r.fail_reasons.append(f"股息率 <= {self.MIN_DIVIDEND_YIELD}%")
                stats.fail_dividend += 1
                results.append(r)
                continue

            # 条件8: 毛利率 > 25%
            if r.gross_margin <= self.MIN_GROSS_MARGIN:
                r.passed = False
                r.fail_reasons.append(f"毛利率 <= {self.MIN_GROSS_MARGIN}%")
                stats.fail_gross_margin += 1
                results.append(r)
                continue

            # 条件9: 负债率 < 60%
            if r.debt_ratio >= self.MAX_DEBT_RATIO:
                r.passed = False
                r.fail_reasons.append(f"负债率 >= {self.MAX_DEBT_RATIO}%")
                stats.fail_debt_ratio += 1
                results.append(r)
                continue

            # 条件10: PB > 0 (隐含，排除负资产)
            # 注: 原来的条件10(经营CF/净利润 > 50%)已删除 — 该检查由CQ维度1精确实现
            #     原批量API ocf_to_or 字段含义错误(OCF/Revenue ≠ OCF/NetProfit)
            if r.pb <= self.MIN_PB:
                r.passed = False
                r.fail_reasons.append("PB <= 0")
                stats.fail_pb += 1
                results.append(r)
                continue

            # 全部通过
            stats.passed += 1
            results.append(r)

        passed = [r for r in results if r.passed]
        logger.info(
            f"选股完成: 输入{stats.total_input}, 通过{stats.passed}, "
            f"淘汰{stats.total_eliminated}"
        )
        if stats.passed < 50:
            logger.warning(f"候选池偏小: {stats.passed} 只")
        elif stats.passed > 200:
            logger.warning(f"候选池偏大: {stats.passed} 只")

        return passed, stats

    def get_fail_summary(self, stats: ScreenerStats) -> str:
        """生成淘汰原因汇总"""
        lines = [
            f"=== 选股器统计 ===",
            f"输入: {stats.total_input}",
            f"通过: {stats.passed}",
            f"淘汰: {stats.total_eliminated}",
            f"  ST/退市: {stats.fail_st}",
            f"  强周期: {stats.fail_cyclical}",
            f"  上市不足{self.MIN_LIST_YEARS}年: {stats.fail_list_years}",
            f"  市值不足{self.MIN_MARKET_CAP_BILLION}亿: {stats.fail_market_cap}",
            f"  ROE<={self.MIN_ROE}%: {stats.fail_roe}",
            f"  PE不在({self.MIN_PE}, {self.MAX_PE}): {stats.fail_pe}",
            f"  股息率<={self.MIN_DIVIDEND_YIELD}%: {stats.fail_dividend}",
            f"  毛利率<={self.MIN_GROSS_MARGIN}%: {stats.fail_gross_margin}",
            f"  负债率>={self.MAX_DEBT_RATIO}%: {stats.fail_debt_ratio}",
            f"  PB<=0: {stats.fail_pb}",
        ]
        return "\n".join(lines)
