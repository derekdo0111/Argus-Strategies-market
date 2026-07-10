"""CounterAgent — LLM 语义级联裁决 + sentiment 修正（v2.2 链感知·Wiki-Centric）

职责：在 VerifyAgent 验证完成后，由 LLM 根据完整五维语义 + 产业链拓扑做两件事：
1. 级联裁决（三遍扫描，不区分 polarity：DISPUTED→OVERTURNED→级联 UNREACHABLE）
2. 基于 corrected_statement 修正假设 sentiment（让下游自然消费）

v2.2 链感知（2026-07-09）：
- _format_chain_context() 从 YAML 提取 6 块级联裁决专属上下文（瓶颈/供需/技术/级联规则）
- _build_cascade_prompt() 从硬编码迁移到 counter_cascade_prompt.md 模板
- LLM 裁决时可参考：瓶颈推翻门槛 / 供需 disputed 分类 / 技术路径 sentiment 校准 / 跨环节依赖

v2.1 去极性化（2026-07-03）：
- 移除 v2.0 的极性规则（positive+disputed→切 / negative+disputed→保活）
- 被证伪的前提不论 polarity 一律 overturned → cascade
- 参考 Spec §2.4 + Plan v1.1

三级降级：LLM → 硬编码三遍扫描 → 原 _cascade_safety_net
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── 硬编码降级：corrected_statement 关键词 → sentiment 修正 ──

NEGATIVE_SIGNAL_WORDS = [
    "放缓", "下降", "下滑", "衰退", "萎缩", "压力",
    "产能过剩", "需求不足", "恶化", "负面", "风险加大",
    "不及预期", "低于预期", "亏损",
]

POSITIVE_SIGNAL_WORDS = [
    "超预期", "高于预期", "加速", "回暖", "复苏",
    "扩张", "渗透率提升", "景气", "强劲", "高增长",
    "供不应求", "结构性机会",
]

NEUTRAL_HEDGE_WORDS = [
    "结构性分化", "冰火两重天", "局部", "但", "然而",
    "虽然", "不过", "博弈",
]


class CounterAgent:
    """LLM 语义级联裁决 Agent（v2.2 链感知·Wiki-Centric）

    输入：VerifyAgent 产出的已验证假设（含五维语义）+ 产业链拓扑 YAML
    输出：级联裁决后的假设（sentiment 可能被修正，status 可能变为 unreachable）

    三遍扫描（不区分 polarity）：
    1. DISPUTED → OVERTURNED（瓶颈感知推翻门槛）
    2. 上游 OVERTURNED → 下游 UNREACHABLE（跨环节依赖判断）
    3. PARTIAL → 降级置信度
    """

    def __init__(self, data_dir=None, rules_dir=None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self._load_templates()

    def _load_templates(self) -> None:
        """加载 prompt 模板（v1.0.4: 从硬编码迁移到模板文件）"""
        tmpl_path = self.rules_dir / "prompts" / "counter_cascade_prompt.md"
        if tmpl_path.exists():
            self.cascade_template = tmpl_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Counter cascade prompt template not found: {tmpl_path}")
            self.cascade_template = ""

    # ═══════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════

    def cascade(
        self,
        industry_name: str,
        session_id: int,
        verified_hypotheses: list[dict],
        history=None,      # v1.0: 补上历史上下文（之前缺失）
        chain_model=None,   # v1.0: 产业链拓扑 YAML dict（Phase 1 预留，Phase 2 消费）
    ) -> list[dict]:
        """主入口：语义级联裁决 + sentiment 修正。

        Returns:
            修改后的假设列表（sentiment 可能被修正，status 可能变为 unreachable）。
            新增字段：original_sentiment（审计痕迹）。
        """
        logger.info(
            f"CounterAgent v2: semantic cascade for {len(verified_hypotheses)} hypotheses "
            f"[{industry_name}]"
        )

        # Step 1: LLM 语义裁决 + sentiment 修正（v1.0.4: 传入 chain_model）
        cascade_decisions = self._llm_cascade(industry_name, verified_hypotheses, chain_model)

        if cascade_decisions:
            verified_hypotheses = self._apply_cascade(verified_hypotheses, cascade_decisions)
            logger.info(
                f"CounterAgent: LLM cascade applied ({len(cascade_decisions)} decisions)"
            )
        else:
            logger.warning("CounterAgent: LLM cascade failed, falling back to hard-coded rules")
            verified_hypotheses = self._hardcoded_cascade(verified_hypotheses)

        return verified_hypotheses

    # ═══════════════════════════════════════════════
    # LLM 语义级联
    # ═══════════════════════════════════════════════

    def _llm_cascade(
        self, industry_name: str, hypotheses: list[dict], chain_model=None
    ) -> list[dict]:
        """调用 LLM 做语义级联裁决 + sentiment 修正（v1.0.4: +chain_model 消费）。"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            logger.warning("CounterAgent: no LLM_API_KEY configured, skip LLM cascade")
            return []

        hypo_context = []
        for h in hypotheses:
            derives = h.get("derives_from", [])
            if isinstance(derives, list):
                derives = derives
            elif isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]
            else:
                derives = []

            hypo_context.append({
                "id": h.get("id", ""),
                "chain_level": h.get("chain_level", 0),
                "title": h.get("title", ""),
                "statement": (h.get("statement", "") or "")[:200],
                "status": h.get("status", "unverified"),
                "sentiment": h.get("sentiment", "neutral"),
                "reason": (h.get("reason", "") or "")[:300],
                "corrected_statement": (h.get("corrected_statement") or "")[:200],
                "causality_strength": h.get("causality_strength", "moderate"),
                "causality_note": (h.get("causality_note", "") or "")[:200],
                "derives_from": derives,
                "time_horizon": h.get("time_horizon", ""),
            })

        chain_context = self._format_chain_context(chain_model)
        prompt = self._build_cascade_prompt(industry_name, hypo_context, chain_context)

        try:
            resp = requests.post(
                f"{settings.LLM_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是投资研究级联分析专家。只输出要求的 JSON 格式，不要额外解释。",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8192,
                },
                timeout=settings.PROSPERITY_COUNTER_TIMEOUT,
            )
            if resp.status_code == 200:
                body = resp.json()
                content = body["choices"][0]["message"]["content"]
                finish_reason = body["choices"][0].get("finish_reason", "unknown")

                decisions = self._parse_cascade_result(content)
                if decisions:
                    return decisions

                # ── 解析失败：保存 debug 信息 ──
                logger.warning(
                    f"CounterAgent: failed to parse LLM output "
                    f"(prompt_len={len(prompt)}, content_len={len(content)}, "
                    f"finish_reason={finish_reason})"
                )
                self._save_debug_output(content, prompt, finish_reason)
            else:
                logger.warning(
                    f"CounterAgent: LLM API returned {resp.status_code}"
                )
        except requests.exceptions.Timeout:
            logger.warning(f"CounterAgent: LLM timeout, retrying once...")
            try:
                resp = requests.post(
                    f"{settings.LLM_API_BASE}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": "你是投资研究级联分析专家。只输出要求的 JSON 格式，不要额外解释。",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 8192,
                    },
                    timeout=settings.PROSPERITY_COUNTER_TIMEOUT,
                )
                if resp.status_code == 200:
                    body = resp.json()
                    content = body["choices"][0]["message"]["content"]
                    finish_reason = body["choices"][0].get("finish_reason", "unknown")
                    decisions = self._parse_cascade_result(content)
                    if decisions:
                        return decisions
                    self._save_debug_output(content, prompt, finish_reason)
                else:
                    logger.warning(f"CounterAgent retry failed: {resp.status_code}")
            except Exception as e2:
                logger.error(f"CounterAgent retry exception: {e2}")
        except Exception as e:
            logger.error(f"CounterAgent LLM call failed: {e}")

        return []

    # ── 产业链上下文格式化（v1.0.4 Wiki-Centric·级联裁决专用）────────────

    def _format_chain_context(self, chain_model: dict | None) -> str:
        """将产业链拓扑 YAML 转为 prompt 友好文本（级联裁决专用）。

        与 VerifyAgent/HypothesizeAgent 的 _format_chain_context() 同逻辑，但输出侧重：
        - 瓶颈严重度 + 国产化率（推翻门槛）
        - 供需格局（disputed 分类）
        - 技术路径成熟度（sentiment 校准）
        - 跨环节依赖（级联传播判断）

        chain_model=None（首次运行无 YAML）时返回空字符串，零影响。
        """
        if not chain_model:
            return "（首次运行，产业链拓扑尚未建立。按通用规则裁决。）"

        lines = []
        chain = chain_model.get("chain", {})
        segments = chain.get("segments", [])

        # ── 产业链结构（瓶颈视图）──
        lines.append("### 产业链环节瓶颈视图")
        lines.append("")
        lines.append("| 环节 | 位置 | 瓶颈级别 | 国产化率 | 瓶颈说明 |")
        lines.append("|------|------|----------|----------|----------|")
        position_order = {"upstream": 0, "mid": 1, "downstream": 2}
        for seg in sorted(segments, key=lambda s: position_order.get(s.get("position", ""), 99)):
            name = seg.get("name", "")
            pos = seg.get("position", "")
            bottleneck = seg.get("bottleneck", {})
            b_level = bottleneck.get("level", "?")
            b_rate = bottleneck.get("localization_rate", "?")
            b_detail = bottleneck.get("detail", "").replace("\n", " ").strip()[:80]
            lines.append(f"| {name} | {pos} | {b_level} | ~{b_rate}% | {b_detail} |")
        lines.append("")

        # ── 全局瓶颈汇总 ──
        bottlenecks = chain_model.get("bottlenecks", [])
        if bottlenecks:
            lines.append("### 全局瓶颈汇总")
            for b in bottlenecks:
                seg_id = b.get("segment_id", "")
                severity = b.get("severity", "")
                desc = b.get("description", "")
                seg_name = seg_id
                for s in segments:
                    if s.get("id") == seg_id:
                        seg_name = s.get("name", seg_id)
                        break
                lines.append(f"- {seg_name} [{severity}]: {desc}")
            lines.append("")

        # ── 供需格局（disputed 分类专用）──
        sd = chain_model.get("supply_demand", {})
        if sd:
            lines.append("### 供需格局（disputed 分类参考）")
            lines.append(f"- 整体判断: **{sd.get('overall_judgment', '')}**")
            lines.append("- 需求驱动:")
            for d in sd.get("demand_drivers", []):
                lines.append(f"  - {d.get('driver', '')} | 确定性: {d.get('certainty', '')} | 时间窗: {d.get('window', '')}")
            lines.append("- 供给约束:")
            for c in sd.get("supply_constraints", []):
                lines.append(f"  - {c.get('constraint', '')} — {c.get('detail', '')}")
            lines.append("")

        # ── 技术路径成熟度（sentiment 校准）──
        tech_paths = chain_model.get("technology_paths", [])
        if tech_paths:
            lines.append("### 技术路径成熟度（sentiment 校准参考）")
            for tp in tech_paths:
                name = tp.get("name", "")
                maturity = tp.get("maturity", "")
                rep = tp.get("representative", "")
                lines.append(f"- {name} [{maturity}]" + (f" 代表: {rep}" if rep else ""))
            lines.append("")

        # ── 级联裁决使用规则 ──
        lines.append("### 级联裁决使用规则")
        lines.append("")
        lines.append("**推翻门槛（瓶颈感知）**：")
        lines.append("- 假设涉及 bottleneck.level=high/critical 的环节 → 推翻门槛更高 → 需要明确方向反转数据才能 overturned")
        lines.append("- 假设涉及 bottleneck.level=low 的环节 → 推翻门槛正常")
        lines.append("- 国产化率<30% 的环节 → 正面修正（国产替代加速）可能是真实突破")
        lines.append("- 国产化率>70% 的环节 → 同样的声明更可能是蹭热点")
        lines.append("")
        lines.append("**disputed 分类（供需格局引导）**：")
        lines.append("- overall_judgment=严重供需短缺/供不应求 → disputed 更可能是程度变化（供不应求下增速放缓≠证伪）")
        lines.append("- overall_judgment=产能过剩/需求不足 → disputed 更可能是方向反转")
        lines.append("")
        lines.append("**sentiment 校准（技术路径成熟度）**：")
        lines.append("- 成熟度=工程验证 → 正面修正需谨慎（实验室≠产业）")
        lines.append("- 成熟度=规模化 → 正面修正可信度更高")
        lines.append("- 成熟度=商业示范 → 居中态度")
        lines.append("")
        lines.append("**级联传播（跨环节依赖）**：")
        lines.append("- overturned 涉及 critical bottleneck → 下游大概率全部 unreachable")
        lines.append("- overturned 涉及 low bottleneck → 下游可能有绕过路径（国产替代、技术替代）")

        return "\n".join(lines)

    def _build_cascade_prompt(
        self, industry_name: str, hypo_context: list[dict], chain_context: str = ""
    ) -> str:
        """构建级联裁决 + sentiment 修正 prompt（v1.0.4: 模板文件 + chain_context 注入）。"""
        context_json = json.dumps(hypo_context, ensure_ascii=False, indent=2)

        if self.cascade_template:
            return self.cascade_template.format(
                industry_name=industry_name,
                chain_context=chain_context,
                context_json=context_json,
            )
        # ── 降级：模板文件不可用时，fallback 到内嵌 prompt ──
        logger.warning("CounterAgent: template not loaded, using built-in fallback prompt")
        return self._build_fallback_prompt(industry_name, chain_context, context_json)

    def _build_fallback_prompt(
        self, industry_name: str, chain_context: str, context_json: str
    ) -> str:
        """模板文件缺失时的内嵌降级 prompt（与原 v2.1 硬编码一致，新增 chain_context 占位）。"""
        parts = [f"你是投资研究级联分析专家。以下是「{industry_name}」行业经过数据交叉验证后的假设链。"]
        if chain_context and chain_context != "（首次运行，产业链拓扑尚未建立。按通用规则裁决。）":
            parts.append(f"\n## 产业链拓扑（决策上下文）\n{chain_context}")

        parts.append(f"""
## 任务一：级联裁决

根据每条假设的完整五维验证结果，判断其与上下游的级联关系。

### 级联规则（必须严格遵守）

1. **overturned → 切断下游**：已被确凿反例证伪的假设，不论 sentiment 方向，其下游自动 unreachable
2. **weak_disputed → 降级不切**：有矛盾但不直接推翻，降低置信度，下游保持活跃
3. **partial → 降级置信度**：数据不充分，不切断链，只降低 confidence
4. **unverified → 证据不足**：保持低置信度，不切链
5. **confirmed → 正常传递**
6. **参考 corrected_statement**：如果 LLM 验证给出了修正版陈述，级联时以修正版为判断依据

### 绝对禁止（必须严格遵守，违反任一条 = 错误输出）

1. **status=partial 的假设绝不 overturned**
2. **status=unverified 的假设绝不 overturned**
3. **status=disputed 的假设要分两类**：强反例（方向反转）→ overturned / 弱反例（程度变化）→ downgrade_confidence
4. **sentiment 修正不与 overturned 叠加**

## 任务二：sentiment 修正（略，见模板）

## 已验证假设

```json
{context_json}
```

## 输出格式（略，见模板）
""")
        return "\n".join(parts)

    def _parse_cascade_result(self, llm_output: str) -> list[dict]:
        """解析 LLM 级联裁决输出。"""
        # 尝试提取 ```json ... ``` 块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output

        try:
            result = json.loads(json_str)
            return result.get("cascade_decisions", [])
        except json.JSONDecodeError:
            # 尝试提取最外层的 JSON 对象
            obj_match = re.search(r"\{[\s\S]*\}", json_str)
            if obj_match:
                try:
                    result = json.loads(obj_match.group(0))
                    return result.get("cascade_decisions", [])
                except json.JSONDecodeError:
                    pass
            logger.warning(f"CounterAgent: unparseable LLM output: {llm_output[:200]}")
            return []

    def _save_debug_output(
        self, content: str, prompt: str, finish_reason: str
    ) -> None:
        """解析失败时保存 LLM 原始输出到 debug 文件，便于事后分析。"""
        debug_path = Path(self.data_dir) / "wiki" / "_debug_counter_output.json"
        try:
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_data = {
                "prompt_preview": prompt[:500],
                "prompt_length": len(prompt),
                "content_length": len(content),
                "finish_reason": finish_reason,
                "raw_output": content,
            }
            debug_path.write_text(
                json.dumps(debug_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.warning(f"CounterAgent: raw LLM output saved to {debug_path}")
        except Exception as e:
            logger.error(f"CounterAgent: failed to save debug output: {e}")

    def _apply_cascade(
        self, hypotheses: list[dict], decisions: list[dict]
    ) -> list[dict]:
        """应用 LLM 级联裁决 + sentiment 修正。

        两遍扫描：
        1. 逐假设应用判决（切链 + 标记 overturned / 降置信度 / 修正 sentiment）
        2. 级联传递：overturned/unreachable 的假设 → 下游 unreachable
        """
        decision_map = {d.get("hypothesis_id", ""): d for d in decisions}

        # ── 第一遍：逐假设处理 ──
        for h in hypotheses:
            h_id = h.get("id", "")
            if h_id not in decision_map:
                continue

            decision = decision_map[h_id]
            action = decision.get("action", "keep_active")
            reason = decision.get("reason", "")

            # v0.23.1 安全网：partial/unverified 不能被 overturned（代码层兜底）
            current_status = h.get("status", "")
            if action == "keep_unreachable" and current_status in ("partial", "unverified"):
                logger.warning(
                    f"CounterAgent safety net: refused to overturn {h_id} "
                    f"(status={current_status}, overridden to downgrade_confidence)"
                )
                action = "downgrade_confidence"
                decision["confidence_adjust"] = decision.get("confidence_adjust", "low")
                decision["reason"] = (
                    f"SAFETY_NET_OVERRIDE: original action=keep_unreachable refused "
                    f"(status={current_status} cannot be overturned). {reason}"
                )[:300]
                reason = decision["reason"]

            if action == "keep_unreachable":
                # 使用 new_status（可为 "overturned" 或 "unreachable"）
                new_status = decision.get("new_status") or "unreachable"
                h["status"] = new_status
                h["causality_strength"] = "broken"
                h["causality_note"] = f"CounterAgent: {reason[:200]}"

            elif action == "downgrade_confidence":
                adjust = decision.get("confidence_adjust", "medium")
                if h.get("confidence") == "high":
                    h["confidence"] = adjust
                existing_note = h.get("causality_note") or ""
                h["causality_note"] = f"{existing_note} | CounterAgent: {reason[:150]}".strip(" |")

            # sentiment 修正（可与以上动作并存）
            override = decision.get("sentiment_override")
            if override and override in ("positive", "negative", "neutral"):
                old_sentiment = h.get("sentiment", "neutral")
                if override != old_sentiment:
                    h["original_sentiment"] = old_sentiment
                    h["sentiment"] = override
                    existing_note = h.get("causality_note") or ""
                    h["causality_note"] = (
                        f"{existing_note} | "
                        f"sentiment {old_sentiment}→{override} ({reason[:100]})"
                    ).strip(" | ")

        # ── 第二遍：级联传递 ──
        # overturned 和 unreachable 的假设 → 下游也 unreachable
        cascade_ids = {
            h.get("id") for h in hypotheses
            if h.get("status") in ("unreachable", "overturned")
        }

        for h in hypotheses:
            if h.get("id") in cascade_ids:
                continue
            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]
            for up_id in derives:
                if up_id in cascade_ids:
                    h["status"] = "unreachable"
                    h["causality_strength"] = "broken"
                    h["causality_note"] = (
                        f"CounterAgent 级联传递：上游 {up_id} 已不可达"
                    )
                    break

        return hypotheses

    # ═══════════════════════════════════════════════
    # 硬编码降级（LLM 失败时）
    # ═══════════════════════════════════════════════

    def _hardcoded_cascade(self, hypotheses: list[dict]) -> list[dict]:
        """硬编码三遍扫描 + corrected_statement 关键词 sentiment 修正。

        LLM 失败时的降级方案。做两件事：
        1. 基于 corrected_statement 关键词修正 sentiment
        2. 三遍扫描级联（不区分 polarity）：
           - DISPUTED → OVERTURNED
           - OVERTURNED → 下游 UNREACHABLE
           - PARTIAL → 降级置信度
        """
        by_id = {h.get("id", ""): h for h in hypotheses}

        # ── 第一遍：sentiment 关键词修正 ──
        for h in hypotheses:
            corrected = (h.get("corrected_statement") or "").strip()
            if not corrected:
                continue
            new_sentiment = self._keyword_sentiment_override(
                h.get("sentiment", "neutral"), corrected
            )
            if new_sentiment != h.get("sentiment", "neutral"):
                old = h.get("sentiment", "neutral")
                h["original_sentiment"] = old
                h["sentiment"] = new_sentiment
                logger.info(
                    f"CounterAgent hard-coded: {h.get('id')} sentiment "
                    f"{old}→{new_sentiment} (corrected_statement keyword match)"
                )

        # ── 第一.五遍：disputed → overturned 仅限方向反转关键词 ──
        # v0.23.1：硬编码兜底时，disputed 只有确认方向反转才 overturned
        DIRECTION_REVERSAL_WORDS = [
            "缩减", "转负", "萎缩", "不再", "停止增长",
            "需求消失", "市场消失", "行业消失",
        ]
        for h in hypotheses:
            if h.get("status") != "disputed":
                continue
            corrected = (h.get("corrected_statement") or "") + (h.get("reason") or "")
            if any(kw in corrected for kw in DIRECTION_REVERSAL_WORDS):
                h["status"] = "overturned"
                h["causality_strength"] = "broken"
                h["causality_note"] = "硬编码：disputed + 方向反转关键词 → overturned"
                logger.info(
                    f"CounterAgent hard-coded: {h.get('id')} disputed→overturned "
                    f"(direction reversal keywords matched)"
                )

        # ── 第二遍：三遍扫描级联 ──
        unreachable_ids: set[str] = set()
        sorted_hyps = sorted(hypotheses, key=lambda h: h.get("chain_level", 0))

        for h in sorted_hyps:
            h_id = h.get("id", "")

            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]

            # 被上游 unreachable 传递
            for up_id in derives:
                if up_id in unreachable_ids:
                    h["status"] = "unreachable"
                    h["causality_strength"] = "broken"
                    h["causality_note"] = f"硬编码级联：上游 {up_id} 已不可达"
                    unreachable_ids.add(h_id)
                    break

            if h_id in unreachable_ids:
                continue

            # 检查上游状态（v0.22：仅 overturned/unreachable 切断，移除 disputed）
            for up_id in derives:
                up = by_id.get(up_id, {})
                up_status = up.get("status", "")

                # overturned / unreachable → 切断下游
                if up_status in ("overturned", "unreachable"):
                    h["status"] = "unreachable"
                    h["causality_strength"] = "broken"
                    h["causality_note"] = (
                        f"硬编码级联：上游 {up_id} 为 {up_status}"
                    )
                    unreachable_ids.add(h_id)
                    break

        return hypotheses

    def _keyword_sentiment_override(
        self, original_sentiment: str, corrected_statement: str
    ) -> str:
        """基于 corrected_statement 关键词判断 sentiment 修正方向。

        仅在 LLM 失败时作为兜底。规则保守（宁可漏判不误判）。
        """
        text = corrected_statement

        negative_count = sum(1 for kw in NEGATIVE_SIGNAL_WORDS if kw in text)
        positive_count = sum(1 for kw in POSITIVE_SIGNAL_WORDS if kw in text)
        neutral_count = sum(1 for kw in NEUTRAL_HEDGE_WORDS if kw in text)

        # 对冲词 ≥ 2 → neutral
        if neutral_count >= 2:
            return "neutral"

        # 原正向 + 负向词占优 → neutral（保守不判 negative）
        if original_sentiment == "positive" and negative_count > positive_count:
            return "neutral"
        if original_sentiment == "positive" and negative_count >= 2:
            return "neutral"

        # 原负向 + 正向词 ≥ 2 → neutral（保守不判 positive）
        if original_sentiment == "negative" and positive_count >= 2:
            return "neutral"

        # 默认维持原 sentiment
        return original_sentiment
