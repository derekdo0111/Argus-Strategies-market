"""ScreeningAgent — v1.2.0 精选推荐（预筛→财务预排→LLM精选→打分排名）

职责（重构后）：
1. Stage 1: 程序化预筛 + 分段 + 全量财务拉取 + 预排名
2. Stage 2: LLM 精选（每段独立调用，从候选池挑 top K）
3. Stage 3: 程序化三维打分 + 分段排名

核心变更（vs v1.1.0）:
- 旧: LLM 一次全部 201 只分类+标记 → 超时 → 兜底无假设命中
- 新: 程序化预筛 → 每段 LLM 只挑 5-8 只 → 每只有命中假设+挑选理由
- 代表公司强制豁免进入候选池（解决财务排名排除战略重要股的问题）
- purity_estimate 程序化计算（营收比例），不浪费 LLM token
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests
import yaml

from app.core.config import settings
from app.strategies.prosperity.tools.stock_screener import score_stocks
from app.strategies.prosperity.tools.industry_metrics import (
    compute_industry_metrics,
    get_industry_ts_codes,
    get_stock_name_map,
)
from app.strategies.prosperity.tools.purity_scorer import get_batch_mainbz
from app.strategies.prosperity.tools.screening_scorer import (
    hypothesis_weight,
    hypothesis_direction,
    format_hypothesis_tree,
    score_stock_pool,
)
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)


# ── 默认环节关键词（链 YAML 可能为空，此为基础兜底）────────────────
_SEGMENT_KEYWORDS_DEFAULT = {
    "upstream":   ["设备", "材料", "硅片", "光刻", "刻蚀", "薄膜", "清洗", "EDA", "IP"],
    "mid":        ["设计", "制造", "晶圆", "DRAM", "NAND", "封测", "存储", "芯片", "HBM"],
    "downstream": ["模组", "SSD", "存储卡", "分销", "代理", "应用"],
}

# 下游排他关键词：命中这些的公司优先归 downstream 而非 mid
_DOWNSTREAM_FORCE = {"模组", "SSD", "存储卡", "分销", "代理"}

_SEGMENT_LABELS = {
    "upstream": "上游设备与材料",
    "mid": "中游设计与制造",
    "downstream": "下游模组与应用",
}


class ScreeningAgent:
    """v1.2.0：精选推荐"""

    def __init__(self, data_dir: Path = None, rules_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR
        self.top_k = getattr(settings, "PROSPERITY_SCREENING_TOP_PER_SEGMENT", 6)
        self.llm_timeout = getattr(settings, "PROSPERITY_SCREENING_LLM_TIMEOUT", 180)
        self._load_template()

    def _load_template(self) -> None:
        template_path = self.rules_dir / "prompts" / "screening_direction_prompt.md"
        if template_path.exists():
            self.template = template_path.read_text(encoding="utf-8")
        else:
            logger.warning(f"Screening prompt template not found: {template_path}")
            self.template = ""

    # ── 主入口 ─────────────────────────────────────────────────

    def screen(
        self,
        industry_name: str,
        session_id: int,
        verification: dict,
        search_result: dict,
        history=None,
        chain_model=None,
    ) -> dict:
        """v1.2.0: 程序化预筛 → LLM 精选 → 三维打分 → 分段排名"""
        logger.info(f"ScreeningAgent v1.2.0: screening stocks for {industry_name}")

        ts_codes = get_industry_ts_codes(industry_name)
        if not ts_codes:
            logger.warning(f"ScreeningAgent: no stocks found for {industry_name}")
            return {
                "industry": industry_name, "session_id": session_id,
                "stock_pool": [], "segments": {}, "direction_scores": {},
            }

        name_map = get_stock_name_map()
        hypotheses = verification.get("hypotheses", [])

        # ── Stage 0: 拉取主营业务 ──
        print(f"      -> [Stage 0/3] 拉取主营业务（{len(ts_codes)} 只）...", flush=True)
        mainbz_data = get_batch_mainbz(ts_codes)
        n_with_bz = len(mainbz_data)
        if n_with_bz < len(ts_codes):
            print(f"         -> {n_with_bz}/{len(ts_codes)} 只有主营业数据", flush=True)

        # ── Stage 1: 程序化预筛 + 分段 + 财务预排 ──
        print(f"      -> [Stage 1/3] 程序化预筛 + 分段 + 财务预排...", flush=True)
        segment_kw = _extract_segment_keywords(chain_model)
        rep_companies = _extract_rep_companies(chain_model, name_map)
        segment_stocks = _programmatic_prescreen(
            ts_codes, name_map, mainbz_data, chain_model, segment_kw, rep_companies,
        )

        n_excluded = len(ts_codes) - sum(len(v) for v in segment_stocks.values())
        for seg, label in _SEGMENT_LABELS.items():
            print(f"         -> {label}: {len(segment_stocks[seg])} 只", flush=True)
        if n_excluded > 0:
            print(f"         -> 排除: {n_excluded} 只（主营业不匹配）", flush=True)

        # 全量拉财务（对所有非排除股票）
        all_surviving = []
        for seg_stocks in segment_stocks.values():
            all_surviving.extend(seg_stocks)
        if not all_surviving:
            return _empty_result(industry_name, session_id, ts_codes)

        finance_map, _ = self._pull_financials(all_surviving, industry_name)

        # 计算关联占比（程序化：营收比例）
        purity_map = {}
        for seg, stocks in segment_stocks.items():
            for ts in stocks:
                purity_map[ts] = _compute_purity(ts, mainbz_data, seg, segment_kw)

        # 每段内财务预排名 → 候选池
        candidate_pool = {}
        for seg, stocks in segment_stocks.items():
            ranked = _financial_prerank(stocks, finance_map, purity_map)
            # 取候选人：min(top K*3, 全量)，但代表公司强制保留
            pool_size = min(self.top_k * 3, len(ranked))
            candidates = ranked[:pool_size]
            # 补回被财务排名排掉的代表公司
            rep_in_seg = rep_companies.get(seg, set())
            for ts in rep_in_seg:
                if ts in stocks and ts not in candidates:
                    candidates.append(ts)
            candidate_pool[seg] = candidates
            print(f"         -> {_SEGMENT_LABELS.get(seg, seg)} 候选池: {len(candidates)} 只 "
                  f"({len(rep_in_seg & set(stocks))} 代表公司)", flush=True)

        # ── Stage 2: LLM 精选 ──
        print(f"      -> [Stage 2/3] LLM 精选（每段挑 {self.top_k} 只）...", flush=True)
        selected_matches = self._llm_select_batched(
            industry_name, candidate_pool, name_map, mainbz_data,
            finance_map, hypotheses, search_result, chain_model,
            segment_kw, purity_map,
        )

        n_selected = len(selected_matches)
        print(f"         -> LLM 精选: {n_selected} 只入选", flush=True)

        if not selected_matches:
            # LLM 全失败 → 程序化兜底：每段取财务 top K
            print(f"         -> LLM 全部失败，程序化兜底取财务 top {self.top_k}", flush=True)
            for seg, candidates in candidate_pool.items():
                for ts in candidates[:self.top_k]:
                    selected_matches.append({
                        "ts_code": ts,
                        "segment": seg,
                        "positive_hits": [],
                        "negative_hits": [],
                        "purity_estimate": purity_map.get(ts, 1.0),
                        "excluded": False,
                        "exclude_reason": "",
                        "selection_reason": "程序化兜底·财务预排名",
                    })

        # ── Stage 3: 程序化三维打分 + 分段排名 ──
        print(f"      -> [Stage 3/3] 三维打分 + 分段排名...", flush=True)
        scored = score_stock_pool(selected_matches, hypotheses)

        # 补充财务质量分
        for ts in (m["ts_code"] for m in selected_matches):
            if ts in scored:
                roe = finance_map.get(ts, {}).get("roe", 0)
                gpm = finance_map.get(ts, {}).get("gross_margin", 0)
                rev = finance_map.get(ts, {}).get("revenue_yoy", 0)
                quality = _calc_quality(roe, gpm, rev)
                scored[ts]["quality"] = quality
                scored[ts]["composite"] = round(
                    scored[ts]["prosperity_fit"] * 0.5
                    - scored[ts]["risk_exposure"] * 0.3
                    + quality * 0.2,
                    4,
                )

        # 补充 selection_reason 到 scored
        for m in selected_matches:
            ts = m.get("ts_code", "")
            if ts in scored:
                scored[ts]["selection_reason"] = m.get("selection_reason", "")

        # 构建股池
        stock_pool = []
        raw_indicators_map = {}
        # 只拉选中股票的 raw_indicators（复用前面的 finance_map 不够，需要 raw）
        if selected_matches:
            selected_codes = [m["ts_code"] for m in selected_matches]
            _, raw_indicators_map = self._pull_financials(selected_codes, industry_name)

        for m in selected_matches:
            ts = m.get("ts_code", "")
            s = scored.get(ts, {})
            raw = raw_indicators_map.get(ts, {})
            stock_pool.append({
                "ts_code": ts,
                "name": name_map.get(ts, ts),
                "segment": s.get("segment", m.get("segment", "")),
                "prosperity_fit": s.get("prosperity_fit", 0),
                "risk_exposure": s.get("risk_exposure", 0),
                "quality": s.get("quality", 0),
                "composite": s.get("composite", 0),
                "purity_estimate": m.get("purity_estimate", 1.0),
                "hit_hypotheses": s.get("hit_hypotheses", []),
                "selection_reason": m.get("selection_reason", ""),
                "raw_indicators": raw,
                "final_score": round(s.get("composite", 0), 4),
                "score_total": round(s.get("composite", 0) * 100, 1),
            })

        # 按 segment 分组排序
        segments = {"upstream": [], "mid": [], "downstream": []}
        for sp in stock_pool:
            seg = sp.get("segment", "")
            if seg in segments:
                segments[seg].append(sp)

        for seg_name, seg_list in segments.items():
            seg_list.sort(key=lambda x: x["composite"], reverse=True)
            for i, s in enumerate(seg_list):
                s["rank"] = i + 1

        # 全量排名
        stock_pool.sort(key=lambda x: x["composite"], reverse=True)
        for i, s in enumerate(stock_pool):
            s["rank_overall"] = i + 1

        # 构建 direction_scores（向后兼容）
        direction_scores = {}
        for m in selected_matches:
            ts = m.get("ts_code", "")
            s = scored.get(ts, {})
            direction_scores[ts] = {
                "segment": s.get("segment", ""),
                "matched_hypotheses": s.get("hit_hypotheses", []),
                "excluded": False,
                "exclude_reason": "",
            }

        # 写入股池 YAML
        pool_path = self.data_dir / "raw" / industry_name / "stock_pool.yaml"
        pool_path.parent.mkdir(parents=True, exist_ok=True)
        with open(pool_path, "w", encoding="utf-8") as f:
            yaml.dump(stock_pool, f, allow_unicode=True)

        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"ScreeningAgent v1.2.0: {len(stock_pool)} stocks for {industry_name}")

        return {
            "industry": industry_name,
            "session_id": session_id,
            "stock_pool": stock_pool,
            "segments": segments,
            "direction_scores": direction_scores,
        }

    # ── 财务拉取 ───────────────────────────────────────────────

    def _pull_financials(
        self, ts_codes: list[str], industry_name: str
    ) -> tuple[dict, dict]:
        """拉取财务数据 → {ts: {roe, gross_margin, revenue_yoy}} + raw_indicators"""
        finance_map: dict[str, dict] = {}
        raw_map: dict[str, dict] = {}
        try:
            industry_metrics = compute_industry_metrics(ts_codes, industry_name)
            finance_list = score_stocks(ts_codes, industry_metrics, name_map=get_stock_name_map())
            for s in finance_list:
                ts = s.get("ts_code", "")
                raw = s.get("raw_indicators", {})
                finance_map[ts] = {
                    "roe": raw.get("roe", 0),
                    "gross_margin": raw.get("gross_margin", 0),
                    "revenue_yoy": raw.get("revenue_yoy", 0),
                }
                raw_map[ts] = raw
        except Exception as e:
            logger.warning(f"Financial scoring failed: {e}")
            for ts in ts_codes:
                finance_map[ts] = {"roe": 0, "gross_margin": 0, "revenue_yoy": 0}
                raw_map[ts] = {}
        return finance_map, raw_map

    # ── 产业链上下文格式化 ─────────────────────────────────────

    def _format_chain_context(self, chain_model: dict | None) -> str:
        """将产业链拓扑 YAML 转为 prompt 友好文本。"""
        if not chain_model:
            return "（首次运行，产业链拓扑尚未建立。按通用规则匹配。）"

        lines = []
        chain = chain_model.get("chain", {})
        segments = chain.get("segments", [])

        lines.append("### 产业链环节代表公司（正例锚点）")
        lines.append("")
        lines.append("| 环节 | 位置 | 瓶颈级别 | 国产化率 | 代表公司 |")
        lines.append("|------|------|----------|----------|----------|")
        position_order = {"upstream": 0, "mid": 1, "downstream": 2}
        for seg in sorted(segments, key=lambda s: position_order.get(s.get("position", ""), 99)):
            name = seg.get("name", "")
            pos = seg.get("position", "")
            b = seg.get("bottleneck", {})
            b_level = b.get("level", "?")
            b_rate = b.get("localization_rate", "?")
            reps = "、".join(seg.get("representative_companies", [])[:6])
            lines.append(f"| {name} | {pos} | {b_level} | ~{b_rate}% | {reps} |")
        lines.append("")

        lines.append("### 供需判断")
        sd = chain_model.get("supply_demand", {})
        if sd.get("overall_judgment"):
            lines.append(f"- 整体: {sd['overall_judgment']}")

        return "\n".join(lines)

    # ── LLM 精选（分段调用）─────────────────────────────────

    def _llm_select_batched(
        self,
        industry_name: str,
        candidate_pool: dict[str, list[str]],
        name_map: dict[str, str],
        mainbz_data: dict[str, list[dict]],
        finance_map: dict[str, dict],
        hypotheses: list[dict],
        search_result: dict,
        chain_model=None,
        segment_kw: dict[str, list[str]] = None,
        purity_map: dict[str, float] = None,
    ) -> list[dict]:
        """分段 LLM 精选：每段独立调用，从候选池中挑 top K。

        返回格式同旧 _llm_classify_and_match 兼容 score_stock_pool()。
        """
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key or not self.template:
            return []  # 无 LLM，走兜底

        hypothesis_tree_text = format_hypothesis_tree(hypotheses)
        chain_context = self._format_chain_context(chain_model)

        all_selected = []
        for seg, candidates in candidate_pool.items():
            if not candidates:
                continue

            seg_label = _SEGMENT_LABELS.get(seg, seg)
            k = min(self.top_k, len(candidates))
            if k == 0:
                continue

            # 构建该段候选池文本（含主营业 + 财务摘要）
            biz_text = self._format_candidate_pool(
                seg, candidates, name_map, mainbz_data, finance_map, purity_map or {}
            )

            prompt = self.template.format(
                industry_name=industry_name,
                segment_label=seg_label,
                chain_context=chain_context,
                hypothesis_tree_text=hypothesis_tree_text,
                biz_text=biz_text,
                k=k,
            )

            print(f"         -> LLM 精选 {seg_label}（{len(candidates)} 选 {k}）...", flush=True)
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
                            {"role": "system", "content": "你是一位投资研究分析师。只输出要求的 JSON 格式，不要其他内容。"},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.0,
                        "max_tokens": settings.LLM_MAX_TOKENS,
                    },
                    timeout=self.llm_timeout,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    parsed = self._parse_selection_result(content, seg, purity_map or {})
                    all_selected.extend(parsed)
                    print(f"            -> 选中 {len(parsed)} 只", flush=True)
                else:
                    logger.error(f"LLM select failed for {seg}: {resp.status_code}")
            except Exception as e:
                logger.error(f"LLM select exception for {seg}: {e}")

        return all_selected

    def _format_candidate_pool(
        self,
        segment: str,
        candidates: list[str],
        name_map: dict[str, str],
        mainbz_data: dict[str, list[dict]],
        finance_map: dict[str, dict],
        purity_map: dict[str, float],
    ) -> str:
        """格式化候选池文本（主营业 + 财务摘要 + 关联占比）"""
        parts = []
        for i, ts in enumerate(candidates):
            name = name_map.get(ts, ts)
            items = mainbz_data.get(ts, [])
            fin = finance_map.get(ts, {})
            purity = purity_map.get(ts, 1.0)

            # 主营业（最多 5 条）
            biz_strs = []
            for it in items[:5]:
                biz_strs.append(f"{it['bz_item']}（{it['bz_sales']/1e8:.1f}亿）")
            biz_line = "；".join(biz_strs) if biz_strs else "无主营业数据"

            # 财务摘要
            roe = fin.get("roe", 0) or 0
            gpm = fin.get("gross_margin", 0) or 0
            rev = fin.get("revenue_yoy", 0) or 0

            parts.append(
                f"#{i+1} {ts} ({name}) | 关联占比 {purity:.0%} | ROE {roe:.1f}% | 毛利率 {gpm:.1f}% | 营收增速 {rev:.1f}%\n"
                f"  主营: {biz_line}"
            )
        return "\n".join(parts)

    def _parse_selection_result(
        self, llm_output: str, segment: str, purity_map: dict[str, float]
    ) -> list[dict]:
        """解析 LLM 精选输出 → 标准化 match 列表"""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output

        try:
            result = json.loads(json_str)
        except json.JSONDecodeError:
            arr_match = re.search(r"\{[\s\S]*\}", json_str)
            if arr_match:
                try:
                    result = json.loads(arr_match.group(0))
                except json.JSONDecodeError:
                    return []
            else:
                return []

        raw_selected = result.get("selected", [])
        parsed = []
        for m in raw_selected:
            ts = m.get("ts_code", "")
            if not ts:
                continue
            parsed.append({
                "ts_code": ts,
                "segment": segment,
                "positive_hits": m.get("positive_hits", []),
                "negative_hits": m.get("negative_hits", []),
                "purity_estimate": purity_map.get(ts, 1.0),
                "excluded": False,
                "exclude_reason": "",
                "selection_reason": m.get("selection_reason", ""),
            })
        return parsed


# ── 程序化预筛函数 ──────────────────────────────────────────────

def _extract_rep_companies(chain_model: dict | None, name_map: dict[str, str]) -> dict[str, set[str]]:
    """从链 YAML 提取代表公司 → {segment: {ts_code, ...}}

    链 YAML 中的公司名可能是中文简称（如 "江波龙"），需映射到 ts_code。
    """
    result: dict[str, set[str]] = {"upstream": set(), "mid": set(), "downstream": set()}
    if not chain_model:
        return result

    # 构建 name → ts_code 反向映射
    name_to_code: dict[str, str] = {}
    for ts_code, name in name_map.items():
        name_to_code[name] = ts_code
        # 也存去掉后缀的简称
        short = re.sub(r"\(.*\)", "", name).strip()
        if short and short != name:
            name_to_code[short] = ts_code

    chain = chain_model.get("chain", {})
    for seg in chain.get("segments", []):
        pos = seg.get("position", "")
        if pos not in result:
            continue
        for c in seg.get("representative_companies", []):
            # c 可能是 "江波龙 (301308.SZ)" 或 "江波龙" 或 "301308.SZ"
            if re.match(r"\d{6}\.\w{2}", c):
                # 已是 ts_code
                result[pos].add(c)
            else:
                # 尝试从 name_map 查找
                pure_name = re.sub(r"\(.*\)", "", c).strip()
                for name, code in name_to_code.items():
                    if pure_name in name or name == pure_name:
                        result[pos].add(code)
                        break

    return result


def _extract_segment_keywords(chain_model: dict | None) -> dict[str, list[str]]:
    """从链 YAML 提取环节 → 关键词映射。无 YAML 时用默认。"""
    if not chain_model:
        return _SEGMENT_KEYWORDS_DEFAULT

    result: dict[str, list[str]] = {}
    chain = chain_model.get("chain", {})
    for seg in chain.get("segments", []):
        pos = seg.get("position", "")
        name = seg.get("name", "")
        desc = seg.get("description", "")

        keywords = set()
        for part in [name, desc]:
            words = re.split(r"[，,。.、；;：:\s()（）\[\]【】/]", part)
            for w in words:
                w = w.strip()
                if 2 <= len(w) <= 6:
                    keywords.add(w)

        # 合并默认关键词（增强覆盖率）
        default_kw = _SEGMENT_KEYWORDS_DEFAULT.get(pos, [])
        keywords.update(default_kw)
        result[pos] = list(keywords)

    # 兜底
    for pos in ("upstream", "mid", "downstream"):
        if pos not in result:
            result[pos] = _SEGMENT_KEYWORDS_DEFAULT.get(pos, [])

    return result


def _programmatic_prescreen(
    ts_codes: list[str],
    name_map: dict[str, str],
    mainbz_data: dict[str, list[dict]],
    chain_model: dict | None,
    segment_kw: dict[str, list[str]],
    rep_companies: dict[str, set[str]],
) -> dict[str, list[str]]:
    """程序化预筛：segment 分类 + 排除无关。

    Returns:
        {upstream: [ts_code, ...], mid: [...], downstream: [...]}
    """
    result: dict[str, list[str]] = {"upstream": [], "mid": [], "downstream": []}

    # 构建"代表公司 → segment" 映射
    rep_to_seg: dict[str, str] = {}
    for seg, codes in rep_companies.items():
        for code in codes:
            rep_to_seg[code] = seg

    for ts in ts_codes:
        # 代表公司 → 直接归类
        if ts in rep_to_seg:
            result[rep_to_seg[ts]].append(ts)
            continue

        items = mainbz_data.get(ts, [])
        if not items:
            continue  # 无主营业数据 → 排除

        biz_full = " ".join(it["bz_item"] for it in items)

        # 精细匹配：先检查下游排他关键词，再检查上游/中游
        seg = ""
        is_downstream = any(kw in biz_full for kw in _DOWNSTREAM_FORCE)
        if is_downstream:
            seg = "downstream"
        else:
            # 按 upstream > mid > downstream 顺序匹配
            for try_seg in ("upstream", "mid", "downstream"):
                for kw in segment_kw.get(try_seg, []):
                    if kw in biz_full:
                        seg = try_seg
                        break
                if seg:
                    break

        if seg:
            result[seg].append(ts)

    return result


def _compute_purity(
    ts_code: str,
    mainbz_data: dict[str, list[dict]],
    segment: str,
    segment_kw: dict[str, list[str]],
) -> float:
    """程序化计算关联占比：行业相关业务线营收 / 总营收。"""
    items = mainbz_data.get(ts_code, [])
    if not items:
        return 0.0

    total_rev = sum(it.get("bz_sales", 0) for it in items)
    if total_rev <= 0:
        return 0.0

    # 使用对应 segment 的关键词匹配
    keywords = segment_kw.get(segment, [])
    related_rev = 0.0
    for it in items:
        biz = it.get("bz_item", "")
        for kw in keywords:
            if kw in biz:
                related_rev += it.get("bz_sales", 0)
                break

    purity = related_rev / total_rev
    return round(min(purity, 1.0), 4)


def _financial_prerank(
    ts_codes: list[str],
    finance_map: dict[str, dict],
    purity_map: dict[str, float],
) -> list[str]:
    """按质量分预排名。"""
    scored = []
    for ts in ts_codes:
        fin = finance_map.get(ts, {})
        roe = fin.get("roe", 0) or 0
        gpm = fin.get("gross_margin", 0) or 0
        rev = fin.get("revenue_yoy", 0) or 0
        quality = _calc_quality(roe, gpm, rev)
        scored.append((ts, quality))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [ts for ts, _ in scored]


def _calc_quality(roe: float, gpm: float, rev: float) -> float:
    """计算质量分（归一化到 0~1）"""
    roe_n = max(0, min(roe, 30)) / 30 if roe else 0.5
    gpm_n = max(0, min(gpm, 60)) / 60 if gpm else 0.5
    rev_n = max(0, min(rev, 50)) / 50 if rev else 0.5
    return round((roe_n + gpm_n + rev_n) / 3, 4)


def _empty_result(industry_name: str, session_id: int, ts_codes: list) -> dict:
    return {
        "industry": industry_name, "session_id": session_id,
        "stock_pool": [], "segments": {},
        "direction_scores": {},
    }
