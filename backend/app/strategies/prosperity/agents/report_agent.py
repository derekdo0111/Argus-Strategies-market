"""ReportAgent — 报告生成（v3：加权信号聚合评级）

产出：
1. wiki/synthesis/{日期}-{行业}景气分析.md
2. 更新 wiki/industries/{行业}.md

v3 变更：股池由 ScreeningAgent 产出，ReportAgent 不再自行生成股池。
评级公式从计数改为加权信号聚合（sentiment × 层级权重 × causality 折扣）。
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)

PROSPERITY_LEVELS = {
    "高景气": "🔥",
    "景气": "✅",
    "弱景气": "⚠️",
    "不景气": "❄️",
}

# 评级阈值（v3 加权信号聚合）
SIGNAL_THRESHOLDS = {
    "高景气": 3.0,
    "景气": 1.5,
    "弱景气": 0.0,
    # ≤ 0 → 不景气
}

# 层级权重
LEVEL_WEIGHTS = {0: 1.0, 1: 0.8, 2: 0.7, 3: 0.5}

# causality_strength 折扣
CAUSALITY_DISCOUNT = {"strong": 1.0, "moderate": 0.7, "weak": 0.4, "broken": 0.0}

# 信号值映射（v0.22: +weak_disputed）
SIGNAL_MAP = {
    # (sentiment, status) → signal_value
    ("positive", "confirmed"): 1.0,
    ("positive", "partial"): 0.6,       # 部分验证的正向信号
    ("positive", "weak_disputed"): 0.3,  # v0.22: 弱反例·降级不切链·微弱正向
    ("positive", "disputed"): -0.5,      # 保留兼容（存量）
    ("positive", "unverified"): 0.3,     # 待验证的正向信号（折扣）
    ("negative", "confirmed"): -1.0,
    ("negative", "partial"): -0.5,      # 部分验证的负向信号
    ("negative", "weak_disputed"): -0.2, # v0.22: 弱反例·微弱负向
    ("negative", "disputed"): 0.5,       # 保留兼容（存量）
    ("negative", "unverified"): -0.3,    # 待验证的负向信号（折扣）
    ("neutral", "confirmed"): 0.3,
    ("neutral", "partial"): 0.1,        # 中性+部分 → 微弱信号
    ("neutral", "weak_disputed"): 0.0,   # v0.22: 弱反例·中性无信号
    ("neutral", "disputed"): -0.2,       # 保留兼容（存量）
    ("neutral", "unverified"): 0.0,
}


class ReportAgent:
    """报告生成 Agent（v3）"""

    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR

    def generate(self, industry_name: str, session_id: int, verification: dict, screening_result: dict, study_count: int = 1) -> dict:
        """生成行业景气报告（v3：使用 ScreeningAgent 股池 + 加权信号聚合评级）"""
        logger.info(f"ReportAgent v3: generating report for {industry_name}")

        hypotheses = verification.get("hypotheses", [])
        stock_pool = screening_result.get("stock_pool", [])

        # 1. 判断景气度（加权信号聚合）
        level, level_icon, signal = self._assess_prosperity(hypotheses)

        # 2. 写入综合报告
        date_str = datetime.now().strftime("%Y%m%d")
        report_md = self._render_report(industry_name, level, level_icon, hypotheses, stock_pool, signal)

        synthesis_dir = self.data_dir / "wiki" / "synthesis"
        synthesis_dir.mkdir(parents=True, exist_ok=True)
        report_path = synthesis_dir / f"{date_str}-{industry_name}景气分析.md"
        report_path.write_text(report_md, encoding="utf-8")

        # 3. 更新行业总览页
        self._update_industry_page(industry_name, level, level_icon, report_path, study_count)

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"ReportAgent v3: {industry_name} → {level} (signal={signal:.2f})")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "prosperity_level": level,
            "rating": level,
            "signal_strength": round(signal, 2),
            "report_path": str(report_path.relative_to(self.data_dir)),
            "stock_count": len(stock_pool),
        }

    def _assess_prosperity(self, hypotheses: list[dict]) -> tuple:
        """加权信号聚合评级（v3）

        景气信号 = Σ(信号值 × 层级权重 × causality折扣)
        """
        # 过滤 unreachable + overturned（v0.10.0: overturned 也排除评级）
        active = [h for h in hypotheses if h.get("status") not in ("unreachable", "overturned")]

        total_signal = 0.0
        for h in active:
            status = h.get("status", "unverified")
            sentiment = h.get("sentiment", "neutral")
            chain_level = h.get("chain_level", 0)
            causality = h.get("causality_strength", "moderate")

            # 信号值（v0.10.0: 折扣已内嵌在 SIGNAL_MAP，移除双重惩罚）
            key = (sentiment, status)
            signal = SIGNAL_MAP.get(key, 0.0)

            # 层级权重
            level_w = LEVEL_WEIGHTS.get(chain_level, 0.5)

            # causality 折扣
            causality_d = CAUSALITY_DISCOUNT.get(causality, 0.7)
            if status == "overturned":
                causality_d = 0.0

            total_signal += signal * level_w * causality_d

        # 阈值映射
        if total_signal > SIGNAL_THRESHOLDS["高景气"]:
            return "高景气", "🔥", total_signal
        elif total_signal > SIGNAL_THRESHOLDS["景气"]:
            return "景气", "✅", total_signal
        elif total_signal > SIGNAL_THRESHOLDS["弱景气"]:
            return "弱景气", "⚠️", total_signal
        else:
            return "不景气", "❄️", total_signal

    def _render_report(self, industry_name, level, icon, hypotheses, stock_pool, signal=0) -> str:
        """生成叙事体裁报告（v3：按推理链组织，含加权信号）"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        lines = [
            f"# {industry_name}行业景气分析",
            f"",
            f"> **综合评级: {icon} {level}** | 信号强度: {signal:.2f} | 生成日期: {date_str}",
            f"",
        ]

        # 按层级分组
        by_level = {0: [], 1: [], 2: [], 3: []}
        for h in hypotheses:
            lv = h.get("chain_level", 0)
            by_level.setdefault(lv, []).append(h)

        status_map = {
            "confirmed": "✅", "partial": "⚠️",
            "disputed": "❌", "weak_disputed": "🟡",
            "unverified": "🔍", "overturned": "⚰️", "unreachable": "🚫"
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

                # ── v1.1.0: 验证诊断（修正陈述 + 因果链强度 + 验证说明）
                # v1.2.1: +CounterAgent 修正追溯（sentiment 变更 + 级联裁决原因）──
                verification_note = h.get("reason", "")
                corrected = h.get("corrected_statement", "")
                causality = h.get("causality_strength", "")
                v_status = h.get("status", "")
                original_sentiment = h.get("original_sentiment", "")
                current_sentiment = h.get("sentiment", "")
                causality_note = h.get("causality_note", "")

                has_diagnostics = (
                    causality
                    or (corrected and str(corrected).strip())
                    or (verification_note and len(str(verification_note)) > 5)
                    or original_sentiment
                    or (causality_note and "CounterAgent" in str(causality_note))
                )

                if has_diagnostics:
                    lines.append(f"**验证诊断**:")
                    if causality:
                        emoji_map = {"strong": "✅", "moderate": "⚠️", "weak": "🔍", "broken": "⚡"}
                        lines.append(f"- 因果链强度: {emoji_map.get(causality, '')} **{causality}**"
                                     f"{' — 此假设不参与选股评分' if causality == 'broken' else ''}")
                    if corrected and str(corrected).strip():
                        lines.append(f"- **修正陈述**: {corrected}")
                    if verification_note and len(str(verification_note)) > 5:
                        lines.append(f"- {str(verification_note)[:200]}")

                    # ── v1.2.1: CounterAgent 修正追溯 ──
                    if original_sentiment and original_sentiment != current_sentiment:
                        sentiment_map = {"positive": "🟢看多", "negative": "🔴看空", "neutral": "⚪中性"}
                        old_label = sentiment_map.get(original_sentiment, original_sentiment)
                        new_label = sentiment_map.get(current_sentiment, current_sentiment)
                        lines.append(f"- **级联修正**: `{current_sentiment}` → `{original_sentiment}` "
                                     f"({new_label} → {old_label})")
                    if causality_note and "CounterAgent" in str(causality_note):
                        # 提取 CounterAgent 部分（去掉原始 causality_note 前缀）
                        note_parts = str(causality_note).split("CounterAgent")
                        for part in note_parts[1:]:
                            clean = part.strip(" :：|").strip()
                            if clean:
                                lines.append(f"- 🔄 CounterAgent: {clean[:200]}")
                                break
                    lines.append(f"")

                if key_indicators:
                    lines.append(f"**跟踪指标**:")
                    for k in key_indicators:
                        if isinstance(k, dict):
                            name = k.get("name", str(k))
                            freq = k.get("frequency", "monthly")
                            lines.append(f"- {name} (巡检: {freq})")
                        else:
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

        # --- 股池（v1.1.0: 分赛道三张表） ---
        if stock_pool:
            lines.extend(["", f"## 行业股池（共 {len(stock_pool)} 只）", ""])

            # 按 segment 分组
            segments_order = [
                ("upstream", "📦 上游设备与材料"),
                ("mid", "📦 中游设计与制造"),
                ("downstream", "📦 下游模组与应用"),
            ]

            for seg_id, seg_label in segments_order:
                seg_stocks = [s for s in stock_pool if s.get("segment") == seg_id]
                if not seg_stocks:
                    continue

                lines.extend([f"### {seg_label}（共 {len(seg_stocks)} 只）", ""])
                lines.append("| # | 股票 | 景气适配 | 风险暴露 | 质量 | 综合 | ROE | 毛利率 | 营收增速 | 命中假设 | 挑选理由 |")
                lines.append("|---|------|:------:|:------:|:----:|:----:|-----|--------|----------|----------|----------|")
                for s in seg_stocks:
                    pf = f"{s.get('prosperity_fit', '-'):.2f}" if isinstance(s.get('prosperity_fit'), (int, float)) else "-"
                    rx = f"{s.get('risk_exposure', '-'):.2f}" if isinstance(s.get('risk_exposure'), (int, float)) else "-"
                    ql = f"{s.get('quality', '-'):.2f}" if isinstance(s.get('quality'), (int, float)) else "-"
                    cp = f"{s.get('composite', '-'):.2f}" if isinstance(s.get('composite'), (int, float)) else "-"
                    raw = s.get("raw_indicators", {})
                    roe = f"{raw.get('roe', '-')}%" if raw.get('roe') is not None else "-"
                    gpm = f"{raw.get('gross_margin', '-')}%" if raw.get('gross_margin') is not None else "-"
                    rev = f"{raw.get('revenue_yoy', '-')}%" if raw.get('revenue_yoy') is not None else "-"
                    hits = ", ".join(s.get("hit_hypotheses", [])) or "-"
                    reason = s.get("selection_reason", "-")[:30] or "-"
                    lines.append(
                        f"| {s.get('rank', '-')} | {s.get('name', s.get('ts_code', '-'))} | "
                        f"{pf} | {rx} | {ql} | {cp} | {roe} | {gpm} | {rev} | {hits} | {reason} |"
                    )
                lines.append("")

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
