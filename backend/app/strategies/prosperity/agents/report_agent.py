"""ReportAgent — 报告生成 + 股池

产出：
1. wiki/synthesis/{日期}-{行业}景气分析.md
2. {industry}/stock_pool.yaml
3. 更新 wiki/industries/{行业}.md
"""

import logging
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.tools.stock_screener import score_stocks
from app.strategies.prosperity.tools.industry_metrics import (
    compute_industry_metrics,
    get_industry_ts_codes,
    get_stock_name_map,
)
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)

PROSPERITY_LEVELS = {
    "高景气": "🔥",
    "景气": "✅",
    "弱景气": "⚠️",
    "不景气": "❄️",
}


class ReportAgent:
    """报告生成 Agent"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR

    def generate(self, industry_name: str, session_id: int, counter_result: dict, study_count: int = 1) -> dict:
        """生成行业景气报告 + 股池"""
        logger.info(f"ReportAgent: generating report for {industry_name}")

        hypotheses = counter_result.get("hypotheses", [])

        # 1. 判断景气度
        level, level_icon = self._assess_prosperity(hypotheses)

        # 2. 生成股池
        stock_pool = self._generate_stock_pool(industry_name)

        # 3. 写入综合报告
        date_str = datetime.now().strftime("%Y%m%d")
        report_md = self._render_report(industry_name, level, level_icon, hypotheses, stock_pool)

        synthesis_dir = self.data_dir / "wiki" / "synthesis"
        synthesis_dir.mkdir(parents=True, exist_ok=True)
        report_path = synthesis_dir / f"{date_str}-{industry_name}景气分析.md"
        report_path.write_text(report_md, encoding="utf-8")

        # 4. 写入股池 YAML
        pool_path = self.data_dir / "raw" / industry_name / "stock_pool.yaml"
        pool_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pool_path, "w", encoding="utf-8") as f:
            yaml.dump(stock_pool, f, allow_unicode=True)

        # 5. 更新行业总览页
        self._update_industry_page(industry_name, level, level_icon, report_path, study_count)

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"ReportAgent: {industry_name} → {level}")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "prosperity_level": level,
            "report_path": str(report_path.relative_to(self.data_dir)),
            "pool_path": str(pool_path.relative_to(self.data_dir)),
            "stock_count": len(stock_pool),
        }

    def _assess_prosperity(self, hypotheses: list[dict]) -> tuple:
        """根据假设验证结果判断景气度（v2：只统计非 unreachable 假设）"""
        active = [h for h in hypotheses if h.get("status") != "unreachable"]
        confirmed = sum(1 for h in active if h.get("status") == "confirmed")
        partial = sum(1 for h in active if h.get("status") == "partial")
        overturned = sum(1 for h in active if h.get("status") == "overturned")

        if confirmed >= 2 and overturned == 0:
            return "高景气", "🔥"
        elif confirmed >= 1 or partial >= 2:
            return "景气", "✅"
        elif overturned <= 1:
            return "弱景气", "⚠️"
        else:
            return "不景气", "❄️"

    def _generate_stock_pool(self, industry_name: str) -> list[dict]:
        """生成行业股池"""
        try:
            ts_codes = get_industry_ts_codes(industry_name)
            if ts_codes:
                metrics = compute_industry_metrics(ts_codes[:200], industry_name)
                name_map = get_stock_name_map()
                return score_stocks(ts_codes[:50], metrics, name_map=name_map)[:20]  # Top 20
        except Exception as e:
            logger.warning(f"Stock pool generation failed: {e}")
        return []

    def _render_report(self, industry_name, level, icon, hypotheses, stock_pool) -> str:
        """生成叙事体裁报告（v2：按推理链组织）"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# {industry_name}行业景气分析",
            f"",
            f"> **综合评级: {icon} {level}** | 生成日期: {date_str}",
            f"",
        ]

        # 按层级分组
        by_level = {0: [], 1: [], 2: [], 3: []}
        for h in hypotheses:
            lv = h.get("chain_level", 0)
            by_level.setdefault(lv, []).append(h)

        status_map = {
            "confirmed": "✅", "partial": "⚠️",
            "disputed": "❌", "unverified": "🔍", "overturned": "⚰️", "unreachable": "🚫"
        }

        # --- 推理链概览图 ---
        lines.extend(["## 推理链概览", ""])
        lines.append("```mermaid")
        lines.append("graph TD")
        for level_num in range(4):
            for h in by_level.get(level_num, []):
                h_id = h.get("id", "?")
                emoji = status_map.get(h.get("status", ""), "")
                safe_title = h.get("title", "")[:20].replace('"', "'")
                lines.append(f"    {h_id}[\"{emoji} {safe_title}\"]")
        # 箭头
        for h in hypotheses:
            for up_id in h.get("derives_from", []):
                h_id = h.get("id", "")
                if h_id:
                    lines.append(f"    {up_id} --> {h_id}")
        lines.append("```")
        lines.append("")

        # --- 逐层展开 ---
        level_names = {0: "📊 现状诊断", 1: "🔮 一阶推演", 2: "⚖️ 二阶推演（矛盾与拐点）", 3: "🎯 投资落点"}
        for level_num in range(4):
            level_hyps = by_level.get(level_num, [])
            if not level_hyps:
                continue
            lines.extend([f"## {level_names.get(level_num, f'L{level_num}')}", ""])
            for h in level_hyps:
                emoji = status_map.get(h.get("status", ""), "")
                title = h.get("title", "")
                statement = h.get("statement", "")
                reasoning = h.get("reasoning", "")
                confidence = h.get("confidence", "")
                derives = h.get("derives_from", [])
                time_horizon = h.get("time_horizon", "")
                implication = h.get("investment_implication", "")
                key_indicators = h.get("key_indicators", [])

                lines.append(f"### {emoji} {title}")
                lines.append(f"")
                lines.append(f"> **ID**: `{h.get('id', '')}` | 置信度: {confidence}")
                if derives:
                    lines.append(f"> 上游: {' → '.join(f'`{d}`' for d in derives)}")
                if time_horizon:
                    lines.append(f"> ⏱️ 时间窗口: {time_horizon}")
                lines.append(f"")
                lines.append(f"**陈述**: {statement}")
                lines.append(f"")
                lines.append(f"**推理链**: {reasoning}")
                lines.append(f"")

                if key_indicators:
                    lines.append(f"**跟踪指标**:")
                    for k in key_indicators:
                        lines.append(f"- {k}")
                    lines.append(f"")

                if implication:
                    lines.append(f"**投资含义**: {implication}")
                    lines.append(f"")

        # --- 假设验证总览表 ---
        lines.extend(["## 验证总览", ""])
        lines.append("| 层级 | ID | 假设 | 状态 | 上游 | 时间窗口 |")
        lines.append("|------|-----|------|------|------|------|")
        for h in hypotheses:
            emoji = status_map.get(h.get("status", ""), "")
            derives_str = ", ".join(h.get("derives_from", []))
            lines.append(
                f"| L{h.get('chain_level', '?')} | {h.get('id', '')} | {h.get('title', '')} | {emoji} {h.get('status', '')} | {derives_str} | {h.get('time_horizon', '')} |"
            )

        # --- 股池 ---
        if stock_pool:
            lines.extend(["", "## 行业股池 (Top 10)", ""])
            lines.append("| 排名 | 股票 | 总分 |")
            lines.append("|------|------|------|")
            for s in stock_pool[:10]:
                lines.append(f"| {s.get('rank', '-')} | {s.get('name', s.get('ts_code', '-'))} | {s.get('score_total', '-')} |")

        return "\n".join(lines)

    def _update_industry_page(self, industry_name, level, icon, report_path, study_count=1):
        """更新 wiki/industries/{行业}.md — 去重：同日同评级替换不追加"""
        industry_dir = self.data_dir / "wiki" / "industries"
        industry_dir.mkdir(parents=True, exist_ok=True)
        page_path = industry_dir / f"{industry_name}.md"

        today = datetime.now().strftime("%Y-%m-%d")
        new_line = f"- [{today}] {icon} {level} — [查看报告](../synthesis/{report_path.name}) (*第{study_count}次研究*)"

        if page_path.exists():
            content = page_path.read_text(encoding="utf-8")

            # 去重：同日期同评级 → 替换最新行
            existing_lines = content.split("\n")
            rating_indices = [
                (i, line) for i, line in enumerate(existing_lines)
                if line.startswith("- [") and re.search(r"\[(\d{4}-\d{2}-\d{2})\]", line)
            ]

            if rating_indices:
                first_i, first_line = rating_indices[0]
                first_date_match = re.search(r"\[(\d{4}-\d{2}-\d{2})\]", first_line)
                if first_date_match and first_date_match.group(1) == today:
                    level_match = re.search(r"\]\s*(\S+)\s*(\S+)", first_line)
                    if level_match and level_match.group(2) == level:
                        # 同日同评级 → 替换
                        existing_lines[first_i] = new_line
                        content = "\n".join(existing_lines)
                        page_path.write_text(content, encoding="utf-8")
                        logger.info(f"ReportAgent: replaced duplicate rating line for {industry_name}")
                        return

            # 不同日期或不同评级 → 追加到头部
            content = f"{new_line}\n{content}"
        else:
            content = f"""# {industry_name}

## 景气评级历史
{new_line}

## 行业概览
（待后续研究更新）
"""

        page_path.write_text(content, encoding="utf-8")
