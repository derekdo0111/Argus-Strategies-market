"""Tier 2 行业数据爬取 — 确定性脚本，零 LLM 调用

按 source_registry.yaml 配置爬取行业协会/政府公开数据。
爬取失败返回空，不猜测不编造。
"""

import logging
import yaml
from pathlib import Path
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ── 信源爬取处理器 ────────────────────────────────────────────

SIA_MONTHLY_URL = "https://www.semiconductors.org/data-resources/market-data/"


def _crawl_sia_sales() -> Optional[dict[str, Any]]:
    """爬取 SIA 全球半导体月度销售数据。

    从 SIA 市场数据页面提取最新月度全球半导体销售额和 YoY 增速。
    页面结构变化时优雅降级返回 None。
    """
    try:
        resp = httpx.get(SIA_MONTHLY_URL, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 尝试从页面提取销售额数据表格
        # SIA 页面通常包含带有销售额数字的统计区块
        result: dict[str, Any] = {"source": "SIA 全球半导体销售报告", "url": SIA_MONTHLY_URL}

        # 查找可能的销售额数字（尝试多种 CSS 选择器）
        stat_blocks = soup.select("[class*='stat'], [class*='number'], [class*='figure']")
        sales_data: dict[str, str] = {}
        for block in stat_blocks[:10]:
            text = block.get_text(strip=True)
            if text and any(kw in text.lower() for kw in ["billion", "sales", "revenue", "growth"]):
                sales_data[text[:80]] = text

        if sales_data:
            result["data"] = sales_data
            result["status"] = "partial"
            logger.info(f"SIA crawl: extracted {len(sales_data)} data points")
        else:
            # 回退：提取页面关键段落作为结构化数据
            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")[:20]]
            meaningful = [p for p in paragraphs if len(p) > 30]
            if meaningful:
                result["data"] = {"raw_excerpts": meaningful[:5]}
                result["status"] = "fallback_text"
                logger.info("SIA crawl: fallback to text excerpts")
            else:
                result["status"] = "empty"
                logger.warning("SIA crawl: no extractable data found")

        return result

    except httpx.HTTPError as e:
        logger.warning(f"SIA crawl HTTP error: {e}")
        return None
    except Exception as e:
        logger.warning(f"SIA crawl unexpected error: {e}")
        return None


def _crawl_wsts_forecast() -> Optional[dict[str, Any]]:
    """爬取 WSTS 半导体市场预测（stub，待实现）。"""
    logger.debug("WSTS crawler stub: not yet implemented")
    return None


def _crawl_semi_orders() -> Optional[dict[str, Any]]:
    """爬取 SEMI 设备订单数据（stub，待实现）。"""
    logger.debug("SEMI orders crawler stub: not yet implemented")
    return None


# 信源名称 → 处理器映射
SOURCE_HANDLERS: dict[str, callable] = {
    "SIA 全球半导体销售报告": _crawl_sia_sales,
    "WSTS 半导体预测": _crawl_wsts_forecast,
    "SEMI 设备订单数据": _crawl_semi_orders,
}


def crawl_industry_sources(
    industry_name: str,
    source_registry: dict,
    output_dir: Path
) -> dict:
    """
    按 source_registry 配置爬取行业专属数据。

    Args:
        industry_name: 行业名称
        source_registry: 信源注册表（从 source_registry.yaml 加载）
        output_dir: 输出目录

    Returns:
        {source_name: {status: "success"|"failed", data: {...}, error: ...}}
    """
    industry_config = source_registry.get("industries", {}).get(industry_name, {})
    if not industry_config:
        logger.info(f"No source config for {industry_name}, using defaults")
        industry_config = source_registry.get("defaults", {})

    sources = industry_config.get("priority_sources", [])
    sources += industry_config.get("domestic_sources", [])

    results = {}
    for source_name in sources:
        try:
            data = _crawl_single_source(source_name, source_registry)
            results[source_name] = {
                "status": "success" if data else "empty",
                "data": data,
            }
        except Exception as e:
            logger.warning(f"Source {source_name} crawl failed: {e}")
            results[source_name] = {
                "status": "failed",
                "error": str(e),
            }

    # 写入文件
    if results:
        output_path = output_dir / f"02_crawled_{industry_name}.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(results, f, allow_unicode=True, default_flow_style=False)

    return results


def _crawl_single_source(source_name: str, registry: dict) -> Optional[dict]:
    """爬取单个信源。按信源名称路由到对应处理器。

    实现路径：
    1. 优先匹配 SOURCE_HANDLERS 中已实现的信源
    2. 未匹配的信源 → 返回 None（不猜测不编造）
    """
    handler = SOURCE_HANDLERS.get(source_name)
    if handler:
        try:
            return handler()
        except Exception as e:
            logger.warning(f"Handler for '{source_name}' raised: {e}")
            return None

    logger.debug(f"Source crawler no handler: {source_name}")
    return None
