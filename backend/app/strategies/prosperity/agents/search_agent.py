"""SearchAgent — 行业情报搜索

职责：
1. 搜索行业相关信息（Tavily + 定向信源）
2. 写入 raw/{industry}/01_search_YYYY-MM-DD.yaml
3. 整理搜索结果（归类、去重、标注来源可信度）

防幻觉：所有搜索原文存入 raw/，Agent 只做归类不编造。
"""

import logging
import yaml
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# 默认搜索关键词模板
DEFAULT_QUERIES = [
    "{industry} 行业景气度 2026",
    "{industry} 营收增速 利润增速 行业趋势",
    "{industry} 政策 补贴 产业规划",
    "{industry} 产能 库存 供需分析",
    "{industry} 龙头公司 竞争格局 市占率",
]


class SearchAgent:
    """行业情报搜索 Agent"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.tavily_api_key = getattr(settings, "TAVILY_API_KEY", "")

    def search(self, industry_name: str, session_id: int, history=None) -> dict:
        """
        搜索行业情报。

        Returns:
            {industry, session_id, timestamp, queries: [...], results: [...], summary: {...}, new_count, old_count}
        """
        logger.info(f"SearchAgent: searching for {industry_name}")

        # 确保 raw 目录存在
        raw_dir = self.data_dir / "raw" / industry_name
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 执行搜索
        all_results = []
        queries = [q.format(industry=industry_name) for q in DEFAULT_QUERIES]

        for query in queries:
            results = self._tavily_search(query)
            all_results.append({"query": query, "results": results})

        # 整理和去重（本次搜索内部）
        deduped = self._deduplicate(all_results)

        # 对比上次搜索做新旧分流
        new_results = deduped
        old_results = []
        if history and not history.is_first_study:
            prev_data = self._load_previous_search(industry_name)
            if prev_data:
                prev_urls = {r.get("url", "") for r in prev_data.get("results", []) if r.get("url")}
                new_results = [r for r in deduped if r.get("url", "") not in prev_urls]
                old_results = [r for r in deduped if r.get("url", "") in prev_urls]

        # 构建输出
        output = {
            "industry": industry_name,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "queries": queries,
            "new_count": len(new_results),
            "old_count": len(old_results),
            "results": new_results + old_results,  # 新在前，旧在后
            "summary": {
                "total_sources": len(deduped),
                "new_sources": len(new_results),
                "searches_performed": len(queries),
            },
        }

        # 写入文件
        date_str = datetime.now().strftime("%Y-%m-%d")
        output_path = raw_dir / f"01_search_{date_str}.yaml"
        with open(output_path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"SearchAgent: {len(new_results)} new + {len(old_results)} old results saved to {output_path}")
        return output

    def _load_previous_search(self, industry_name: str) -> Optional[dict]:
        """加载上次搜索结果（用于 URL 去重）"""
        raw_dir = self.data_dir / "raw" / industry_name
        if not raw_dir.exists():
            return None
        search_files = sorted(raw_dir.glob("01_search_*.yaml"), reverse=True)
        if not search_files:
            return None
        with open(search_files[0], "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _tavily_search(self, query: str, max_results: int = 10) -> list[dict]:
        """调用 Tavily Search API"""
        if not self.tavily_api_key:
            logger.warning("TAVILY_API_KEY not configured, skipping search")
            return []

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": "advanced",
                    "max_results": max_results,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("results", [])
            else:
                logger.warning(f"Tavily returned {resp.status_code}: {resp.text[:200]}")
                return []
        except Exception as e:
            logger.error(f"Tavily search failed for '{query}': {e}")
            return []

    def _deduplicate(self, all_results: list[dict]) -> list[dict]:
        """按 URL 去重，保留首次出现的结果"""
        seen_urls = set()
        deduped = []
        for query_block in all_results:
            for r in query_block.get("results", []):
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    deduped.append({
                        "title": r.get("title", ""),
                        "url": url,
                        "content": r.get("content", "")[:500],  # 截取前 500 字
                        "score": r.get("score", 0),
                        "query": query_block.get("query", ""),
                    })
        return deduped
