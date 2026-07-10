"""TrackAgent — 跟踪项提取 + 巡检（v4：全自动研究触发器）

跟踪项触发时机：
- 研究完成时自动提取
- 研究前预检（check_industry）

数据流：
  HypothesizeAgent.key_indicators (object[]) → TrackAgent 提取
    → tracking/watchlist/{行业}.yaml (权威源)
    → SQLite tracking_items 表 (查询缓存，单向同步)

watchlist/ 目录结构（v0.14.2 起每行业一个文件）：
  watchlist/电气设备.yaml:
    - indicator: 国家电网季度投资完成额
      industry: 电气设备
      frequency: quarterly
      search_query: ...
      ...
"""

import json
import logging
import re
import time
import yaml
import requests
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import (
    get_session as get_db_session,
    TrackingItem,
    Industry,
)

logger = logging.getLogger(__name__)

# v4: 可跟踪的假设状态（排除 unreachable/overturned）
TRACKABLE_STATUSES = {"confirmed", "partial", "unverified", "disputed"}

# 巡检频率 → 天数映射
FREQUENCY_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
}


class TrackAgent:
    """跟踪项 Agent (v4 — 全自动巡检)"""

    def __init__(self, data_dir: Path = None, rules_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self.bocha_api_key = getattr(settings, "BOCHA_API_KEY", "")
        self.tavily_api_key = getattr(settings, "TAVILY_API_KEY", "")
        self.llm_api_key = getattr(settings, "LLM_API_KEY", "")
        self.llm_api_base = getattr(settings, "LLM_API_BASE", "https://api.deepseek.com/v1")
        self.llm_model = getattr(settings, "LLM_MODEL", "deepseek-v4-flash")
        self._load_template()

    def _load_template(self) -> None:
        """加载 prompt 模板"""
        template_path = self.rules_dir / "prompts" / "track_extract_prompt.md"
        if template_path.exists():
            self.template = template_path.read_text(encoding="utf-8")
            logger.debug(f"Loaded track extract prompt template from {template_path}")
        else:
            logger.warning(f"Track extract prompt template not found: {template_path}")
            self.template = ""

    # ============================================================
    # 提取：研究完成 → watchlist
    # ============================================================

    def extract_tracking(self, industry_name: str, session_id: int, report: dict) -> dict:
        """从研究结果中提取 key_indicators → watchlist（行业分组格式，v4 新字段）"""
        logger.info(f"TrackAgent v4: extracting tracking items for {industry_name}")

        all_items = []

        hypotheses = report.get("hypotheses", [])
        for h in hypotheses:
            h_id = h.get("id", "")
            title = h.get("title", "")
            status = h.get("status", "unverified")

            # v4: 过滤状态 — 排除 unreachable/overturned
            if status not in TRACKABLE_STATUSES:
                continue

            key_indicators = h.get("key_indicators", [])
            if not key_indicators:
                continue

            for k in key_indicators:
                # v4: 兼容旧格式 string[] 和新格式 object[]
                if isinstance(k, dict):
                    name = k.get("name", "").strip()
                    frequency = k.get("frequency", "monthly")
                    search_query = k.get("search_query", name)
                    expected_direction = k.get("expected_direction", "unknown")
                else:
                    name = str(k).strip()
                    frequency = "monthly"
                    search_query = name
                    expected_direction = "unknown"

                if not name:
                    continue

                all_items.append({
                    "indicator": name,
                    "industry": industry_name,
                    "hypothesis_id": h_id,
                    "hypothesis_title": title,
                    "hypothesis_status": status,
                    "source_session": session_id,
                    "frequency": frequency,
                    "search_query": search_query,
                    "expected_direction": expected_direction,
                    "last_value": None,
                    "last_value_text": "",
                    "last_updated": datetime.utcnow().isoformat(),
                    "status": "pending",
                    "threshold": 0.20,
                    "trigger_condition": {
                        "type": "threshold",
                        "threshold": 0.20,
                        "direction": "bidirectional",
                    },
                    "history": [],
                })

        # 按 (行业, 指标) 复合 key 合并去重
        merged = self._merge_indicators(all_items)
        logger.info(f"TrackAgent v4: {len(all_items)} raw indicators → {len(merged)} merged (TRACKABLE: {TRACKABLE_STATUSES})")

        # 与现有 watchlist 合并：保留已有巡检值（last_value/last_value_text/history/last_updated）
        existing = self._load_industry_watchlist(industry_name)
        merged = self._merge_with_existing(merged, existing)
        logger.info(f"TrackAgent v4: after merge with existing → {len(merged)} items")

        # 写入 YAML 权威源
        watchlist_dir = self.data_dir / "tracking" / "watchlist"
        watchlist_dir.mkdir(parents=True, exist_ok=True)
        industry_file = watchlist_dir / f"{industry_name}.yaml"
        with open(industry_file, "w", encoding="utf-8") as f:
            yaml.dump(merged, f, allow_unicode=True, default_flow_style=False)

        # 单向同步到 SQLite
        self._sync_to_db(industry_name, merged, session_id)

        return {
            **report,
            "tracking_items": len(merged),
        }

    # ============================================================
    # 巡检：研究前预检（核心新增）
    # ============================================================

    def check_industry(self, industry_name: str) -> dict:
        """行业级巡检入口 — 研究前调用

        Returns:
            {industry, triggered_count, checked_count, triggered_items: [...], checked_items: [...], summary: str}
        """
        logger.info(f"TrackAgent v4: checking industry {industry_name}")

        # 1. 加载 watchlist
        items = self._load_industry_watchlist(industry_name)
        if not items:
            logger.info(f"TrackAgent: no watchlist for {industry_name}, skip check")
            return {
                "industry": industry_name,
                "triggered_count": 0,
                "checked_count": 0,
                "triggered_items": [],
                "checked_items": [],
                "summary": f"{industry_name}: 无跟踪项，跳过巡检。",
            }

        # 2. 筛选到期项
        due_items = self._filter_due(items)
        if not due_items:
            return {
                "industry": industry_name,
                "triggered_count": 0,
                "checked_count": 0,
                "triggered_items": [],
                "checked_items": [],
                "summary": f"{industry_name}: {len(items)} 项跟踪指标均未到期，跳过巡检。",
            }

        logger.info(f"TrackAgent: {len(due_items)}/{len(items)} items due for {industry_name}")

        # 3. 逐条巡检
        triggered = []
        checked = []
        for i, item in enumerate(due_items):
            logger.info(f"  [{i+1}/{len(due_items)}] checking: {item['indicator']}")
            try:
                result = self._check_single(item)
                if result.get("triggered"):
                    triggered.append(result)
                else:
                    checked.append(result)
            except Exception as e:
                logger.warning(f"  check failed for {item['indicator']}: {e}")
                item["last_updated"] = datetime.utcnow().isoformat()
                item["status"] = "error"
                checked.append({**item, "check_error": str(e)})

        # 4. 保存更新后的 YAML + 同步 SQLite
        self._save_industry_watchlist(industry_name, items)
        self._sync_to_db(industry_name, items)

        # 5. 构建摘要
        summary = self._build_summary(industry_name, triggered, checked, len(items))

        return {
            "industry": industry_name,
            "triggered_count": len(triggered),
            "checked_count": len(checked),
            "triggered_items": triggered,
            "checked_items": checked,
            "summary": summary,
        }

    def _load_industry_watchlist(self, industry_name: str) -> list[dict]:
        """加载单行业 watchlist YAML，兼容旧格式（自动补默认值）"""
        watchlist_dir = self.data_dir / "tracking" / "watchlist"
        industry_file = watchlist_dir / f"{industry_name}.yaml"

        if not industry_file.exists():
            return []

        with open(industry_file, "r", encoding="utf-8") as f:
            items = yaml.safe_load(f) or []

        # 旧格式兼容：补全缺失字段
        for item in items:
            if "frequency" not in item:
                item["frequency"] = "monthly"
            if "search_query" not in item:
                item["search_query"] = item.get("indicator", "")
            if "expected_direction" not in item:
                item["expected_direction"] = "unknown"
            if "history" not in item:
                item["history"] = []
            if "threshold" not in item:
                item["threshold"] = 0.20
            if "trigger_condition" not in item:
                item["trigger_condition"] = {
                    "type": "threshold",
                    "threshold": 0.20,
                    "direction": "bidirectional",
                }
            if "last_value_text" not in item:
                item["last_value_text"] = ""

        return items

    def _save_industry_watchlist(self, industry_name: str, items: list[dict]) -> None:
        """保存单行业 watchlist YAML"""
        watchlist_dir = self.data_dir / "tracking" / "watchlist"
        watchlist_dir.mkdir(parents=True, exist_ok=True)
        industry_file = watchlist_dir / f"{industry_name}.yaml"
        with open(industry_file, "w", encoding="utf-8") as f:
            yaml.dump(items, f, allow_unicode=True, default_flow_style=False)

    def _filter_due(self, items: list[dict]) -> list[dict]:
        """筛选到期项：now - last_updated >= frequency 对应天数

        特殊规则：
        - last_value 为 None 且 last_value_text 为空 → 从未巡检过 → 始终到期（seed baseline）
        - last_value 为 None 但 last_value_text 有内容 → 已巡检过但无数值（定性指标）→ 按时钟规则
        - 因为有值 → 按时钟规则"""
        now = datetime.utcnow()
        due = []
        for item in items:
            # 首次巡检：last_value 和 last_value_text 都为空 → seed needed
            if item.get("last_value") is None and not item.get("last_value_text", ""):
                due.append(item)
                continue

            last_updated_str = item.get("last_updated", "")
            if not last_updated_str:
                due.append(item)
                continue

            try:
                last_updated = datetime.fromisoformat(last_updated_str)
            except (ValueError, TypeError):
                due.append(item)
                continue

            frequency = item.get("frequency", "monthly")
            days = FREQUENCY_DAYS.get(frequency, 30)
            if (now - last_updated).days >= days:
                due.append(item)

        return due

    # ============================================================
    # 单条巡检：网络搜索 → LLM → 对比
    # ============================================================

    def _check_single(self, item: dict) -> dict:
        """单条指标巡检：网络搜索（Bocha/Tavily）→ LLM 提取值 → 触发判定"""
        indicator = item.get("indicator", "")
        search_query = item.get("search_query", indicator)
        last_value = item.get("last_value")
        last_value_text = item.get("last_value_text", "")
        expected_direction = item.get("expected_direction", "unknown")

        # Step 1: 网络搜索（Bocha 优先，Tavily 降级）
        search_results = self._web_search(search_query, max_results=5)

        # Step 2: LLM 从搜索结果中提取结构化值
        snippets = ""
        for r in search_results:
            snippets += f"- [{r.get('title', '')}]\n  {r.get('content', '')[:300]}\n  URL: {r.get('url', '')}\n\n"

        check_result = self._call_llm_extract(indicator, search_query, snippets,
                                                last_value, last_value_text, expected_direction)

        # Step 3: 触发判定
        triggered = self._should_trigger(item, check_result)

        # Step 4: 更新 item
        item["last_value"] = check_result.get("value_numeric")
        item["last_value_text"] = check_result.get("current_value", "")
        item["last_updated"] = datetime.utcnow().isoformat()
        item.setdefault("history", []).append({
            "timestamp": datetime.utcnow().isoformat(),
            "value": check_result.get("current_value", ""),
            "value_numeric": check_result.get("value_numeric"),
            "trend": check_result.get("trend", "unclear"),
            "triggered": triggered,
        })

        # 只保留最近 10 条历史
        if len(item["history"]) > 10:
            item["history"] = item["history"][-10:]

        if triggered:
            item["status"] = "triggered"
        else:
            item["status"] = "checked"

        return {
            "indicator": indicator,
            "industry": item.get("industry", ""),
            "check_result": check_result,
            "triggered": triggered,
            "change_summary": self._format_change(item, check_result, triggered),
        }

    def _detect_engine(self) -> str:
        """检测使用哪个搜索引擎: bocha > tavily > none"""
        if self.bocha_api_key:
            return "bocha"
        if self.tavily_api_key:
            return "tavily"
        return "none"

    def _web_search(self, query: str, max_results: int = 5) -> list[dict]:
        """搜索引擎分发：Bocha 优先，Tavily 降级"""
        engine = self._detect_engine()
        if engine == "bocha":
            return self._bocha_search(query, max_results)
        elif engine == "tavily":
            return self._tavily_search(query, max_results)
        else:
            logger.warning("No search API key configured! Set BOCHA_API_KEY in .env")
            return []

    def _bocha_search(self, query: str, max_results: int = 5) -> list[dict]:
        """调用 Bocha Web Search API（v0.23: 巡检搜索）"""
        if not self.bocha_api_key:
            return []

        try:
            resp = requests.post(
                "https://api.bochaai.com/v1/web-search",
                headers={
                    "Authorization": f"Bearer {self.bocha_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "freshness": "oneYear",
                    "summary": True,
                    "count": max_results,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"Bocha returned {resp.status_code}: {resp.text[:200]}")
                return []

            data = resp.json()
            web_pages = data.get("data", {}).get("webPages", {}).get("value", [])

            results = []
            for page in web_pages:
                content = page.get("summary", "") or page.get("snippet", "")
                results.append({
                    "title": page.get("name", ""),
                    "url": page.get("url", ""),
                    "content": content[:500],
                })
            return results
        except Exception as e:
            logger.error(f"Bocha search failed for '{query}': {e}")
            return []

    def _tavily_search(self, query: str, max_results: int = 5) -> list[dict]:
        """调用 Tavily Search API（v0.23: 降级为备用）"""
        if not self.tavily_api_key:
            logger.warning("TAVILY_API_KEY not configured, skipping web search")
            return []

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",  # 轻量搜索
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

    def _call_llm_extract(self, indicator: str, search_query: str, snippets: str,
                          last_value, last_value_text: str, expected_direction: str) -> dict:
        """调用 LLM 从搜索结果中提取指标的最新值（temperature=0，结构化输出）"""
        if not self.llm_api_key:
            logger.warning("LLM_API_KEY not configured, returning empty check result")
            return {
                "current_value": "",
                "value_numeric": None,
                "trend": "unclear",
                "confidence": "low",
                "source_url": "",
                "source_date": "",
                "summary": "LLM 未配置，无法提取。",
            }

        last_info = f"上次记录值: {last_value_text} (数值: {last_value})" if last_value_text else "首次巡检，无上次记录值"

        prompt = self.template.format(
            indicator=indicator,
            search_query=search_query,
            last_info=last_info,
            expected_direction=expected_direction,
            snippets=snippets if snippets else "（无搜索结果）",
        )

        try:
            resp = requests.post(
                f"{self.llm_api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.llm_model,
                    "messages": [
                        {"role": "system", "content": "你是数据检索助手。只输出要求的 JSON 格式，不要其他内容。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,  # 确定性输出，数值提取不可幻觉
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=60,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return self._parse_check_result(content)
            else:
                logger.warning(f"LLM returned {resp.status_code}: {resp.text[:200]}")
                return self._empty_check_result()
        except Exception as e:
            logger.error(f"LLM extract failed for '{indicator}': {e}")
            return self._empty_check_result()

    def _parse_check_result(self, llm_output: str) -> dict:
        """解析 LLM 返回的 JSON"""
        default = self._empty_check_result()

        # 尝试提取 JSON
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output

        # 尝试找到第一个 JSON 对象
        obj_match = re.search(r"\{[\s\S]*\}", json_str)
        if obj_match:
            json_str = obj_match.group(0)

        try:
            result = json.loads(json_str)
            # 标准化字段
            return {
                "current_value": str(result.get("current_value", "")),
                "value_numeric": result.get("value_numeric"),
                "trend": result.get("trend", "unclear"),
                "confidence": result.get("confidence", "low"),
                "source_url": result.get("source_url", ""),
                "source_date": result.get("source_date", ""),
                "summary": result.get("summary", ""),
            }
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse LLM check result: {llm_output[:200]}")
            return default

    def _empty_check_result(self) -> dict:
        return {
            "current_value": "",
            "value_numeric": None,
            "trend": "unclear",
            "confidence": "low",
            "source_url": "",
            "source_date": "",
            "summary": "数据提取失败。",
        }

    # ============================================================
    # 触发判定
    # ============================================================

    def _should_trigger(self, item: dict, check_result: dict) -> bool:
        """判断是否触发研究"""
        # 1. LLM 置信度低 → 不触发（模糊信号不值得跑管道）
        if check_result.get("confidence") == "low":
            return False

        # 2. 暂无上次值 → 不触发（基准线不存在，无法对比）
        last_value = item.get("last_value")
        if last_value is None:
            return False

        # 3. 数值类指标：变化超阈值
        current_numeric = check_result.get("value_numeric")
        if current_numeric is not None and last_value != 0:
            delta = abs(current_numeric - last_value) / abs(last_value)
            if delta > item.get("threshold", 0.20):
                return True

        # 4. 方向反转：预期 rising 但实际 falling，或反之
        expected = item.get("expected_direction", "unknown")
        actual = check_result.get("trend", "unclear")
        if actual == "falling" and expected == "rising":
            return True
        if actual == "rising" and expected == "falling":
            return True

        return False

    def _format_change(self, item: dict, check_result: dict, triggered: bool) -> str:
        """格式化变化摘要"""
        indicator = item.get("indicator", "")
        if not triggered:
            return f"{indicator}: 无明显变化。"

        current = check_result.get("current_value", "?")
        last_text = item.get("last_value_text", "首次")
        expected = item.get("expected_direction", "unknown")
        actual = check_result.get("trend", "unclear")

        parts = [f"{indicator}:"]
        if last_text:
            parts.append(f"上次: {last_text} → 当前: {current}")
        if expected != "unknown" and actual != expected:
            dir_map = {"rising": "上升", "falling": "下降", "stable": "平稳"}
            parts.append(f"⚠️ 方向反转: 预期{dir_map.get(expected, expected)}，实际{dir_map.get(actual, actual)}")

        return " | ".join(parts)

    # ============================================================
    # 摘要构建
    # ============================================================

    def _build_summary(self, industry_name: str, triggered: list[dict],
                       checked: list[dict], total: int) -> str:
        """构建巡检摘要"""
        lines = [f"## {industry_name} 巡检摘要\n"]
        lines.append(f"- 总跟踪项: {total}")
        lines.append(f"- 本次巡检: {len(checked) + len(triggered)} 项")
        lines.append(f"- 触发预警: {len(triggered)} 项")
        lines.append(f"- 正常: {len(checked)} 项")

        if triggered:
            lines.append(f"\n### ⚠️ 触发预警项")
            for t in triggered:
                lines.append(f"- {t.get('change_summary', t.get('indicator', '?'))}")
        else:
            lines.append(f"\n✅ 所有巡检指标正常，无需触发新研究。")

        return "\n".join(lines)

    # ============================================================
    # 数据库同步：YAML → SQLite 单向
    # ============================================================

    def _sync_to_db(self, industry_name: str, items: list[dict], session_id: int = None) -> None:
        """单向同步：YAML → SQLite（先删该行业旧记录，再写入新记录）"""
        import json as _json
        db = get_db_session()
        try:
            # 查找 industry_id
            industry = db.query(Industry).filter_by(name=industry_name).first()
            if not industry:
                logger.warning(f"TrackAgent._sync_to_db: industry '{industry_name}' not found in DB")
                return
            industry_id = industry.id

            # 删除该行业的旧 tracking_items
            db.query(TrackingItem).filter_by(industry_id=industry_id).delete()
            db.flush()

            # 逐条写入新记录
            for item in items:
                history_json = _json.dumps(item.get("history", []), ensure_ascii=False) if item.get("history") else None

                # 计算 check_date
                frequency = item.get("frequency", "monthly")
                days = FREQUENCY_DAYS.get(frequency, 30)
                check_date = datetime.utcnow() + timedelta(days=days)

                db_item = TrackingItem(
                    industry_id=industry_id,
                    item=f"[{item.get('indicator', '')}] {', '.join(item.get('hypothesis_ids', []))}",
                    trigger_condition=str(item.get("trigger_condition", "")),
                    check_date=check_date,
                    status=item.get("status", "pending"),
                    source_session_id=session_id or item.get("source_session"),
                    # v4 新字段
                    indicator_name=item.get("indicator", ""),
                    frequency=item.get("frequency", "monthly"),
                    last_value=item.get("last_value"),
                    last_value_text=item.get("last_value_text", ""),
                    search_query=item.get("search_query", ""),
                    expected_direction=item.get("expected_direction", "unknown"),
                    history_json=history_json,
                )
                db.add(db_item)

            db.commit()
            logger.info(f"TrackAgent._sync_to_db: {len(items)} items synced for {industry_name}")
        except Exception as e:
            db.rollback()
            logger.error(f"TrackAgent._sync_to_db failed for {industry_name}: {e}")
        finally:
            db.close()

    # ============================================================
    # 合并去重
    # ============================================================

    def _merge_indicators(self, items: list[dict]) -> list[dict]:
        """按 (行业, 指标) 复合 key 合并去重（v4 增加新字段合并逻辑）"""
        merged = defaultdict(lambda: {
            "indicator": "",
            "industry": "",
            "hypothesis_ids": [],
            "hypothesis_titles": [],
            "hypothesis_statuses": [],
            "source_session": None,
            "frequency": "monthly",
            "search_query": "",
            "expected_direction": "unknown",
            "last_value": None,
            "last_value_text": "",
            "last_updated": "",
            "status": "pending",
            "threshold": 0.20,
            "trigger_condition": {
                "type": "threshold",
                "threshold": 0.20,
                "direction": "bidirectional",
            },
            "history": [],
        })

        for item in items:
            key = (item["indicator"], item.get("industry", ""))
            entry = merged[key]
            entry["indicator"] = key[0]
            entry["industry"] = key[1]
            entry["hypothesis_ids"].append(item.get("hypothesis_id", ""))
            entry["hypothesis_titles"].append(item.get("hypothesis_title", ""))
            entry["hypothesis_statuses"].append(item.get("hypothesis_status", ""))
            entry["source_session"] = item.get("source_session")

            # v4 新字段：首次优先，后续相同指标取最频繁的 frequency
            if entry["search_query"] == "":
                entry["search_query"] = item.get("search_query", key[0])
            if entry["frequency"] == "monthly" and item.get("frequency") in ("daily", "weekly"):
                entry["frequency"] = item["frequency"]  # 更频繁的周期优先
            if entry["expected_direction"] == "unknown":
                entry["expected_direction"] = item.get("expected_direction", "unknown")

            entry["last_updated"] = item.get("last_updated", "")
            entry["last_value"] = item.get("last_value")
            entry["last_value_text"] = item.get("last_value_text", "")
            if item.get("history"):
                entry["history"].extend(item["history"])

        # 清理 hypotheses 列表内去重
        for entry in merged.values():
            entry["hypothesis_ids"] = list(dict.fromkeys(entry["hypothesis_ids"]))
            entry["hypothesis_titles"] = list(dict.fromkeys(entry["hypothesis_titles"]))
            entry["hypothesis_statuses"] = list(dict.fromkeys(entry["hypothesis_statuses"]))

        return list(merged.values())

    def _merge_with_existing(self, new_items: list[dict], existing_items: list[dict]) -> list[dict]:
        """将新生成的 items 与已有 watchlist 合并。

        规则：
        - 新 items 的假设信息（hypothesis_ids/titles/statuses）覆盖旧值
        - 已有 items 的巡检值（last_value/last_value_text/history/last_updated）保留
        - 旧 items 中不再出现的指标 → 保留（可能是手动添加的）
        """
        if not existing_items:
            return new_items

        # 构建 existing index: indicator → item
        existing_by_name = {}
        for item in existing_items:
            key = item.get("indicator", "")
            if key:
                existing_by_name[key] = item

        # 合并
        result = []
        new_names = set()
        for item in new_items:
            name = item.get("indicator", "")
            new_names.add(name)
            if name in existing_by_name:
                old = existing_by_name[name]
                # 保留旧巡检值
                item["last_value"] = old.get("last_value")
                item["last_value_text"] = old.get("last_value_text", "")
                item["last_updated"] = old.get("last_updated", "")
                item["status"] = old.get("status", "pending")
                item["history"] = old.get("history", [])
                # 新假设信息覆盖旧值
                item["hypothesis_ids"] = item.get("hypothesis_ids", [])
                item["hypothesis_titles"] = item.get("hypothesis_titles", [])
                item["hypothesis_statuses"] = item.get("hypothesis_statuses", [])
            result.append(item)

        # 保留旧 items 中不再出现的指标
        for name, old_item in existing_by_name.items():
            if name not in new_names:
                result.append(old_item)

        return result

    # ============================================================
    # 旧版 check_watchlist（保留，向后兼容）
    # ============================================================

    def check_watchlist(self) -> list[dict]:
        """巡检 watchlist/ 目录，返回到期项目（带行业标注）— 旧版保留"""
        watchlist_dir = self.data_dir / "tracking" / "watchlist"
        if not watchlist_dir.exists():
            return []

        data = self._load_watchlist(watchlist_dir)
        now = datetime.utcnow()
        due = []
        for industry, items in data.items():
            for item in items:
                check_date_str = item.get("check_date", "")
                if check_date_str:
                    try:
                        check_date = datetime.fromisoformat(check_date_str)
                        if check_date <= now and item.get("status") == "pending":
                            item["_industry"] = industry
                            due.append(item)
                    except (ValueError, TypeError):
                        pass
        return due

    def _load_watchlist(self, watchlist_dir: Path) -> dict:
        """加载 watchlist/ 目录（v0.14.2+ 每行业一个文件）"""
        if watchlist_dir.is_file():
            return self._load_watchlist_legacy(watchlist_dir)

        if not watchlist_dir.exists() or not watchlist_dir.is_dir():
            return {}
        result = {}
        for yaml_file in sorted(watchlist_dir.glob("*.yaml")):
            industry_name = yaml_file.stem
            with open(yaml_file, "r", encoding="utf-8") as f:
                items = yaml.safe_load(f) or []
            if items:
                result[industry_name] = items
        return result

    def _load_watchlist_legacy(self, file_path: Path) -> dict:
        """加载旧格式 watchlist.yaml"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        if "items" not in data:
            return data

        logger.info("TrackAgent: migrating watchlist.yaml from flat items to industry-grouped format")
        grouped = {}
        for item in data.get("items", []):
            industry = item.get("industry", "未知行业")
            if industry not in grouped:
                grouped[industry] = []
            grouped[industry].append(item)
        return grouped
