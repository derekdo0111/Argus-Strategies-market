"""VerifyAgent — LLM 交叉验证（v4）

对每条假设链用 LLM 进行串行交叉验证：
- LLM 自动生成反例搜索词并执行网络搜索（Bocha 优先，Tavily 降级）
- LLM 基于 Tushare 数据 + 搜索素材 + 反例证据 逐链验证
- 输出：status / reason / corrected_statement / confidence / causality_strength
- v4 增强：3 轮并行 LLM（Self-Consistency）+ 字段级投票聚合
  - Q1 supporting_source_indices: 3 轮交集 → source_count
  - Q2 data_alignment: 3 轮众数
  - Q3 counter_conflict_score: 3 轮 MAX, ≥2 → counter_conflict=yes
  - Q4 sentiment: 3 轮众数 → verified_sentiment
- 确定性后处理：级联安全网 + 假设页面写入 + DB 更新

CounterAgent 功能已合并进 VerifyAgent。
"""

import json
import logging
import re
import requests
import yaml
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import (
    get_session as get_db_session,
    Hypothesis,
)
from app.strategies.prosperity.tools.industry_metrics import (
    compute_industry_metrics,
    get_industry_ts_codes,
)
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)

STATUS_EMOJI = {
    "confirmed": "✅ CONFIRMED",
    "partial": "⚠️ PARTIAL",
    "disputed": "❌ DISPUTED",          # 保留兼容（存量假设可能仍带此值）
    "unverified": "🔍 UNVERIFIED",
    "unreachable": "🚫 UNREACHABLE",
    "overturned": "⚰️ OVERTURNED",
    "weak_disputed": "🟡 WEAK_DISPUTED",  # v0.22: 弱反例·降级不切链
}


# ═══════════════════════════════════════════════
# 确定性状态合成（v0.19：LLM 不再输出 status）
# ═══════════════════════════════════════════════

def _synthesize_status(
    source_count: int, data_alignment: str, conflict_level: str, chain_fit: str = ""
) -> str:
    """从 LLM 事实输出确定性合成假设状态（v0.22：三级冲突分级，v1.0.3：+chain_fit）。

    LLM 不再输出 status，只输出 source_count / data_alignment / conflict_level。
    status 由本函数根据固定规则计算，同一输入永远同一输出。

    v0.22: conflict_level 从布尔(yes/no)升级为三级(none/weak/strong)。
    v1.0.3: chain_fit 不影响 status（只影响 confidence）——避免用旧知识惩罚新信息。
    """
    # 优先级 1: 强反例直接推翻 → overturned
    if conflict_level == "strong":
        return "overturned"

    # 优先级 2: 零信源 → 完全无法验证
    if source_count == 0:
        return "unverified"

    # 优先级 3: 弱反例（冲突但非直接推翻） → weak_disputed（降级不切链）
    if conflict_level == "weak":
        return "weak_disputed"

    # 优先级 4: 信源不足或数据不支持 → partial
    if source_count == 1 or data_alignment == "不支持":
        return "partial"

    # 优先级 5: 2+ 信源 + 数据方向支持 → confirmed
    if source_count >= 2 and data_alignment in ("支持", "部分支持"):
        return "confirmed"

    # 兜底：2+ 信源但 data_alignment 未知 → partial
    return "partial"


def _synthesize_confidence(
    source_count: int, data_alignment: str, conflict_level: str, chain_fit: str = ""
) -> str:
    """从事实输出确定性合成置信度（v0.22：三级冲突分级，v1.0.3：+chain_fit 加权）。

    v1.0.3: chain_fit 对置信度做 ±1 级修正（不跨越两级）：
      - aligned → 升一级（low→medium, medium→high, high→high）
      - misaligned → 降一级（high→medium, medium→low, low→low）
    """
    # 基础置信度计算
    if conflict_level == "strong":
        base = "high"  # 被推翻的置信度高——证据非常确定
    elif conflict_level == "weak":
        base = "low"   # 弱反例：置信度低
    elif source_count >= 3 and data_alignment == "支持":
        base = "high"
    elif source_count >= 2 and data_alignment in ("支持", "部分支持"):
        base = "high"
    elif source_count >= 1 and data_alignment in ("支持", "部分支持"):
        base = "medium"
    elif source_count >= 1:
        base = "medium"
    else:
        base = "low"

    # chain_fit ±1 级修正（v1.0.3）
    LEVELS = {"low": 0, "medium": 1, "high": 2}
    if chain_fit == "aligned":
        new_level = min(LEVELS[base] + 1, 2)
    elif chain_fit == "misaligned":
        new_level = max(LEVELS[base] - 1, 0)
    else:
        new_level = LEVELS[base]  # 无 chain_fit 或无 chain_model → 不变

    return {0: "low", 1: "medium", 2: "high"}[new_level]


class VerifyAgent:
    """LLM 交叉验证 Agent（v3：完全重构）"""

    def __init__(self, data_dir: Path = None, rules_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self.bocha_api_key = getattr(settings, "BOCHA_API_KEY", "")
        self.tavily_api_key = getattr(settings, "TAVILY_API_KEY", "")
        self._load_templates()

    def _load_templates(self) -> None:
        """加载 prompt 模板"""
        verify_path = self.rules_dir / "prompts" / "verify_prompt.md"
        counter_path = self.rules_dir / "prompts" / "counter_query_prompt.md"
        self.verify_template = verify_path.read_text(encoding="utf-8") if verify_path.exists() else ""
        self.counter_template = counter_path.read_text(encoding="utf-8") if counter_path.exists() else ""
        if not self.verify_template:
            logger.warning(f"Verify prompt template not found: {verify_path}")
        if not self.counter_template:
            logger.warning(f"Counter query prompt template not found: {counter_path}")

    # ── 产业链上下文格式化（v1.0.2 Wiki-Centric）────────────

    def _format_chain_context(self, chain_model: dict | None) -> str:
        """将产业链拓扑 YAML 转为 prompt 友好文本。

        chain_model=None（首次运行无 YAML）时返回空字符串，零影响。
        与 HypothesizeAgent._format_chain_context() 同逻辑，各 Agent 自包含。
        """
        if not chain_model:
            return ""

        lines = []
        chain = chain_model.get("chain", {})
        segments = chain.get("segments", [])

        # ── 产业链结构 ──
        lines.append("## 产业链拓扑（来自知识库，跨 run 复用）")
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

        # ── 使用规则（v1.0.3：升级为 Q5 链适配度体系）──
        lines.append("### 产业链使用规则（验证专用·v1.0.3 Q5体系）")
        lines.append("")
        lines.append("**核心原则**：产业链拓扑是评分标准，不是参考书。Q1-Q4 必须链感知，Q5 独立判定链适配度。")
        lines.append("")
        lines.append("**Q1 信源对口**：判断假设对应哪个产业链环节 → 只算涉及该环节 bottleneck/代表公司/关键指标的信源。同一信源涉多环节 → 以最接近假设核心陈述的环节为准。")
        lines.append("")
        lines.append("**Q2 数据对齐**：参考 tracking_indicators 的 meaning 文本 + 供需格局 overall_judgment（如\"严重供需短缺\"→正方向）。Tushare 数据方向与该环节代表公司业绩一致才算\"支持\"。")
        lines.append("")
        lines.append("**Q3 瓶颈校准**：")
        lines.append(f"- bottleneck level=high/critical 且国产化率<30% → 反例可能是真实瓶颈 → 至少打 1 分")
        lines.append("- 反例涉及瓶颈缓解信号（如国产替代加速）→ 2 分以上")
        lines.append("- 反例泛泛而谈、不涉任何瓶颈环节 → 最高 1 分")
        lines.append("")
        lines.append("**Q4 情感联动**：sentiment 应与瓶颈级别联动——high/critical 瓶颈的负面信号更严重，正面信号价值更高。")
        lines.append("")
        lines.append("**Q5 chain_fit**（alias/aligned）：判断假设因果逻辑是否契合产业链拓扑。")
        lines.append("- aligned：假设方向与 bottleneck 供需矛盾一致 / 技术路径成熟度匹配")
        lines.append("- misaligned：假设声称能解决 critical bottleneck 但国产化率极低 / 因果链断裂（如\"下游需求解决上游技术卡脖子\"）/ 预期方向与供需格局相反")
        lines.append("- Q5 影响 confidence ±1 级（不影响 status）")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════

    def verify(
        self,
        industry_name: str,
        session_id: int,
        hypotheses: list[dict],
        search_result: dict,
        history=None,      # Optional[IndustryHistory]
        chain_model=None,   # v1.0: 产业链拓扑 YAML dict（Phase 1 预留，Phase 2 消费）
        skip_cascade: bool = False,  # v0.10.0: CounterAgent 接管级联时跳过
    ) -> dict:
        """LLM 串行验证所有推理链。

        Args:
            industry_name: 行业名称
            session_id: 研究会话 ID
            hypotheses: HypothesizeAgent 产出的假设列表
            search_result: SearchAgent 产出的搜索结果
            history: 行业历史上下文

        Returns:
            {industry, session_id, verified_count, statuses, hypotheses: [...], chain_results: [...]}
        """
        logger.info(f"VerifyAgent v3: LLM verifying {len(hypotheses)} hypotheses for {industry_name}")

        # Step 1: 拉取 Tushare 行业 + 个股数据
        print(f"      -> [1/5] 拉取 Tushare 行业数据...")
        industry_data = self._get_industry_data(industry_name)
        n_sample = industry_data.get("sample_size", 0)
        print(f"      -> [1/5] Tushare 数据就绪（{n_sample} 只成分股）")

        # Step 2: 构建推理链分组
        chains = self._build_chains(hypotheses)
        print(f"      -> [2/5] 识别 {len(chains)} 条推理链")

        # Step 3: 串行验证每条链路
        all_verified: dict[str, dict] = {}  # id → verified hypothesis
        chain_results = []
        previous_summary = ""
        search_materials_text = self._format_search_materials(search_result)
        # v0.9.8: wiki 历史锚定 — 确保 LLM 验证有上下文延续性（Bug P0）
        history_text = self._build_history_context(history)

        for i, chain in enumerate(chains):
            chain_label = f"链路{i+1}"
            print(f"      -> [3/5] 验证 {chain_label} ({len(chain)} 条假设)...")

            # 3a: 生成反例搜索词并搜索
            counter_queries = self._generate_counter_queries(industry_name, chain, chain_label, chain_model)
            counter_evidence = self._execute_counter_searches(counter_queries)

            # 3b: LLM 验证
            result = self._verify_chain_with_llm(
                industry_name=industry_name,
                chain=chain,
                chain_label=chain_label,
                industry_data=industry_data,
                search_materials=search_materials_text,
                counter_evidence=counter_evidence,
                previous_summary=previous_summary,
                history_text=history_text,
                chain_model=chain_model,
            )

            # 3c: 汇总
            for h in result.get("hypotheses", []):
                h_id = h.get("id", "")
                if h_id:
                    all_verified[h_id] = h

            chain_results.append({
                "chain_label": chain_label,
                "counter_queries": counter_queries,
                "result": result,
            })

            # 3d: 构建下一轮摘要
            previous_summary = self._build_chain_summary(result)

        # Step 4: 级联处理（v0.10.0: CounterAgent 接管时跳过）
        verified_hypotheses = [all_verified.get(h.get("id", ""), h) for h in hypotheses]
        if skip_cascade:
            print(f"      -> [4/5] 级联安全网跳过（CounterAgent 接管）")
        else:
            print(f"      -> [4/5] 级联安全网...")
            verified_hypotheses = self._cascade_safety_net(verified_hypotheses, all_verified)

        # Step 5: 写入
        print(f"      -> [5/5] 写回假设页面 + 数据库...")
        self._update_hypothesis_pages(industry_name, verified_hypotheses)
        self._update_db(session_id, verified_hypotheses)

        # 统计（v0.22: +weak_disputed +overturned）
        statuses = {"confirmed": 0, "partial": 0, "weak_disputed": 0, "disputed": 0, "unverified": 0, "overturned": 0, "unreachable": 0}
        for v in verified_hypotheses:
            s = v.get("status", "unverified")
            statuses[s] = statuses.get(s, 0) + 1

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"VerifyAgent v3: {statuses} for {industry_name}")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "verified_count": len(verified_hypotheses),
            "statuses": statuses,
            "hypotheses": verified_hypotheses,
            "chain_results": chain_results,
        }

    # ═══════════════════════════════════════════════
    # 数据拉取
    # ═══════════════════════════════════════════════

    def _get_industry_data(self, industry_name: str) -> dict:
        """获取行业财务聚合数据 + 成分股核心指标"""
        try:
            ts_codes = get_industry_ts_codes(industry_name)
            if ts_codes:
                n_codes = min(len(ts_codes), 200)
                print(f"        -> 获取到 {len(ts_codes)} 只成分股，拉取前 {n_codes} 只...")
                return compute_industry_metrics(ts_codes[:200], industry_name)
            else:
                print(f"        -> 未找到 {industry_name} 的成分股")
        except Exception as e:
            logger.warning(f"Industry data fetch failed: {e}")
        return {"industry": industry_name, "sample_size": 0, "metrics": {}}

    # ═══════════════════════════════════════════════
    # 推理链分组
    # ═══════════════════════════════════════════════

    def _build_chains(self, hypotheses: list[dict]) -> list[list[dict]]:
        """将假设按 derives_from 分组为推理链。

        每条链从 L0 开始，沿 derives_from 向下追踪。未链接的假设各自成链。
        """
        if not hypotheses:
            return []

        by_id = {h.get("id", ""): h for h in hypotheses}
        chains = []
        assigned: set[str] = set()

        # L0 作为链的起点
        for h in hypotheses:
            h_id = h.get("id", "")
            if h_id in assigned:
                continue
            if h.get("chain_level") == 0 or not h.get("derives_from"):
                chain = [h]
                assigned.add(h_id)
                # 向下追踪
                self._follow_chain(h_id, by_id, chain, assigned)
                chains.append(chain)

        # 剩余未分配的
        for h in hypotheses:
            h_id = h.get("id", "")
            if h_id not in assigned:
                chains.append([h])
                assigned.add(h_id)

        return chains

    def _follow_chain(self, upstream_id: str, by_id: dict, chain: list, assigned: set):
        """沿 derives_from 向下追踪，将下游假设加入链"""
        for h_id, h in by_id.items():
            if h_id in assigned:
                continue
            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",")]
            if upstream_id in derives:
                chain.append(h)
                assigned.add(h_id)
                self._follow_chain(h_id, by_id, chain, assigned)

    # ═══════════════════════════════════════════════
    # 反例搜索
    # ═══════════════════════════════════════════════

    def _generate_counter_queries(self, industry_name: str, chain: list[dict], chain_label: str, chain_model=None) -> list[str]:
        """让 LLM 根据推理链生成反例搜索词（v1.0.2: 链感知增强）"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            return ["{industry} 风险 衰退 产能过剩".format(industry=industry_name),
                    "{industry} 泡沫 炒作 概念".format(industry=industry_name)]

        # 构建链摘要
        chain_text = ""
        for h in chain:
            chain_text += f"{h.get('id', '')}: {h.get('statement', '')}\n"

        chain_context = self._format_chain_context(chain_model)

        prompt = self.counter_template.format(
            industry_name=industry_name,
            chain_label=chain_label,
            chain_context=chain_context,
            chain_text=chain_text,
        )

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
                        {"role": "system", "content": "你是一位投资研究分析师。只输出要求的搜索词，不要其他内容。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": settings.LLM_MAX_TOKENS,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                queries = [line.strip("- ").strip() for line in content.strip().split("\n") if line.strip()]
                return queries[:3]  # 最多 3 条
        except Exception as e:
            logger.warning(f"Counter query generation failed: {e}")

        return ["{industry} 风险 衰退".format(industry=industry_name)]

    def _detect_engine(self) -> str:
        """检测使用哪个搜索引擎: bocha > tavily > none"""
        if self.bocha_api_key:
            return "bocha"
        if self.tavily_api_key:
            return "tavily"
        return "none"

    def _bocha_search(self, query: str, max_results: int = 5) -> list[dict]:
        """调用 Bocha Web Search API（v0.23: 反例搜索）"""
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
                    "query": query,
                    "title": page.get("name", ""),
                    "url": page.get("url", ""),
                    "content": content[:300],
                })
            return results
        except Exception as e:
            logger.warning(f"Bocha counter search failed for '{query}': {e}")
            return []

    def _tavily_counter_search(self, query: str, max_results: int = 5) -> list[dict]:
        """调用 Tavily Search API（备用反例搜索）"""
        if not self.tavily_api_key:
            return []

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                return [{
                    "query": query,
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", "")[:300],
                } for r in results[:max_results]]
        except Exception as e:
            logger.warning(f"Tavily counter search failed for '{query}': {e}")

        return []

    def _execute_counter_searches(self, queries: list[str]) -> list[dict]:
        """执行反例搜索（Bocha 优先，Tavily 降级）"""
        engine = self._detect_engine()
        if engine == "none":
            return []

        all_results = []
        for query in queries:
            if engine == "bocha":
                results = self._bocha_search(query)
            else:
                results = self._tavily_counter_search(query)
            all_results.extend(results)

        logger.debug(f"Counter searches [{engine}]: {len(queries)} queries → {len(all_results)} results")
        return all_results

    # ═══════════════════════════════════════════════
    # 历史上下文构建
    # ═══════════════════════════════════════════════

    def _build_history_context(self, history) -> str:
        """从 IndustryHistory 构建历史锚定文本（与 HypothesizeAgent 同源）"""
        if history is None:
            return "（无历史记录，首次研究）"

        lines = []

        # 评级历史
        if history.rating_history:
            lines.append("**最近评级历史**:")
            lines.extend(history.rating_history[:3])
            lines.append("")

        # 上次报告摘要（L0-L3 推理结论）
        if history.last_synthesis_excerpt:
            lines.append("**上次报告摘要**（L0-L3 推理结论）:")
            lines.append(history.last_synthesis_excerpt)
            lines.append("")

        # 上次假设状态分布
        if history.previous_hypotheses:
            lines.append(f"**上次研究假设状态**: {history.get_hypotheses_summary()}")
            lines.append("（请参考上次的验证结论，标记哪些假设的信源数量/数据方向应与上次一致）")
            lines.append("")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════
    # LLM 验证
    # ═══════════════════════════════════════════════

    def _format_search_materials(self, search_result: dict) -> str:
        """格式化搜索素材为文本"""
        results = search_result.get("results", [])
        if not results:
            return "（无搜索素材）"

        lines = []
        for i, r in enumerate(results[:30]):
            lines.append(f"[{i+1}] {r.get('title', '')}")
            lines.append(f"    {r.get('content', '')[:300]}")
            lines.append("")
        return "\n".join(lines)

    def _call_verify_llm(self, prompt: str) -> Optional[str]:
        """单次 LLM 验证调用，含超时重试。返回响应文本或 None。

        v0.20: 从 _verify_chain_with_llm 中提取为独立方法，供多轮并行调用。
        """
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            return None

        for attempt in range(2):
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
                            {"role": "system", "content": "你是一位行业研究验证分析师。只输出要求的 JSON 格式，不要其他内容。"},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": settings.LLM_MAX_TOKENS,
                    },
                    timeout=180,
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"]
                else:
                    logger.error(f"LLM verify failed (attempt {attempt+1}/2): {resp.status_code} {resp.text[:200]}")
            except requests.exceptions.Timeout:
                logger.warning(f"LLM verify timeout (attempt {attempt+1}/2)")
            except Exception as e:
                logger.error(f"LLM verify error (attempt {attempt+1}/2): {e}")

        return None

    def _verify_chain_with_llm(
        self,
        industry_name: str,
        chain: list[dict],
        chain_label: str,
        industry_data: dict,
        search_materials: str,
        counter_evidence: list[dict],
        previous_summary: str,
        history_text: str = "",
        chain_model=None,
    ) -> dict:
        """调用 LLM 验证一条推理链（v4：3 轮并行 + 字段级聚合）"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            return {"hypotheses": [{**h, "status": "unverified", "reason": "LLM API 未配置",
                                      "causality_strength": "moderate", "causality_note": ""}
                                     for h in chain]}

        # 构建 prompt（与 v3 相同）
        tushare_text = self._format_tushare_data(industry_data)
        counter_text = self._format_counter_evidence(counter_evidence)
        chain_context = self._format_chain_context(chain_model)

        chain_text = ""
        for h in chain:
            derives = h.get("derives_from", [])
            if isinstance(derives, list):
                derives = ", ".join(derives)
            chain_text += f"""
**{h.get('id', '?')}** (L{h.get('chain_level', '?')})
- 标题: {h.get('title', '')}
- 陈述: {h.get('statement', '')}
- 推理链: {h.get('reasoning', '')}
- 初始置信度: {h.get('confidence', 'medium')}
- 上游假设: {derives}
- 时间窗口: {h.get('time_horizon', '')}
- 原始信源: {', '.join(h.get('sources', []))}
"""

        prompt = self.verify_template.format(
            industry_name=industry_name,
            chain_label=chain_label,
            previous_summary=previous_summary if previous_summary else "（首条链路，无前序摘要）",
            history_text=history_text if history_text else "（无历史记录，首次研究）",
            chain_context=chain_context,
            tushare_text=tushare_text,
            search_materials=search_materials[:3000],
            counter_text=counter_text,
            chain_text=chain_text,
        )

        # v0.20: 3 轮并行 LLM 调用
        N_ROUNDS = getattr(settings, "PROSPERITY_VERIFY_ROUNDS", 3)
        raw_outputs: list[Optional[str]] = [None] * N_ROUNDS

        with ThreadPoolExecutor(max_workers=N_ROUNDS) as executor:
            futures = {executor.submit(self._call_verify_llm, prompt): i for i in range(N_ROUNDS)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    raw_outputs[idx] = future.result()
                except Exception as e:
                    logger.error(f"LLM verify round {idx+1} exception: {e}")

        # 过滤掉失败的轮次
        valid_outputs = [r for r in raw_outputs if r is not None]

        if not valid_outputs:
            logger.warning(f"All {N_ROUNDS} LLM verify rounds failed for {chain_label}")
            return {"hypotheses": [{**h, "status": "unverified", "reason": "LLM 多轮调用全部失败",
                                      "causality_strength": "moderate", "causality_note": ""}
                                     for h in chain]}

        # 字段级聚合
        n_valid = len(valid_outputs)
        logger.debug(f"  {chain_label}: {n_valid}/{N_ROUNDS} rounds valid, aggregating")
        return self._aggregate_rounds(valid_outputs, chain)

    def _parse_verification_raw(self, llm_output: str) -> Optional[dict]:
        """纯 JSON 解析 LLM 输出（不含后处理）。v0.20 新增。"""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            arr_match = re.search(r"\{[\s\S]*\}", json_str)
            if arr_match:
                try:
                    return json.loads(arr_match.group(0))
                except json.JSONDecodeError:
                    pass
            return None

    def _aggregate_rounds(self, rounds_raw: list[str], chain: list[dict]) -> dict:
        """对 N 轮 LLM 输出做字段级聚合，合成最终验证结果。v0.20 新增。

        Args:
            rounds_raw: 每轮的 LLM 原始响应文本
            chain: 原始假设链（用于字段保留和兜底）

        Returns:
            聚合后的验证结果，格式与 _parse_verification_result 返回一致
        """
        # Step 1: 逐轮解析
        parsed_rounds = []
        for raw in rounds_raw:
            parsed = self._parse_verification_raw(raw)
            if parsed:
                parsed_rounds.append(parsed)

        if not parsed_rounds:
            return {"hypotheses": [{**h, "status": "unverified", "reason": "LLM 输出解析全部失败"} for h in chain]}

        # Step 2: 对每条假设做字段级聚合
        by_id = {h.get("id"): h for h in chain}
        aggregated_hyps = []

        for orig_h in chain:
            h_id = orig_h.get("id", "")

            # 收集各轮中该假设的输出
            rounds_for_h = []
            for pr in parsed_rounds:
                for vh in pr.get("hypotheses", []):
                    if vh.get("id") == h_id:
                        rounds_for_h.append(vh)

            if not rounds_for_h:
                aggregated_hyps.append({**orig_h, "status": "unverified", "reason": "所有轮次中未找到该假设"})
                continue

            # ── Q1: 交集 → source_count ──
            all_indices = []
            for vh in rounds_for_h:
                indices = vh.get("supporting_source_indices", vh.get("source_count"))  # 兼容旧格式
                if isinstance(indices, list):
                    all_indices.append(set(indices))
                elif isinstance(indices, (int, float)):
                    # 旧格式 source_count，无法做交集，取最大值
                    all_indices.append(set(range(int(indices))))
            if all_indices:
                common = all_indices[0]
                for s in all_indices[1:]:
                    common = common & s
                source_count = len(common)
            else:
                source_count = 0

            # ── Q2: 众数 → data_alignment ──
            da_values = [vh.get("data_alignment", "无相关数据") for vh in rounds_for_h]
            data_alignment = Counter(da_values).most_common(1)[0][0]

            # ── Q3: MAX + 三级分级 → conflict_level（v0.22：替代布尔 yes/no）──
            cc_values = []
            for vh in rounds_for_h:
                score = vh.get("counter_conflict_score", vh.get("counter_conflict"))
                if isinstance(score, (int, float)):
                    cc_values.append(int(score))
                elif score == "yes":
                    cc_values.append(3)  # 旧格式 yes → score 3
                elif score == "no":
                    cc_values.append(0)
                else:
                    cc_values.append(0)

            cc_score = max(cc_values) if cc_values else 0

            # v0.22 三级分级（多轮一致原则）
            # v1.2.1 FIX: weak conflict (score=2) 的多轮一致性不应升级为 strong。
            # 只有 ≥1 轮明确打出 3 分（强反例）+ ≥2 轮检测到任何冲突（非孤立），才算 strong。
            # 否则 3 轮都打 2 分（"有矛盾但不推翻"）→ weak → weak_disputed（不切链）。
            strong = (
                any(v == 3 for v in cc_values)           # 至少一轮明确认定为强反例
                and sum(1 for v in cc_values if v > 0) >= 2  # 非孤立异常值
            )

            if strong:
                conflict_level = "strong"
            elif any(v == 2 for v in cc_values):
                conflict_level = "weak"    # 至少一轮打2分但非strong
            else:
                conflict_level = "none"

            # ── Q4 sentiment: 众数 → verified_sentiment ──
            sent_values = [vh.get("sentiment", "neutral") for vh in rounds_for_h]
            verified_sentiment = Counter(sent_values).most_common(1)[0][0]

            # ── Q5 chain_fit: 众数 → aggregated_chain_fit（v1.0.3）──
            cf_values = [vh.get("chain_fit", "") for vh in rounds_for_h if vh.get("chain_fit") in ("aligned", "misaligned")]
            aggregated_chain_fit = Counter(cf_values).most_common(1)[0][0] if cf_values else ""

            # ── 其他字段取第一轮 ──
            base = dict(rounds_for_h[0])

            # 确定性合成 status + confidence（v0.22: conflict_level，v1.0.3: +chain_fit 加权）
            base["source_count"] = source_count
            base["data_alignment"] = data_alignment
            base["counter_conflict_score"] = cc_score
            base["conflict_level"] = conflict_level
            base["chain_fit"] = aggregated_chain_fit
            base["status"] = _synthesize_status(source_count, data_alignment, conflict_level, aggregated_chain_fit)
            base["confidence"] = _synthesize_confidence(source_count, data_alignment, conflict_level, aggregated_chain_fit)
            base["verified_sentiment"] = verified_sentiment

            # 保留原始字段（不覆盖 HypothesizeAgent 产出的 sentiment）
            if h_id in by_id:
                orig = by_id[h_id]
                for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
                            "sources", "time_horizon", "key_indicators", "investment_implication",
                            "wiki_path", "verification_needed", "tier",
                            "sentiment", "causality_strength", "causality_note"):
                    if key in orig and key not in base:
                        base[key] = orig[key]

            # 日志
            logger.debug(
                f"  {h_id}: Q1_indices→{source_count} Q2_mode={data_alignment} "
                f"Q3_max={cc_score}→{conflict_level} Q4_mode={verified_sentiment} "
                f"Q5_chain={aggregated_chain_fit} → {base['status']}/{base['confidence']}"
            )

            aggregated_hyps.append(base)

        chain_label = parsed_rounds[0].get("chain_label", "")
        return {
            "chain_label": chain_label,
            "hypotheses": aggregated_hyps,
        }

    def _parse_verification_result(self, llm_output: str, original_chain: list[dict]) -> dict:
        """解析 LLM 验证输出，确定性合成 status + confidence（兼容新旧格式）。

        v0.20: 保留作为向后兼容路径。当 _aggregate_rounds 不可用时（如单轮模式），
        本方法仍可处理旧格式 source_count/counter_conflict 和新格式 supporting_source_indices/counter_conflict_score。
        v1.0.3: 支持 Q5 chain_fit 字段。
        """
        result = self._parse_verification_raw(llm_output)
        if result is None:
            return {"hypotheses": [{**h, "status": "unverified", "reason": "JSON 解析失败"} for h in original_chain]}

        verified_hyps = result.get("hypotheses", [])
        by_id = {h.get("id"): h for h in original_chain}
        for vh in verified_hyps:
            h_id = vh.get("id", "")
            if h_id in by_id:
                orig = by_id[h_id]
                for key in ("title", "statement", "reasoning", "chain_level", "derives_from",
                            "sources", "time_horizon", "key_indicators", "investment_implication",
                            "wiki_path", "verification_needed", "tier",
                            "sentiment", "causality_strength", "causality_note"):
                    if key in orig and key not in vh:
                        vh[key] = orig[key]

            # v0.22: 兼容新旧两种输入格式
            # 新格式: supporting_source_indices + counter_conflict_score → conflict_level
            # 旧格式: source_count + counter_conflict → conflict_level
            if "supporting_source_indices" in vh:
                indices = vh.get("supporting_source_indices", [])
                sc = len(indices) if isinstance(indices, list) else 0
            else:
                sc = vh.get("source_count", 0)

            if "counter_conflict_score" in vh:
                cc_score = int(vh.get("counter_conflict_score", 0))
            elif "counter_conflict" in vh:
                old_cc = vh.get("counter_conflict", "no")
                cc_score = 3 if old_cc == "yes" else 0
            else:
                cc_score = 0

            # v0.22: 单轮路径也用三级分级（单轮时：3→strong, 2→weak, ≤1→none）
            if cc_score >= 3:
                conflict_level = "strong"
            elif cc_score == 2:
                conflict_level = "weak"
            else:
                conflict_level = "none"

            da = vh.get("data_alignment", "无相关数据")

            # v1.0.3: 提取 Q5 chain_fit
            chain_fit = vh.get("chain_fit", "")

            vh["status"] = _synthesize_status(sc, da, conflict_level, chain_fit)
            vh["confidence"] = _synthesize_confidence(sc, da, conflict_level, chain_fit)

            # 保留 LLM 输出的 sentiment 作为 verified_sentiment
            llm_sent = vh.get("sentiment")
            if llm_sent and llm_sent in ("positive", "negative", "neutral"):
                vh["verified_sentiment"] = llm_sent

            logger.debug(
                f"  {h_id}: source_count={sc} data_alignment={da} "
                f"cc_score={cc_score}→{conflict_level} chain_fit={chain_fit} "
                f"→ {vh['status']}/{vh['confidence']}"
            )

        return result

    def _format_tushare_data(self, industry_data: dict) -> str:
        """格式化 Tushare 行业数据为 LLM 可读文本"""
        metrics = industry_data.get("metrics", {})
        sample_size = industry_data.get("sample_size", 0)

        lines = [f"成分股数量: {sample_size}", ""]
        for key, val in metrics.items():
            if isinstance(val, dict):
                lines.append(f"**{key}**:")
                for k, v in val.items():
                    if k == "sorted_values":
                        continue
                    lines.append(f"  - {k}: {v}")
            else:
                lines.append(f"**{key}**: {val}")
        return "\n".join(lines) if lines else "（无 Tushare 行业数据）"

    def _format_counter_evidence(self, counter_evidence: list[dict]) -> str:
        """格式化反例搜索证据"""
        if not counter_evidence:
            return "（无反例搜索证据）"

        by_query: dict[str, list] = {}
        for r in counter_evidence:
            q = r.get("query", "")
            if q not in by_query:
                by_query[q] = []
            by_query[q].append(r)

        lines = []
        for query, results in by_query.items():
            lines.append(f"**搜索词**: {query} — {len(results)} 条结果")
            for i, r in enumerate(results[:3]):
                lines.append(f"  [{i+1}] {r.get('title', '')}")
                lines.append(f"      {r.get('content', '')[:200]}")
            lines.append("")
        return "\n".join(lines)

    def _build_chain_summary(self, result: dict) -> str:
        """构建链验证摘要（供下一轮串行验证使用）"""
        hyps = result.get("hypotheses", [])
        lines = []
        for h in hyps:
            h_id = h.get("id", "")
            status = h.get("status", "")
            reason_short = (h.get("reason", "") or "")[:150]
            causality = h.get("causality_strength", "")
            lines.append(f"- {h_id}: {status} | 因果: {causality} | {reason_short}")
        return "\n".join(lines)

    # ═══════════════════════════════════════════════
    # 确定性后处理
    # ═══════════════════════════════════════════════

    def _cascade_safety_net(self, hypotheses: list[dict], by_id: dict[str, dict]) -> list[dict]:
        """级联安全网：确保上游 overturned → 下游 unreachable（v0.22：仅 overturned 切链）

        v0.22: disputed 已在 VerifyAgent 阶段消化为 overturned/weak_disputed，
        此安全网仅处理 overtuned 的级联传递。weak_disputed 不切断。
        """
        unreachable_ids: set[str] = set()

        # 按层级排序
        sorted_hyps = sorted(hypotheses, key=lambda h: h.get("chain_level", 0))

        for h in sorted_hyps:
            h_id = h.get("id", "")
            # 检查上游
            derives = h.get("derives_from", [])
            if isinstance(derives, str):
                derives = [d.strip() for d in derives.split(",") if d.strip()]

            for up_id in derives:
                if up_id in unreachable_ids:
                    h["status"] = "unreachable"
                    h["causality_strength"] = "broken"
                    h["causality_note"] = f"级联安全网：上游 {up_id} 已不可达"
                    unreachable_ids.add(h_id)
                    break

            # 上游 overturned 也标记下游（v0.22：移除 disputed）
            if h_id not in unreachable_ids:
                for up_id in derives:
                    up = by_id.get(up_id, {})
                    if up.get("status") in ("overturned", "unreachable"):
                        h["status"] = "unreachable"
                        h["causality_strength"] = "broken"
                        h["causality_note"] = f"级联安全网：上游 {up_id} 为 {up.get('status')}"
                        unreachable_ids.add(h_id)
                        break

        return hypotheses

    # ═══════════════════════════════════════════════
    # 页面写入 + DB 更新
    # ═══════════════════════════════════════════════

    def _update_hypothesis_pages(self, industry_name: str, verified: list[dict]) -> None:
        """更新假设 Markdown 页面的验证章节（v3：含修正陈述 + 因果强度）"""
        for v in verified:
            wiki_path = v.get("wiki_path", "")
            if not wiki_path:
                continue
            full_path = self.data_dir / wiki_path
            if not full_path.exists():
                continue

            content = full_path.read_text(encoding="utf-8")
            status = v.get("status", "unverified")
            emoji = STATUS_EMOJI.get(status, "🔍 UNVERIFIED")
            reason = v.get("reason", "")
            corrected = v.get("corrected_statement", "")
            causality = v.get("causality_strength", "")
            causality_note = v.get("causality_note", "")
            confidence = v.get("confidence", "")

            verification_block_parts = [
                f"\n**验证结果**: {emoji}",
                f"\n**置信度**: {confidence}",
                f"\n**验证说明**: {reason}",
            ]
            if corrected:
                verification_block_parts.append(f"\n**修正陈述**: {corrected}")
            if causality:
                verification_block_parts.append(f"\n**因果箭头强度**: {causality} — {causality_note}")
            verification_block_parts.append(f"\n**验证时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            verification_block = "".join(verification_block_parts)

            if "## 验证\n\n（待验证）" in content:
                content = content.replace(
                    "## 验证\n\n（待验证）",
                    f"## 验证\n{verification_block}"
                )
            elif "## 验证" in content:
                # 追加上一次验证之后
                content = content + f"\n---\n### 最新验证 ({datetime.now().strftime('%Y-%m-%d')})\n{verification_block}"

            full_path.write_text(content, encoding="utf-8")

    def _update_db(self, session_id: int, verified: list[dict]) -> None:
        """更新数据库中的假设状态（含 v3 新字段）"""
        db = get_db_session()
        try:
            db_hypotheses = db.query(Hypothesis).filter_by(session_id=session_id).all()
            title_map = {h.title: h for h in db_hypotheses}
            for v in verified:
                h = title_map.get(v.get("title"))
                if h:
                    h.status = v.get("status", "unverified")
                    h.sentiment = v.get("sentiment")
                    h.causality_strength = v.get("causality_strength")
                    h.causality_note = v.get("causality_note", "")[:500] if v.get("causality_note") else None
                    h.updated_at = datetime.utcnow()
            db.commit()
        finally:
            db.close()
