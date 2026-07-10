"""行业聚合指标计算 — 确定性脚本，零 LLM 调用

从 Tushare 拉取同行业所有上市公司的财务数据，计算通用聚合指标。
不写死行业专属阈值，只做纯数学聚合。
"""

import logging
import statistics
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 行业分类缓存
# ═══════════════════════════════════════════════

# 缓存：{industry_name: [ts_codes]}
_industry_cache: dict[str, list[str]] = {}

# 缓存：stock_basic 全量 DataFrame（避免重复调用）
_stock_basic_cache = None






def get_industry_ts_codes(industry_name: str) -> list[str]:
    """
    根据行业名称获取该行业所有上市公司的 ts_code 列表。

    匹配策略：
    0. ConceptIndex rapidfuzz 模糊搜索 + ths_member（v0.23.5 新增，最快）
    1. Tushare stock_basic 的 industry 字段精确匹配
    2. 精确匹配失败 → 模糊匹配（contains）
    3. 申万 index_classify 的 industry_name 精确匹配（取并集）
    4. concept_detail 概念板块成分股（免费，兜底）
    5. ths_index → ths_member 同花顺概念板块（需积分权限）
    6. 搜索引擎自建概念板块（Bocha + LLM + stock_basic 交叉验证，终极兜底）
    7. 结果缓存

    Args:
        industry_name: 行业名称，如 "半导体", "消费电子"

    Returns:
        ts_code 列表，如 ["002371.SZ", "688981.SH", ...]
    """
    global _industry_cache, _stock_basic_cache

    # 命中缓存直接返回
    if industry_name in _industry_cache:
        return _industry_cache[industry_name]

    codes: set[str] = set()

    try:
        from app.services.tushare_client import TushareClient
        client = TushareClient()

        # ── 信源0: ConceptIndex rapidfuzz 模糊搜索（v0.23.5，优先最快路径）──
        try:
            from app.strategies.prosperity.tools.concept_index import resolve as concept_resolve
            concept_codes = concept_resolve(industry_name)
            if concept_codes:
                for c in concept_codes:
                    codes.add(c)
                logger.info(
                    f"ConceptIndex 匹配到 '{industry_name}': "
                    f"{len(concept_codes)} 只股票"
                )
        except Exception as e:
            logger.debug(f"ConceptIndex 查询 '{industry_name}' 失败: {e}")

        # ── 信源1: stock_basic 的 industry 字段 ──
        if _stock_basic_cache is None:
            stocks = client.get_stock_basic()
            if stocks is not None and not stocks.empty:
                _stock_basic_cache = stocks
            else:
                _stock_basic_cache = None

        if _stock_basic_cache is not None:
            stocks = _stock_basic_cache
            industry_clean = industry_name.replace(" ", "")
            # 精确匹配优先
            matches = stocks[stocks["industry"] == industry_clean]
            if matches.empty:
                # 模糊匹配兜底
                matches = stocks[stocks["industry"].str.contains(
                    industry_clean, na=False
                )]
            if not matches.empty:
                for c in matches["ts_code"].tolist():
                    codes.add(c)
                logger.debug(
                    f"stock_basic 匹配到 {industry_name}: {len(matches)} 只股票"
                )

        # ── 信源2: 申万行业分类 index_classify ──
        try:
            for level in ("L1", "L2", "L3"):
                sw = client.get_industry(level=level)
                if sw is not None and not sw.empty:
                    sw_matches = sw[sw["industry_name"] == industry_name]
                    if not sw_matches.empty:
                        for c in sw_matches["ts_code"].tolist():
                            codes.add(c)
                        logger.debug(
                            f"申万{level} 匹配到 {industry_name}: {len(sw_matches)} 只"
                        )
        except Exception as e:
            logger.debug(f"申万分类查询 {industry_name} 失败: {e}")

        # ── 信源3: concept_detail 概念板块成分股（免费，0 积分）──
        if len(codes) == 0:
            try:
                concept_detail = client.get_concept_detail(concept_name=industry_name)
                if concept_detail is not None and not concept_detail.empty:
                    for c in concept_detail["ts_code"].tolist():
                        codes.add(c)
                    logger.info(
                        f"concept_detail 匹配到 '{industry_name}': "
                        f"{len(concept_detail)} 只股票"
                    )
            except Exception as e:
                logger.debug(f"concept_detail 查询 '{industry_name}' 失败: {e}")

        # ── 信源4: 同花顺概念板块成分股（ths_index → ths_member）──
        if len(codes) == 0:
            try:
                # 4a: 获取所有同花顺概念板块
                ths_concepts = client.get_ths_index(type="N")
                if ths_concepts is not None and not ths_concepts.empty:
                    # 4b: 按名称模糊匹配（板块名称包含行业名）
                    industry_clean = industry_name.replace(" ", "")
                    matches = ths_concepts[
                        ths_concepts["name"].str.contains(
                            industry_clean, na=False
                        )
                    ]
                    # 优先精确匹配，无精确则用模糊
                    exact = ths_concepts[ths_concepts["name"] == industry_clean]
                    if not exact.empty:
                        matches = exact

                    # 4c: 逐板块查询成分股（最多取前 5 个匹配板块）
                    for _, row in matches.head(5).iterrows():
                        ts_code = row["ts_code"]
                        try:
                            members = client.get_ths_member(ts_code=ts_code)
                            if members is not None and not members.empty:
                                # API 返回 ts_code
                                member_col = (
                                    "con_code" if "con_code" in members.columns
                                    else "ts_code"
                                )
                                for c in members[member_col].tolist():
                                    codes.add(c)
                        except Exception:
                            continue

                    if codes:
                        logger.info(
                            f"同花顺概念匹配到 '{industry_name}': "
                            f"{len(matches)} 个板块"
                        )
            except Exception as e:
                logger.debug(f"同花顺概念查询 '{industry_name}' 失败: {e}")

        # ── 信源5: 搜索引擎自建概念板块（Tavily + LLM + stock_basic 交叉验证）──
        if len(codes) == 0:
            try:
                from app.strategies.prosperity.tools.concept_builder import search_concept_stocks
                concept_stocks = search_concept_stocks(industry_name)
                if concept_stocks:
                    for s in concept_stocks:
                        codes.add(s["ts_code"])
                    logger.info(
                        f"搜索引擎概念板块匹配到 '{industry_name}': "
                        f"{len(concept_stocks)} 只股票"
                    )
            except Exception as e:
                logger.debug(f"搜索引擎概念查询 '{industry_name}' 失败: {e}")

    except Exception as e:
        logger.warning(f"行业分类查询 '{industry_name}' 失败: {e}")

    result = sorted(codes)
    _industry_cache[industry_name] = result
    logger.info(
        f"行业 '{industry_name}' → {len(result)} 只股票 "
        f"(stock_basic + 申万 + concept_detail + 同花顺 + 搜索引擎自建)"
    )
    return result


def clear_industry_cache() -> None:
    """清除行业分类缓存（用于强制刷新）"""
    global _industry_cache, _stock_basic_cache
    _industry_cache.clear()
    _stock_basic_cache = None


# 通用指标定义：key → (Tushare 字段名, 聚合方式)
# 注意：Tushare 字段名必须与 API 原始返回值一致（见 docs/TUSHARE_FIELDS.md）
UNIVERSAL_METRICS = {
    "revenue_growth": ("revenue_yoy", "percentile"),
    "gross_margin": ("grossprofit_margin", "median"),   # API 原始字段名 grossprofit_margin
    "roe": ("roe", "median"),
    "net_profit_growth": ("net_profit_yoy", "percentile"),
    "debt_ratio": ("debt_to_assets", "median"),          # API 原始字段名 debt_to_assets
}


def compute_industry_metrics(
    ts_codes: list[str],
    industry_name: str,
    period: str = None
) -> dict:
    """
    计算行业聚合指标。

    Args:
        ts_codes: 行业内所有股票的 ts_code 列表
        industry_name: 行业名称
        period: 财报周期，如 "2026Q1"

    Returns:
        {
            "industry": "半导体",
            "period": "2026Q1",
            "sample_size": 128,
            "metrics": {
                "revenue_growth": {"median": 18.5, "distribution": [5.2, 18.5, 32.1]},
                ...
            }
        }
    """
    # Step 1: 批量拉取 Tushare 数据
    print(f"         -> 拉取行业财务指标（{len(ts_codes)} 只）...", flush=True)
    raw_data = _fetch_batch_financials(ts_codes)

    if not raw_data:
        logger.warning(f"No financial data fetched for {industry_name}")
        return {
            "industry": industry_name,
            "period": period or "latest",
            "sample_size": 0,
            "metrics": {},
            "error": "No data available"
        }

    # Step 2: 逐指标计算分布
    metrics = {}
    for metric_key, (field_name, agg_method) in UNIVERSAL_METRICS.items():
        values = _extract_metric_values(raw_data, field_name)
        if not values:
            continue
        metrics[metric_key] = _compute_distribution(values)

    # Step 3: 计算额外衍生指标
    metrics["accelerated_ratio"] = _compute_acceleration(raw_data)
    metrics["fcf_positive_ratio"] = _compute_fcf_ratio(raw_data)

    return {
        "industry": industry_name,
        "period": period or "latest",
        "sample_size": len(raw_data),
        "metrics": metrics,
    }


# 模块级缓存：批量拉取的全量 fina_indicator DataFrame（供 _compute_acceleration 复用）
_cached_fina_full = None


def _fetch_batch_financials(ts_codes: list[str]) -> dict:
    """批量拉取财务数据 — 使用 Tushare 批量接口（逗号分隔 ts_code）

    优化前：逐只调 fina_indicator，200 只 × ~1.5s/次 = ~5 分钟
    优化后：批量请求
    """
    global _cached_fina_full

    codes = ts_codes[:200]
    if not codes:
        _cached_fina_full = None
        return {}

    try:
        from app.services.tushare_client import TushareClient
        client = TushareClient()

        import pandas as pd

        all_rows = []
        batch_size = 30  # 直连批量
        total_batches = (len(codes) + batch_size - 1) // batch_size

        for batch_idx in range(0, len(codes), batch_size):
            batch = codes[batch_idx:batch_idx + batch_size]
            ts_code_str = ",".join(batch)
            batch_num = batch_idx // batch_size + 1

            try:
                fina = client.get_fina_indicator(ts_code_str)
                if fina is not None and not fina.empty:
                    all_rows.append(fina)
                    print(f"            [{batch_num}/{total_batches}] 批次完成（{len(batch)} 只）", flush=True)
                else:
                    print(f"            [{batch_num}/{total_batches}] 批次无数据", flush=True)
            except Exception as e:
                logger.warning(
                    f"Batch {batch_num}/{total_batches} "
                    f"failed: {e}"
                )
                print(f"            [{batch_num}/{total_batches}] 批次失败: {e}", flush=True)

            # 批次间隔，避免触达限频
            if batch_idx + batch_size < len(codes):
                time.sleep(0.3)

        if not all_rows:
            _cached_fina_full = None
            return {}

        combined = pd.concat(all_rows, ignore_index=True)
        _cached_fina_full = combined  # 供 _compute_acceleration 复用
        logger.info(
            f"Batch fina_indicator: {len(codes)} ts_codes → "
            f"{len(combined)} rows across {len(all_rows)}/{total_batches} batches"
        )

        # 提取每只股票最新一期数据
        result = {}
        for ts_code, group in combined.groupby("ts_code"):
            group_sorted = group.sort_values("end_date", ascending=False)
            result[ts_code] = group_sorted.iloc[0].to_dict()

        return result
    except Exception as e:
        logger.error(f"Batch fetch failed: {e}")
        _cached_fina_full = None
        return {}


def _extract_metric_values(raw_data: dict, field_name: str) -> list[float]:
    """从批量数据中提取指定字段的数值列表"""
    values = []
    for ts_code, data in raw_data.items():
        val = data.get(field_name)
        if val is not None and isinstance(val, (int, float)):
            values.append(float(val))
    return values


def _compute_distribution(values: list[float]) -> dict:
    """计算数值分布：P25, P50 (median), P75 + 全量排序值（用于连续百分位打分）"""
    if not values:
        return {"median": 0, "distribution": [0, 0, 0], "sorted_values": []}

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def percentile(p):
        idx = int(n * p / 100)
        return sorted_vals[min(idx, n - 1)]

    return {
        "median": round(statistics.median(sorted_vals), 2),
        "distribution": [
            round(percentile(25), 2),
            round(percentile(50), 2),
            round(percentile(75), 2),
        ],
        "sorted_values": sorted_vals,
        "count": n,
    }


def get_stock_name_map() -> dict[str, str]:
    """获取 ts_code → 股票名称 映射（复用 stock_basic 缓存）

    Returns:
        {"000001.SZ": "平安银行", "600519.SH": "贵州茅台", ...}
    """
    global _stock_basic_cache
    if _stock_basic_cache is None:
        from app.services.tushare_client import TushareClient
        client = TushareClient()
        try:
            _stock_basic_cache = client.get_stock_basic()
        except Exception as e:
            logger.warning(f"Failed to fetch stock_basic for name map: {e}")
            return {}
    if _stock_basic_cache is not None and not _stock_basic_cache.empty:
        return dict(zip(_stock_basic_cache["ts_code"], _stock_basic_cache["name"]))
    return {}


def _compute_acceleration(raw_data: dict) -> dict:
    """
    计算营收增速环比加速的公司比例。

    复用 _fetch_batch_financials 缓存的 _cached_fina_full，
    比较每只股票的 revenue_yoy[t] vs revenue_yoy[t-1]：
    - 加速：最新期 > 上一期 + 1pp
    - 减速：最新期 < 上一期 - 1pp
    - 持平：其他

    Returns:
        {"ratio": 0.42, "accelerating": 42, "decelerating": 35, "flat": 23, "total": 100}
    """
    global _cached_fina_full

    if _cached_fina_full is None or _cached_fina_full.empty:
        return {"ratio": 0.0, "accelerating": 0, "decelerating": 0, "flat": 0, "total": 0}

    accelerating = 0
    decelerating = 0
    flat = 0

    try:
        for ts_code, group in _cached_fina_full.groupby("ts_code"):
            if len(group) < 2:
                continue

            group_sorted = group.sort_values("end_date", ascending=False)
            latest = group_sorted.iloc[0]
            prev = group_sorted.iloc[1]

            rev_yoy_0 = _safe_float(latest.get("revenue_yoy"))
            rev_yoy_1 = _safe_float(prev.get("revenue_yoy"))
            if rev_yoy_0 is None or rev_yoy_1 is None:
                continue

            diff = rev_yoy_0 - rev_yoy_1
            if diff > 1.0:
                accelerating += 1
            elif diff < -1.0:
                decelerating += 1
            else:
                flat += 1

    except Exception as e:
        logger.warning(f"Acceleration computation failed: {e}")

    valid = accelerating + decelerating + flat
    ratio = round(accelerating / valid, 3) if valid > 0 else 0.0
    return {
        "ratio": ratio,
        "accelerating": accelerating,
        "decelerating": decelerating,
        "flat": flat,
        "total": valid,
    }


def _safe_float(val) -> Optional[float]:
    """安全转 float，失败返回 None"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _compute_fcf_ratio(raw_data: dict) -> dict:
    """计算 FCF 为正的公司比例。FCF = 经营CF − CAPEX（近似）。"""
    positive = 0
    total = len(raw_data)
    if total == 0:
        return {"ratio": 0.0}

    for ts_code, data in raw_data.items():
        ocf = data.get("ocf", 0) or 0
        capex = data.get("capital_expend", 0) or 0
        if ocf - capex > 0:
            positive += 1

    return {"ratio": round(positive / total, 3) if total > 0 else 0.0}
