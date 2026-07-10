"""HypothesizeAgent — 因果推理假设形成（v4，两阶段稳定性增强）

v0.21 两阶段架构：
  Phase 1: 骨架生成 — 3 轮并行 LLM（仅 4 字段）→ 投票聚合 → 固定骨架
  Phase 2: 内容填充 — 1 轮 LLM + 骨架硬约束 → 程序化校验 → 最多 2 轮回滚

从情报搜索结果中构建 4 层因果推理链：
- Level 0: 现状诊断 — 「当前行业的客观状态是什么？」
- Level 1: 一阶推演 — 「如果 L0 成立，接下来必然发生什么？」
- Level 2: 二阶推演 — 「趋势发展下去，矛盾/机会/拐点在哪里？」
- Level 3: 投资落点 — 「这个推理对选股意味着什么？」

核心原则：
1. 推演而非罗列 — 每条假设必须有「上游 premise → 本环节 → 下游 consequence」的逻辑箭头
2. 可操作 — L3 必须给出可落地的选股方向
3. 防幻觉 — 每条假设必须引用至少 2 个信源
"""

import json
import logging
import re
import requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import get_session as get_db_session, Hypothesis
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)


class LLMUnavailableError(Exception):
    """LLM API 不可用（超时或连接失败），应立刻终止流水线，不回退。"""
    pass


# 4 层推理链的定义
CHAIN_LEVELS = {
    0: {"name": "现状诊断", "question": "当前行业的客观状态是什么？", "min_count": 2, "max_count": 3},
    1: {"name": "一阶推演", "question": "如果 L0 成立，接下来必然发生什么？", "min_count": 2, "max_count": 4},
    2: {"name": "二阶推演", "question": "趋势发展下去，矛盾/机会/拐点在哪里？", "min_count": 2, "max_count": 4},
    3: {"name": "投资落点", "question": "这个推理对选股意味着什么？", "min_count": 2, "max_count": 3},
}


class HypothesizeAgent:
    """因果推理假设形成 Agent (v4 — 两阶段稳定性增强)"""

    def __init__(self, data_dir: Path = None, rules_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self._load_templates()

    def _load_templates(self) -> None:
        """加载 prompt 模板"""
        # 主模板（降级单轮用）
        tmpl_path = self.rules_dir / "prompts" / "hypothesize_prompt.md"
        if tmpl_path.exists():
            self.template = tmpl_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Hypothesize prompt template not found: {tmpl_path}")
            self.template = ""

        # Phase 1 骨架模板
        p1_path = self.rules_dir / "prompts" / "hypothesize_phase1_prompt.md"
        if p1_path.exists():
            self.phase1_template = p1_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Phase 1 prompt template not found: {p1_path}")
            self.phase1_template = ""

        # Phase 2 填充模板
        p2_path = self.rules_dir / "prompts" / "hypothesize_phase2_prompt.md"
        if p2_path.exists():
            self.phase2_template = p2_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Phase 2 prompt template not found: {p2_path}")
            self.phase2_template = ""

    # ── 产业链上下文格式化（v1.0 Wiki-Centric）────────────

    def _format_chain_context(self, chain_model: dict | None) -> str:
        """将产业链拓扑 YAML 转为 prompt 友好文本。

        chain_model=None（首次运行无 YAML）时返回空字符串，零影响。
        """
        if not chain_model:
            return ""

        lines = []
        chain = chain_model.get("chain", {})
        segments = chain.get("segments", [])

        # ── 产业链结构 ──
        lines.append("## 产业链拓扑（来自知识库，跨 run 复用）")
        lines.append("")
        lines.append("### 产业链结构（上游→中游→下游）")
        lines.append("")

        position_order = {"upstream": 0, "mid": 1, "downstream": 2}
        for seg in sorted(segments, key=lambda s: position_order.get(s.get("position", ""), 99)):
            name = seg.get("name", "")
            role = seg.get("description", "").replace("\n", " ").strip()
            bottleneck = seg.get("bottleneck", {})
            b_level = bottleneck.get("level", "unknown")
            b_rate = bottleneck.get("localization_rate", "?")
            b_detail = bottleneck.get("detail", "").replace("\n", " ").strip()
            companies = ", ".join(seg.get("representative_companies", []))

            lines.append(f"**{name}**")
            lines.append(f"- 角色: {role}")
            lines.append(f"- 瓶颈: {b_level} | 国产化率 ~{b_rate}% | {b_detail}")
            lines.append(f"- 代表公司: {companies}")
            lines.append("")

        # ── 全局瓶颈视图 ──
        bottlenecks = chain_model.get("bottlenecks", [])
        if bottlenecks:
            lines.append("### 全局瓶颈视图")
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

        # ── 供需格局 ──
        sd = chain_model.get("supply_demand", {})
        if sd:
            lines.append("### 供需格局")
            lines.append(f"- 整体判断: {sd.get('overall_judgment', '')}")
            lines.append("- 需求驱动:")
            for d in sd.get("demand_drivers", []):
                driver = d.get("driver", "")
                cert = d.get("certainty", "")
                window = d.get("window", "")
                lines.append(f"  - {driver} | 确定性: {cert} | 时间窗: {window}")
            lines.append("- 供给约束:")
            for c in sd.get("supply_constraints", []):
                constraint = c.get("constraint", "")
                detail = c.get("detail", "")
                lines.append(f"  - {constraint} — {detail}")
            lines.append("")

        # ── 技术路径 ──
        tech_paths = chain_model.get("technology_paths", [])
        if tech_paths:
            lines.append("### 技术路径成熟度")
            for tp in tech_paths:
                name = tp.get("name", "")
                maturity = tp.get("maturity", "")
                rep = tp.get("representative", "")
                if rep:
                    lines.append(f"- {name} [{maturity}] 代表: {rep}")
                else:
                    lines.append(f"- {name} [{maturity}]")
            lines.append("")

        # ── 可跟踪指标 ──
        tracking = chain_model.get("tracking_indicators", [])
        if tracking:
            lines.append("### 可跟踪指标")
            for ti in tracking:
                name = ti.get("name", "")
                freq = ti.get("frequency", "")
                meaning = ti.get("meaning", "")
                lines.append(f"- {name} ({freq}) — {meaning}")
            lines.append("")

        # ── 使用规则 ──
        lines.append("### 产业链使用规则")
        lines.append("")
        lines.append("1. **锚定环节**: 每条假设应明确对应产业链的哪个 segment，推理中引用该环节的瓶颈和国产化率。")
        lines.append('   示例: 「H1-1: HBM产能不足 → 中游制造环节景气延续」')
        lines.append("")
        lines.append("2. **瓶颈驱动**: 标注为 high/critical 的瓶颈环节应生成更多假设，重点关注瓶颈对上下游的传导效应。")
        lines.append("")
        lines.append("3. **供需锚定**: 假设核心命题应围绕供需矛盾展开（如「供给约束 vs 需求爆发」），而非孤立引用新闻片段。")
        lines.append("")
        lines.append("4. **公司锚定**: L3 投资落点中提到的公司应优先从 representative_companies 中选择；如需新增公司必须标注对应的信源编号。")
        lines.append("")
        lines.append("5. **技术路径感知**: ")
        lines.append('   - 「规模化」路径 → 生成放量/渗透率提升类假设')
        lines.append('   - 「商业示范/工程验证」路径 → 生成技术拐点类假设')
        lines.append("")
        lines.append("6. **指标锁定**: key_indicators 应优先参考 tracking_indicators 中已有的指标名和巡检频率，确保指标确实可公开跟踪。")
        lines.append("")
        lines.append("7. **跨环节传导**: 可基于上下游瓶颈关系生成传导类假设。")
        lines.append('   示例: 「上游设备国产化率30% → 限制中游产能扩张速度 → 中游景气持续性超预期」')

        return "\n".join(lines)

    # ── 入口 ──────────────────────────────────────────────

    def form_hypotheses(
        self,
        industry_name: str,
        session_id: int,
        search_result: dict,
        history=None,     # Optional[IndustryHistory]
        chain_model=None,  # v1.0: 产业链拓扑 YAML dict（Phase 1 预留，Phase 2 消费）
    ) -> list[dict]:
        """
        从搜索结果中构建因果推理链（v4 两阶段）。

        Returns:
            [{id, title, chain_level, derives_from, statement, reasoning,
              sources, confidence, time_horizon, investment_implication,
              key_indicators, verification_needed, tier, wiki_path}, ...]
        """
        rounds = getattr(settings, "PROSPERITY_HYPOTHESIZE_ROUNDS", 3)

        # ── 降级模式：rounds≤1 → 走传统单轮 ──
        if rounds <= 1:
            logger.info(f"HypothesizeAgent v4: single-round mode (rounds={rounds})")
            return self._form_single_round(industry_name, session_id, search_result, history, chain_model)

        logger.info(f"HypothesizeAgent v4: two-phase mode for {industry_name}")

        # ── Phase 1: 骨架（3 轮并行 + 投票） ──
        logger.info(f"Phase 1: generating skeleton ({rounds} parallel rounds)")
        skeleton = self._phase1_skeleton(industry_name, search_result, history, rounds, chain_model)
        logger.info(f"Phase 1: skeleton fixed → {len(skeleton)} hypotheses "
                    f"({','.join(h['id'] for h in skeleton)})")

        # ── Phase 2: 填充（1 轮强约束） ──
        logger.info("Phase 2: filling content with skeleton constraint")
        try:
            hypotheses = self._phase2_fill(industry_name, skeleton, search_result, history, chain_model)
        except LLMUnavailableError:
            raise  # LLM 不可用，不 fallback，直接退出

        if not hypotheses:
            logger.error(f"Phase 2 failed: all attempts returned empty, falling back to single-round")
            return self._form_single_round(industry_name, session_id, search_result, history, chain_model)

        # ── 后处理：tier 映射 ──
        for h in hypotheses:
            if "tier" not in h or not h.get("tier"):
                level = h.get("chain_level", 0)
                tier_map = {0: "core", 1: "sub", 2: "sub", 3: "data"}
                h["tier"] = tier_map.get(level, "core")

        # ── 写入 wiki + 数据库 ──
        self._persist_hypotheses(hypotheses, industry_name, session_id)

        logger.info(f"HypothesizeAgent v4: {len(hypotheses)} hypotheses formed (two-phase)")
        return hypotheses

    def _form_single_round(
        self, industry_name: str, session_id: int, search_result: dict, history=None, chain_model=None
    ) -> list[dict]:
        """降级模式：传统单轮 LLM 调用（rounds≤1 时使用）"""
        logger.info(f"HypothesizeAgent v4: fallback single-round for {industry_name}")

        prompt = self._build_prompt(industry_name, search_result, history, chain_model)
        llm_output = self._call_llm(prompt, timeout=120)
        hypotheses = self._parse_hypotheses(llm_output, industry_name)

        for h in hypotheses:
            if "tier" not in h or not h.get("tier"):
                level = h.get("chain_level", 0)
                tier_map = {0: "core", 1: "sub", 2: "sub", 3: "data"}
                h["tier"] = tier_map.get(level, "core")

        self._persist_hypotheses(hypotheses, industry_name, session_id)
        return hypotheses

    # ── 持久化（wiki + DB） ──────────────────────────────

    def _persist_hypotheses(self, hypotheses: list[dict], industry_name: str, session_id: int) -> None:
        """写入 wiki + 数据库"""
        wiki_dir = self.data_dir / "wiki" / "hypotheses"
        wiki_dir.mkdir(parents=True, exist_ok=True)

        db = get_db_session()
        try:
            for h in hypotheses:
                md_content = self._render_hypothesis_page(industry_name, h, hypotheses)
                filename = f"{industry_name}-{self._safe_filename(h['title'])}.md"
                file_path = wiki_dir / filename
                file_path.write_text(md_content, encoding="utf-8")

                h["wiki_path"] = str(file_path.relative_to(self.data_dir))

                derives_str = h.get("derives_from", [])
                if isinstance(derives_str, list):
                    derives_str = ",".join(derives_str)
                db_h = Hypothesis(
                    session_id=session_id,
                    title=h["title"],
                    tier=h.get("tier", "core"),
                    chain_level=h.get("chain_level"),
                    derives_from=derives_str,
                    time_horizon=h.get("time_horizon", ""),
                    status="pending",
                    confidence=h.get("confidence", "medium"),
                    sentiment=h.get("sentiment"),
                    wiki_path=h["wiki_path"],
                )
                db.add(db_h)
            db.commit()
        finally:
            db.close()

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"HypothesizeAgent v4: {len(hypotheses)} hypotheses for {industry_name}")

    # ── Phase 1: 骨架生成 ───────────────────────────────

    def _phase1_skeleton(
        self, industry_name: str, search_result: dict, history=None, rounds: int = 3, chain_model=None
    ) -> list[dict]:
        """Phase 1: N 轮并行 LLM → 投票聚合 → 链完整性回填

        LLM 不可用时直接抛 LLMUnavailableError，不再 fallback 浪费时间。
        """
        timeout = getattr(settings, "PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT", 25)
        prompt_func = lambda: self._build_phase1_prompt(industry_name, search_result, history, chain_model)

        all_rounds = []
        llm_down = False

        with ThreadPoolExecutor(max_workers=rounds) as executor:
            futures = {
                executor.submit(self._call_llm_phase1, prompt_func(), i + 1): i + 1
                for i in range(rounds)
            }
            for future in futures:
                round_num = futures[future]
                try:
                    result = future.result(timeout=timeout)
                    if result:
                        all_rounds.append(result)
                        logger.info(f"Phase 1 round {round_num}/{rounds}: {len(result)} items")
                except FutureTimeoutError:
                    logger.warning(f"Phase 1 round {round_num}/{rounds}: timeout ({timeout}s)")
                    llm_down = True
                except LLMUnavailableError:
                    logger.error(f"Phase 1 round {round_num}/{rounds}: LLM unavailable")
                    llm_down = True
                except Exception as e:
                    logger.warning(f"Phase 1 round {round_num}/{rounds}: error — {e}")

        if not all_rounds:
            if llm_down:
                raise LLMUnavailableError(
                    f"Phase 1: all {rounds} rounds timed out — LLM API unavailable. Aborting."
                )
            logger.error("Phase 1: all rounds returned empty (not timeout)")
            return self._fallback_skeleton(industry_name, search_result, history, chain_model)

        # 投票聚合
        skeleton = self._aggregate_skeletons(all_rounds)

        if not skeleton:
            logger.warning("Phase 1: ≥2/3 vote filtered all hypotheses, falling back to round 1")
            skeleton = all_rounds[0]

        # 链完整性回填
        skeleton = self._fix_chain_completeness(skeleton, all_rounds)

        # 按层级+序号排序
        skeleton.sort(key=lambda h: (h.get("chain_level", 0),
                                     int(re.search(r"\d+", h.get("id", "H0-0")).group())))

        return skeleton

    def _call_llm_phase1(self, prompt: str, round_num: int = 0) -> list[dict]:
        """Phase 1 专用 LLM 调用 + 解析"""
        timeout = getattr(settings, "PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT", 30)
        output = self._call_llm(prompt, timeout=timeout)
        # Phase 1 输出结构简单（仅 4 字段），但复用同一解析器
        try:
            hypotheses = self._parse_hypotheses(output)
            return hypotheses
        except Exception as e:
            logger.warning(f"Phase 1 round {round_num}: parse failed — {e}")
            return []

    def _build_phase1_prompt(self, industry_name: str, search_result: dict, history=None, chain_model=None) -> str:
        """构建 Phase 1 骨架 prompt"""
        results_text = self._build_search_results_text(search_result)
        history_text = self._build_history_context(history)
        chain_context = self._format_chain_context(chain_model)
        return self.phase1_template.format(
            industry_name=industry_name,
            history_text=history_text if history_text else "（无历史记录，首次研究）",
            chain_context=chain_context,
            results_text=results_text,
        )

    def _aggregate_skeletons(self, rounds: list[list[dict]]) -> list[dict]:
        """对 N 轮骨架投票：ID + title 双重匹配 + ≥2/N 规则"""
        min_votes = max(2, len(rounds) // 2 + 1)  # 多数规则

        # Step 1: 按 ID 收集
        id_counter = Counter()
        id_details = {}  # id → {"titles": [...], "derives": [...], "level": int}

        for round_hyps in rounds:
            seen = set()
            for h in round_hyps:
                h_id = h.get("id", "")
                if not h_id or h_id in seen:
                    continue
                seen.add(h_id)
                id_counter[h_id] += 1
                if h_id not in id_details:
                    id_details[h_id] = {
                        "titles": [],
                        "derives": [],
                        "level": h.get("chain_level", 0),
                    }
                id_details[h_id]["titles"].append(h.get("title", ""))
                id_details[h_id]["derives"].append(
                    tuple(sorted(h.get("derives_from", [])))
                )

        # Step 2: 保留 ≥ min_votes 的假设
        skeleton = []
        for h_id, count in id_counter.items():
            if count < min_votes:
                logger.debug(f"Phase 1 vote: {h_id} dropped ({count}/{len(rounds)} votes)")
                continue

            detail = id_details[h_id]
            # 投票选最多的 title
            title = Counter(detail["titles"]).most_common(1)[0][0]
            # 投票选最多的 derives_from
            derives = list(Counter(detail["derives"]).most_common(1)[0][0])

            skeleton.append({
                "id": h_id,
                "title": title,
                "chain_level": detail["level"],
                "derives_from": derives,
            })

        logger.info(f"Phase 1 aggregation: {len(skeleton)}/{sum(len(r) for r in rounds)} "
                    f"hypotheses kept (≥{min_votes}/{len(rounds)} rule)")

        return skeleton

    def _fix_chain_completeness(self, skeleton: list[dict], all_rounds: list[list[dict]]) -> list[dict]:
        """确保每条 L1 有 ≥1 条 L2，每条 L2 有 ≥1 条 L3。

        投票可能丢弃下游 → 从被丢弃的假设中找回。
        """
        for h in skeleton:
            level = h.get("chain_level", 0)
            if level not in (1, 2):
                continue
            # 检查是否有下游
            next_level = level + 1
            has_downstream = any(
                h.get("id") in other.get("derives_from", [])
                for other in skeleton
                if other.get("chain_level") == next_level
            )
            if has_downstream:
                continue

            # 从被丢弃的假设中找回下游
            rescued = self._rescue_downstream_for(h.get("id"), all_rounds, next_level)
            if rescued:
                skeleton.append(rescued)
                logger.info(f"Chain fix: rescued {rescued['id']} as downstream of {h.get('id')}")

        return skeleton

    def _rescue_downstream_for(
        self, upstream_id: str, all_rounds: list[list[dict]], target_level: int
    ) -> dict | None:
        """从所有轮次中找回 upstream_id 的下游（target_level）"""
        candidates = Counter()
        candidate_details = {}

        for round_hyps in all_rounds:
            seen = set()
            for h in round_hyps:
                if h.get("chain_level") != target_level:
                    continue
                if upstream_id not in h.get("derives_from", []):
                    continue
                h_id = h.get("id", "")
                if h_id in seen:
                    continue
                seen.add(h_id)
                candidates[h_id] += 1
                if h_id not in candidate_details:
                    candidate_details[h_id] = h

        if not candidates:
            return None

        best_id = candidates.most_common(1)[0][0]
        best = candidate_details[best_id]
        return {
            "id": best.get("id", ""),
            "title": best.get("title", ""),
            "chain_level": target_level,
            "derives_from": best.get("derives_from", []),
        }

    def _fallback_skeleton(self, industry_name: str, search_result: dict, history=None, chain_model=None) -> list[dict]:
        """兜底：Phase 1 全失败时用单轮生成骨架"""
        logger.warning("Phase 1 fallback: using single-round skeleton generation")
        prompt = self._build_prompt(industry_name, search_result, history, chain_model)
        llm_output = self._call_llm(prompt, timeout=120)
        hypotheses = self._parse_hypotheses(llm_output, industry_name)
        # 提取骨架
        return [
            {
                "id": h.get("id", ""),
                "title": h.get("title", ""),
                "chain_level": h.get("chain_level", 0),
                "derives_from": h.get("derives_from", []),
            }
            for h in hypotheses
        ]

    # ── Phase 2: 内容填充 ───────────────────────────────

    def _phase2_fill(
        self, industry_name: str, skeleton: list[dict], search_result: dict, history=None, chain_model=None
    ) -> list[dict]:
        """Phase 2: 1 轮 LLM 填充 + 骨架校验 + 最多 2 次重试。

        LLM 不可用时直接抛 LLMUnavailableError 快速终止。
        """
        for attempt in range(3):
            prompt = self._build_phase2_prompt(industry_name, skeleton, search_result, history, chain_model)
            # v0.23: Phase 2 超时可配（v4 pro 模型慢，默认 120s）
            timeout = getattr(settings, "PROSPERITY_HYPOTHESIZE_PHASE2_TIMEOUT", 120)
            try:
                llm_output = self._call_llm(prompt, timeout=timeout)
            except LLMUnavailableError:
                raise LLMUnavailableError(
                    "Phase 2: LLM unavailable during content fill. Aborting pipeline."
                ) from None
            hypotheses = self._parse_hypotheses(llm_output, industry_name)

            if not hypotheses:
                logger.warning(f"Phase 2 attempt {attempt + 1}/3: empty parse result")
                continue

            if self._validate_fill_output(hypotheses, skeleton):
                logger.info(f"Phase 2: validated (attempt {attempt + 1}/3)")
                return hypotheses

            logger.warning(f"Phase 2 attempt {attempt + 1}/3: skeleton validation failed, retrying...")

        logger.error("Phase 2: all 3 attempts failed skeleton validation")
        return []

    def _build_phase2_prompt(
        self, industry_name: str, skeleton: list[dict], search_result: dict, history=None, chain_model=None
    ) -> str:
        """构建 Phase 2 填充 prompt — 嵌入选定骨架文本"""
        # 生成骨架文本
        skeleton_lines = []
        for h in skeleton:
            h_id = h.get("id", "")
            title = h.get("title", "")
            level = h.get("chain_level", 0)
            derives = h.get("derives_from", [])
            derives_str = ", ".join(derives) if derives else "无"
            skeleton_lines.append(f"- {h_id} [L{level}] {title} (derives_from: {derives_str})")
        skeleton_text = "\n".join(skeleton_lines)

        results_text = self._build_search_results_text(search_result)
        history_text = self._build_history_context(history)
        chain_context = self._format_chain_context(chain_model)

        return self.phase2_template.format(
            industry_name=industry_name,
            history_text=history_text if history_text else "（无历史记录，首次研究）",
            chain_context=chain_context,
            skeleton_text=skeleton_text,
            results_text=results_text,
        )

    def _validate_fill_output(self, filled: list[dict], skeleton: list[dict]) -> bool:
        """校验 Phase 2 输出与骨架一致性"""
        skeleton_ids = {h.get("id", "") for h in skeleton}
        filled_ids = {h.get("id", "") for h in filled}

        # 检查 ID 集合
        if skeleton_ids != filled_ids:
            missing = skeleton_ids - filled_ids
            extra = filled_ids - skeleton_ids
            logger.warning(f"Phase 2 skeleton mismatch: missing={missing}, extra={extra}")
            return False

        # 检查每条假设的 derives_from 是否与骨架一致
        for h in filled:
            h_id = h.get("id", "")
            expected = next((s for s in skeleton if s.get("id") == h_id), None)
            if expected is None:
                continue
            filled_derives = set(h.get("derives_from", []))
            expected_derives = set(expected.get("derives_from", []))
            if filled_derives != expected_derives:
                logger.warning(
                    f"Phase 2: derives_from changed for {h_id}: "
                    f"expected={expected_derives}, got={filled_derives}"
                )
                return False

        return True

    def _build_search_results_text(self, search_result: dict) -> str:
        """构建搜索结果文本（新旧分流），供各 prompt 复用"""
        results_text = ""
        new_count = search_result.get("new_count", 0)
        old_count = search_result.get("old_count", 0)
        all_results = search_result.get("results", [])

        if new_count > 0 or old_count > 0:
            new_results = all_results[:new_count]
            old_results = all_results[new_count:new_count + old_count]

            if new_results:
                results_text += "## 🆕 本期新情报\n\n"
                for i, r in enumerate(new_results[:20]):
                    # v0.23: 解除截断 — 之前 300 字导致 LLM 看不到关键数据
                    results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')}\n来源: {r.get('url', '')}\n\n"

            if old_results:
                results_text += "## 📚 上次已覆盖（摘要）\n\n"
                for i, r in enumerate(old_results[:10]):
                    results_text += f"[旧#{i+1}] {r.get('title', '')}\n{r.get('content', '')[:500]}\n\n"
        else:
            for i, r in enumerate(all_results[:20]):
                results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')}\n来源: {r.get('url', '')}\n\n"

        return results_text

    def _build_prompt(self, industry_name: str, search_result: dict, history=None, chain_model=None) -> str:
        """构建 LLM prompt — 4 层因果推理链 + 历史锚定 + 产业链拓扑（降级单轮用）"""
        results_text = self._build_search_results_text(search_result)
        history_text = self._build_history_context(history)
        chain_context = self._format_chain_context(chain_model)

        return self.template.format(
            industry_name=industry_name,
            history_text=history_text if history_text else "（无历史记录，首次研究）",
            chain_context=chain_context,
            results_text=results_text,
        )

    def _build_history_context(self, history) -> str:
        """从 IndustryHistory 构建历史锚定文本"""
        if history is None:
            return ""

        lines = []

        # 评级历史
        if history.rating_history:
            lines.append("**最近评级历史**:")
            lines.extend(history.rating_history[:3])
            lines.append("")

        # 上次报告摘要
        if history.last_synthesis_excerpt:
            lines.append("**上次报告摘要**（L0-L3 推理结论）:")
            lines.append(history.last_synthesis_excerpt)
            lines.append("")

        # 上次假设状态分布
        if history.previous_hypotheses:
            lines.append(f"**上次研究假设状态**: {history.get_hypotheses_summary()}")
            lines.append("（请基于既有推理链延续拓展，标记哪些假设仍成立、哪些已变化）")
            lines.append("")

        return "\n".join(lines)

    def _call_llm(self, prompt: str, timeout: int = 120) -> str:
        """调用 DeepSeek LLM（temperature=0 确保输出确定性）。

        超时/连接失败 → 抛 LLMUnavailableError 快速终止流水线。
        HTTP 错误(非超时) → 返回 "[]" 允许回退。
        """
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            raise LLMUnavailableError("LLM_API_KEY not configured")

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
                        {"role": "system", "content": "你是行业研究分析师。只输出要求的 JSON 格式，不要其他内容。严格按 H{level}-{seq} 格式编 id。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,  # v0.9.8: 确定性输出（Bug 4）
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"LLM returned {resp.status_code}: {resp.text[:300]}")
                return "[]"
        except requests.exceptions.Timeout:
            logger.error(f"LLM call timeout ({timeout}s)")
            raise LLMUnavailableError(f"LLM API timeout after {timeout}s") from None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"LLM connection refused: {e}")
            raise LLMUnavailableError(f"LLM API unreachable: {e}") from None
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "[]"

    def _parse_hypotheses(self, llm_output: str, industry_name: str = "") -> list[dict]:
        """解析 LLM JSON 输出"""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output

        hypotheses = []
        # 尝试直接解析
        try:
            hypotheses = json.loads(json_str)
        except json.JSONDecodeError:
            # 回退 1: 尝试提取第一个 JSON 数组
            arr_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", json_str)
            if arr_match:
                try:
                    hypotheses = json.loads(arr_match.group(0))
                except json.JSONDecodeError:
                    pass

        if not hypotheses:
            # 回退 2: 失败时保存原始输出到 debug 文件
            logger.warning("Failed to parse LLM JSON output")
            debug_path = self.data_dir / "wiki" / "_debug_llm_output.json"
            try:
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                debug_path.write_text(llm_output, encoding="utf-8")
                logger.warning(f"Raw LLM output saved to {debug_path}")
            except Exception:
                pass
            return []

        # 向后兼容：key_indicators 旧格式 string[] → 新格式 object[]
        for h in hypotheses:
            indicators = h.get("key_indicators", [])
            if indicators and isinstance(indicators[0], str):
                h["key_indicators"] = [
                    {
                        "name": s,
                        "frequency": "monthly",
                        "search_query": "",
                        "expected_direction": "unknown",
                    }
                    for s in indicators
                ]

        # v0.10.0: 链结构完整性验证（警告不阻断）
        self._validate_chain_completeness(hypotheses, industry_name)

        return hypotheses

    def _validate_chain_completeness(
        self, hypotheses: list[dict], industry_name: str
    ) -> None:
        """验证推理链结构完整性（v0.10.0）。

        警告不阻断 — LLM 产出后仅打日志，让用户决定是否重跑。
        """
        # 构建反向索引：哪些下游引用了该 id
        children_map: dict[str, list[str]] = {}
        for h in hypotheses:
            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]
            for up_id in derives:
                children_map.setdefault(up_id, []).append(h.get("id", "?"))

        # 检查 L1 → L2
        l1_items = [h for h in hypotheses if h.get("chain_level") == 1]
        for h in l1_items:
            h_id = h.get("id", "")
            if h_id not in children_map:
                logger.warning(
                    f"Dead-end chain: L1 '{h_id}' ({h.get('title','')}) "
                    f"has no L2 downstream. Industry: {industry_name}. "
                    f"Its signal will be wasted in prosperity rating."
                )

        # 检查 L2 → L3
        l2_items = [h for h in hypotheses if h.get("chain_level") == 2]
        for h in l2_items:
            h_id = h.get("id", "")
            if h_id not in children_map:
                logger.warning(
                    f"Dead-end chain: L2 '{h_id}' ({h.get('title','')}) "
                    f"has no L3 downstream. Industry: {industry_name}."
                )

    def _render_hypothesis_page(self, industry_name: str, h: dict, all_hypotheses: list[dict] = None) -> str:
        """渲染假设 Markdown 页面（v3 — 含推理链可视化 + sentiment）"""
        h_id = h.get("id", "?")
        chain_level = h.get("chain_level", 0)
        level_name = CHAIN_LEVELS.get(chain_level, {}).get("name", "未知层级")
        sources = "、".join(h.get("sources", []))
        verify_items = "\n".join(f"- {v}" for v in h.get("verification_needed", []))
        derives_from = h.get("derives_from", [])
        time_horizon = h.get("time_horizon", "")
        investment_implication = h.get("investment_implication", "")
        key_indicators = h.get("key_indicators", [])
        sentiment = h.get("sentiment", "")
        sentiment_display = {"positive": "📈 正向", "negative": "📉 负向", "neutral": "➖ 中性"}.get(sentiment, "")

        # 上游引用
        upstream_section = ""
        if derives_from:
            upstream_section = f"\n**上游假设**: {', '.join(f'`{d}`' for d in derives_from)}\n"

        # 下游引用（可选）
        downstream_section = ""
        if all_hypotheses:
            downstream = [other.get("title", "?") for other in all_hypotheses
                          if h_id in other.get("derives_from", [])]
            if downstream:
                downstream_section = f"\n**下游推演**: {', '.join(downstream)}\n"

        # 关键跟踪指标（兼容旧格式 string[] 和新格式 object[]）
        indicators_section = ""
        if key_indicators:
            lines = []
            for k in key_indicators:
                if isinstance(k, dict):
                    name = k.get("name", str(k))
                    freq = k.get("frequency", "monthly")
                    direction = k.get("expected_direction", "")
                    dir_icon = {"rising": "↑", "falling": "↓", "stable": "→", "breaking": "⚡"}.get(direction, "")
                    lines.append(f"- {name} (巡检: {freq} {dir_icon})")
                else:
                    lines.append(f"- {k}")
            indicators_section = "\n**关键跟踪指标**:\n" + "\n".join(lines) + "\n"

        # 时间窗口
        horizon_section = ""
        if time_horizon:
            horizon_section = f"\n**时间窗口**: ⏱️ {time_horizon}\n"

        # 投资含义（仅 L3）
        implication_section = ""
        if investment_implication:
            implication_section = f"""\n## 投资含义

{investment_implication}
"""

        level_icon = {0: "📊", 1: "🔮", 2: "⚖️", 3: "🎯"}.get(chain_level, "📌")

        sentiment_line = f"\n**方向**: {sentiment_display}\n" if sentiment else ""

        return f"""# {level_icon} [{level_name}] {h.get('title', '')}

> 行业: {industry_name} | ID: `{h_id}` | 层级: L{chain_level} | 状态: 🔍 UNVERIFIED
{upstream_section}{downstream_section}
## 假设

**陈述**: {h.get('statement', '')}

**推理链**: {h.get('reasoning', '')}
{horizon_section}
**支撑信源**: {sources}

**初始置信度**: {h.get('confidence', 'medium')}{sentiment_line}
**需要验证的数据点**:
{verify_items}
{indicators_section}{implication_section}
## 验证

（待验证）

## 跟踪

（待确认）
"""

    def _safe_filename(self, title: str) -> str:
        """将标题转为安全的文件名"""
        return re.sub(r"[^\w\-]", "_", title)[:50]
