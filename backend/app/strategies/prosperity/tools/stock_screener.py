"""行业内百分位排名打分 — 确定性脚本，零 LLM 调用

v0.18: 移除动量因子，权重重新分配为营收35/利润35/ROE20/质量10。
        新增返回原始财务指标（ROE/毛利率/营收增速）供报告展示。
所有维度基于行业内百分位排名（非绝对阈值），消除行业间差异。
权重可通过 scoring_weights.yaml 或 .env 调整。
"""

import bisect
import logging
import yaml
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 默认权重（v0.18：移除动量）
DEFAULT_WEIGHTS = {
    "revenue_growth": 0.35,
    "earnings_growth": 0.35,
    "roe_level": 0.20,
    "quality": 0.10,
}


def score_stocks(
    ts_codes: list[str],
    industry_metrics: dict,
    raw_data_dir: Path = None,
    name_map: dict[str, str] = None,
) -> list[dict]:
    """
    对行业内股票按百分位排名打分（v0.18：仅作参考，不参与股池排名）。

    Args:
        ts_codes: 行业内所有股票代码
        industry_metrics: compute_industry_metrics() 的输出
        raw_data_dir: 原始数据目录（可选，用于读取个股数据）
        name_map: ts_code → 股票名称 映射（可选，用于股池中文名）

    Returns:
        [{ts_code, name, score_total, score_detail, raw_indicators, rank}, ...] 按总分降序
    """
    dist = industry_metrics.get("metrics", {})

    print(f"         -> 行业内百分位打分（{len(ts_codes)} 只）...", flush=True)
    scores = []
    for ts_code in ts_codes:
        # 获取个股数据
        stock_data = _get_stock_data(ts_code, raw_data_dir)
        if not stock_data:
            continue

        detail = {}
        # 营收增速 — 连续百分位排名（基于全量排序值）
        detail["revenue_growth"] = _percentile_score(
            stock_data.get("revenue_yoy", 0),
            dist.get("revenue_growth", {})
        ) * DEFAULT_WEIGHTS["revenue_growth"]

        # 利润增速
        detail["earnings_growth"] = _percentile_score(
            stock_data.get("net_profit_yoy", 0),
            dist.get("net_profit_growth", {})
        ) * DEFAULT_WEIGHTS["earnings_growth"]

        # ROE 水平
        detail["roe_level"] = _percentile_score(
            stock_data.get("roe", 0),
            dist.get("roe", {})
        ) * DEFAULT_WEIGHTS["roe_level"]

        # 质量因子：FCF 为正 + 毛利率趋势
        quality = _quality_score(stock_data)
        detail["quality"] = quality * DEFAULT_WEIGHTS["quality"]

        total = sum(detail.values())
        total = round(total, 4)  # 0~1 区间，保留 4 位小数

        # 名称：优先用 name_map，其次 stock_data，兜底 ts_code
        name = ts_code
        if name_map and ts_code in name_map:
            name = name_map[ts_code]
        elif stock_data.get("name"):
            name = stock_data.get("name")

        # v0.18: 原始财务指标供报告展示
        raw_indicators = {
            "roe": _safe_pct(stock_data.get("roe")),
            "gross_margin": _safe_pct(stock_data.get("grossprofit_margin")),
            "revenue_yoy": _safe_pct(stock_data.get("revenue_yoy")),
            "net_profit_yoy": _safe_pct(stock_data.get("net_profit_yoy")),
        }

        scores.append({
            "ts_code": ts_code,
            "name": name,
            "score_total": total,
            "score_detail": detail,
            "raw_indicators": raw_indicators,
        })

    # 按总分降序排名
    scores.sort(key=lambda x: x["score_total"], reverse=True)
    for i, s in enumerate(scores):
        s["rank"] = i + 1

    print(f"         -> 打分完成，共 {len(scores)} 只有效数据", flush=True)
    return scores


def _safe_pct(val) -> Optional[float]:
    """安全转百分比，保留 1 位小数"""
    if val is None:
        return None
    try:
        return round(float(val), 1)
    except (ValueError, TypeError):
        return None


def _percentile_score(value: float, metrics: dict) -> float:
    """将数值转为 0~1 的连续百分位分

    使用行业全量排序值（sorted_values），通过二分查找确定精确百分位排名。
    不再使用 P25/P50/P75 四档离散分桶。
    """
    sorted_vals = metrics.get("sorted_values", [])
    if not sorted_vals or len(sorted_vals) < 2:
        return 0.5
    rank = bisect.bisect_left(sorted_vals, value)
    return min(rank / len(sorted_vals), 1.0)


def _quality_score(stock_data: dict) -> float:
    """质量因子打分：FCF 为正 + 毛利率 > 20%

    FCF = n_cashflow_act（经营现金流）− c_pay_acq_const_fiolta（CAPEX，取自现金流量表）
    毛利率 = grossprofit_margin（取自 fina_indicator）
    """
    score = 0.0
    # 经营现金流净额 (n_cashflow_act) − 购建固定资产/无形资产 CAPEX (c_pay_acq_const_fiolta)
    ocf = stock_data.get("n_cashflow_act", 0) or 0
    capex = stock_data.get("c_pay_acq_const_fiolta", 0) or 0
    if ocf - capex > 0:
        score += 0.5
    # 毛利率 (grossprofit_margin)，单位 %，>20% 加 0.5 分
    gm = stock_data.get("grossprofit_margin", 0) or 0
    if gm > 20:
        score += 0.5
    return score


def _get_stock_data(ts_code: str, raw_data_dir: Path = None) -> Optional[dict]:
    """获取单只股票的最新财务数据（fina_indicator + cashflow 合并）

    从 Tushare 拉取 fina_indicator（主营指标）和 cashflow（现金流量表），
    合并为单个 dict 返回，确保 quality_score 所需字段齐全。
    """
    try:
        from app.services.tushare_client import TushareClient
        client = TushareClient()

        # 主财务指标
        fina = client.get_fina_indicator(ts_code)
        result = {}
        if fina is not None and not fina.empty:
            result.update(fina.iloc[0].to_dict())

        # 现金流量表（quality_score 需要 n_cashflow_act, c_pay_acq_const_fiolta）
        cf = client.get_cashflow(ts_code)
        if cf is not None and not cf.empty:
            result.update(cf.iloc[0].to_dict())

        return result if result else None
    except Exception as e:
        logger.debug(f"Get stock data failed for {ts_code}: {e}")
    return None


def load_weights(config_path: Path = None) -> dict:
    """加载打分权重配置"""
    weights = DEFAULT_WEIGHTS.copy()
    if config_path and config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                custom = yaml.safe_load(f)
            if custom and isinstance(custom, dict):
                weights.update(custom)
        except Exception as e:
            logger.warning(f"Failed to load scoring weights: {e}")
    return weights
