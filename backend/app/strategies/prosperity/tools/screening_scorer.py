"""Screen Scoring — v1.1.0 三维打分引擎（纯规则，零 LLM）

职责：
1. hypothesis_weight() — 单条假设的有效评分权重（消费验证结果）
2. format_hypothesis_tree() — 假设树摘要 → LLM prompt 可读文本
3. score_stock_pool() — 股票三维打分（景气适配 + 风险暴露 + 质量）

核心规则：
- causality_strength == "broken" → weight = 0（因果链断裂）
- status in (overturned, unreachable) → weight = 0
- 有 corrected_statement → 基础权重 × 0.5
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── 常数 ──────────────────────────────────────────────────────

# status → 基础权重
STATUS_WEIGHT = {
    "confirmed": 1.0,
    "partial": 0.6,
    "weak_disputed": 0.3,
    "disputed": 0.0,
    "unverified": 0.3,
    "overturned": 0.0,
    "unreachable": 0.0,
}

# chain_level → 层级折扣
LAYER_WEIGHT = {0: 1.0, 1: 0.8, 2: 0.7, 3: 0.5}

# causality_strength → 因果强度折扣
CAUSALITY_DISCOUNT = {"strong": 1.0, "moderate": 0.7, "weak": 0.4, "broken": 0.0}

# 综合分权重
COMPOSITE_WEIGHTS = {
    "prosperity_fit": 0.5,
    "risk_exposure": 0.3,       # 负向，公式中减
    "quality": 0.2,
}


# ── 假设权重计算 ──────────────────────────────────────────────

def hypothesis_weight(h: dict) -> float:
    """单条假设的有效评分权重。

    消费验证结果 (status / causality_strength / corrected_statement)，
    返回 0.0 ~ 1.0 的权重。

    Rules (优先级递减):
      1. causality_strength == "broken" → 0.0（因果链断裂）
      2. status in (overturned, unreachable) → 0.0（已推翻/不可达）
      3. 有 corrected_statement → base × 0.5（修正降权）
      4. 正常: STATUS_WEIGHT × LAYER_WEIGHT × CAUSALITY_DISCOUNT
    """
    status = h.get("status", "unverified")
    # 只把字符串转小写确保匹配（兼容 verified→confirmed 等旧格式）
    status_lower = status.lower()

    # 1. 因果链断裂 → 不参与评分
    causality = h.get("causality_strength", "moderate")
    if causality == "broken":
        return 0.0

    # 2. 被推翻/不可达 → 不参与评分
    if status_lower in ("overturned", "unreachable"):
        return 0.0

    # 3. 基础权重
    base_w = STATUS_WEIGHT.get(status_lower, 0.3)

    # 4. 层级折扣
    chain_level = h.get("chain_level", 0)
    layer_w = LAYER_WEIGHT.get(chain_level, 0.5)

    # 5. 因果强度折扣
    causality_d = CAUSALITY_DISCOUNT.get(causality, 0.7)

    weight = base_w * layer_w * causality_d

    # 6. 修正陈述降权
    corrected = h.get("corrected_statement", "")
    if corrected and len(str(corrected).strip()) > 5:
        weight *= 0.5

    return round(weight, 4)


def hypothesis_direction(h: dict) -> str:
    """返回假设的影响方向：positive / negative / neutral。

    如果 causality_strength == "broken" 且有 corrected_statement，
    按修正陈述中是否出现反转关键词判断实际方向。
    """
    causality = h.get("causality_strength", "moderate")
    corrected = h.get("corrected_statement", "")

    # 如果因果链断裂且有修正，尝试从修正文本推断实际方向
    if causality == "broken" and isinstance(corrected, str) and corrected.strip():
        negative_reverse = ["不成立", "难以逆转", "不存在", "不构成", "被高估", "被夸大"]
        positive_reverse = ["利好", "支撑", "推动", "增长", "改善", "扩张"]
        text = corrected
        neg_count = sum(1 for kw in negative_reverse if kw in text)
        pos_count = sum(1 for kw in positive_reverse if kw in text)
        # 修正陈述推翻了负面假设 → 实际应该是正面或中性
        if neg_count > pos_count:
            return "neutral"  # 负面不成立 → 中性
        if pos_count > 0:
            return "positive"  # 有正面信号

    return h.get("sentiment", "neutral")


# ── 假设树格式化 ──────────────────────────────────────────────

def _flatten_implication(value) -> str:
    """安全地将 investment_implication 转为字符串。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, str):
                parts.append(f"{k}: {v}")
        return "；".join(parts)
    if value is None:
        return ""
    return str(value)


def format_hypothesis_tree(hypotheses: list[dict]) -> str:
    """将假设树 + 验证结果转成 LLM prompt 可读的摘要文本。

    分组：正面信号 / 负面信号
    broken 的假设标注"已被验证修正，不参与判断"
    """
    positive_lines = []
    negative_lines = []
    neutral_lines = []

    for h in hypotheses:
        h_id = h.get("id", "?")
        statement = h.get("statement", "")
        status = h.get("status", "unverified")
        causality = h.get("causality_strength", "")
        corrected = h.get("corrected_statement", "")

        direction = hypothesis_direction(h)
        weight = hypothesis_weight(h)

        # 标记
        tags = []
        if status != "confirmed":
            tags.append(status.upper())
        if causality == "broken":
            tags.append("因果链断裂·已被验证修正·不参与判断")
        elif causality == "weak":
            tags.append(f"因果强度:{causality}")
        if corrected and isinstance(corrected, str) and corrected.strip():
            tags.append(f"修正陈述:{corrected[:120]}")

        tag_str = f" [{', '.join(tags)}]" if tags else ""
        line = f"- {h_id} (w={weight:.2f}): {statement[:150]}{tag_str}"

        if direction == "positive":
            positive_lines.append(line)
        elif direction == "negative":
            negative_lines.append(line)
        else:
            neutral_lines.append(line)

    parts = []
    if positive_lines:
        parts.append("### 正面信号（利好）")
        parts.extend(positive_lines)
        parts.append("")
    if negative_lines:
        parts.append("### 负面信号（利空）")
        parts.extend(negative_lines)
        parts.append("")
    if neutral_lines:
        parts.append("### 中性信号")
        parts.extend(neutral_lines)
        parts.append("")

    return "\n".join(parts)


# ── 三维打分 ──────────────────────────────────────────────────

def score_stock_pool(
    matches: list[dict],
    hypotheses: list[dict],
    finance_data: Optional[dict[str, dict]] = None,
) -> dict[str, dict]:
    """输入 LLM 已标注命中的股票列表 + 假设树 → 输出三维得分。

    Args:
        matches: [{ts_code, segment, positive_hits, negative_hits, purity_estimate, excluded}, ...]
        hypotheses: 完整假设树（含验证结果）
        finance_data: {ts_code: {roe, gross_margin, revenue_yoy}} 可选

    Returns:
        {ts_code: {prosperity_fit, risk_exposure, quality, composite, segment, hit_hypotheses}}
    """
    # 构建假设权重查找表
    h_weight_map: dict[str, float] = {}
    h_direction_map: dict[str, str] = {}
    for h in hypotheses:
        h_id = h.get("id", "")
        if h_id:
            h_weight_map[h_id] = hypothesis_weight(h)
            h_direction_map[h_id] = hypothesis_direction(h)

    # 收集所有有效股票的质量分
    quality_scores: dict[str, float] = {}
    if finance_data:
        for ts, fd in finance_data.items():
            roe = _safe_float(fd.get("roe", 0))
            gpm = _safe_float(fd.get("gross_margin", 0))
            rev = _safe_float(fd.get("revenue_yoy", 0))
            # 质量分 = 三项平均（归一化到 0~1）
            quality_scores[ts] = round(
                (_clamp_pct(roe, 30) + _clamp_pct(gpm, 60) + _clamp_pct(rev, 50)) / 3,
                4,
            )

    results = {}
    for m in matches:
        ts = m.get("ts_code", "")
        if not ts:
            continue

        # 景气适配度 = Σ(命中正面假设 × 权重)
        pos_hits = m.get("positive_hits", [])
        prosperity_fit = sum(h_weight_map.get(h_id, 0) for h_id in pos_hits)

        # 风险暴露度 = Σ(命中负面假设 × 权重)
        neg_hits = m.get("negative_hits", [])
        risk_exposure = sum(h_weight_map.get(h_id, 0) for h_id in neg_hits)

        # 关联占比折扣
        purity = m.get("purity_estimate", 1.0)
        if isinstance(purity, (int, float)) and 0 < purity < 1:
            prosperity_fit *= purity
            risk_exposure *= purity

        # 质量分
        quality = quality_scores.get(ts, 0.5)

        # 综合 = 景气适配 × 0.5 - 风险暴露 × 0.3 + 质量 × 0.2
        composite = round(
            prosperity_fit * COMPOSITE_WEIGHTS["prosperity_fit"]
            - risk_exposure * COMPOSITE_WEIGHTS["risk_exposure"]
            + quality * COMPOSITE_WEIGHTS["quality"],
            4,
        )

        # 收集所有命中假设
        all_hits = pos_hits + neg_hits

        results[ts] = {
            "prosperity_fit": round(prosperity_fit, 4),
            "risk_exposure": round(risk_exposure, 4),
            "quality": round(quality, 4),
            "composite": composite,
            "segment": m.get("segment", ""),
            "hit_hypotheses": all_hits,
            "purity_estimate": round(purity, 4) if isinstance(purity, (int, float)) else 1.0,
            "excluded": m.get("excluded", False),
            "exclude_reason": m.get("exclude_reason", ""),
            "selection_reason": m.get("selection_reason", ""),
        }

    return results


# ── 辅助函数 ──────────────────────────────────────────────────

def _clamp_pct(value: float, cap: float) -> float:
    """将百分比值钳制到 [0, cap]，然后归一化到 [0, 1]。
    
    例: ROE 15%, cap=30 → 0.5
    """
    v = max(0, min(value, cap))
    if cap == 0:
        return 0.0
    return v / cap


def _safe_float(val) -> float:
    """安全转 float，失败返回 0.0"""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
