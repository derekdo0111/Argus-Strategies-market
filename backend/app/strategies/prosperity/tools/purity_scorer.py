"""业务纯度打分 — v0.18 新增

基于 Tushare fina_mainbz_vip（主营业务构成）计算每只股票与投资方向的业务纯度。
纯度分 = 相关业务线收入 / 总收入（线性映射 0~1），作为股池排名依据。

流程：
1. 批量拉取 fina_mainbz_vip → 获取所有股票的分业务收入
2. LLM 批量匹配：哪些业务线属于核聚变/L3 方向
3. 计算纯度分 = SUM(相关业务收入) / SUM(全部业务收入)
"""

import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_batch_mainbz(ts_codes: list[str]) -> dict[str, list[dict]]:
    """批量拉取主营业务构成数据

    Args:
        ts_codes: 股票代码列表

    Returns:
        {ts_code: [{bz_item, bz_sales, bz_profit, end_date}, ...]}
        找不到数据的股票不会出现在返回中
    """
    try:
        from app.services.tushare_client import TushareClient
        client = TushareClient()
    except Exception as e:
        logger.error(f"TushareClient init failed: {e}")
        return {}

    result: dict[str, list[dict]] = {}
    batch_size = 10  # fina_mainbz_vip 逐只调，控制节奏
    total = len(ts_codes)
    print(f"            [批量拉取主营业务] 共 {total} 只，逐只查询...", flush=True)

    for i, ts_code in enumerate(ts_codes):
        try:
            df = client.get_fina_mainbz(ts_code)
            if df is None or df.empty:
                continue

            # 取最新一期报告数据
            df = df.sort_values("end_date", ascending=False)
            latest_date = df.iloc[0]["end_date"]
            latest_df = df[df["end_date"] == latest_date]

            items = []
            for _, row in latest_df.iterrows():
                bz_sales = _safe_float(row.get("bz_sales"))
                if bz_sales is None or bz_sales <= 0:
                    continue
                items.append({
                    "bz_item": str(row.get("bz_item", "")).strip(),
                    "bz_sales": bz_sales,
                    "bz_profit": _safe_float(row.get("bz_profit")),
                    "end_date": str(latest_date),
                })

            if items:
                result[ts_code] = items

        except Exception as e:
            logger.debug(f"fina_mainbz_vip failed for {ts_code}: {e}")

        # 进度提示
        if (i + 1) % 5 == 0 or i == total - 1:
            print(f"            [{i+1}/{total}] 完成", flush=True)

        # 频率控制
        if (i + 1) % batch_size == 0 and i + 1 < total:
            time.sleep(0.5)

    logger.info(
        f"purity_scorer: fetched mainbz for {len(result)}/{total} stocks"
    )
    return result


def match_business_to_l3(
    industry_name: str,
    ts_codes: list[str],
    name_map: dict[str, str],
    mainbz_data: dict[str, list[dict]],
    hypotheses: list[dict],
    search_result: dict | None = None,
) -> dict[str, dict]:
    """确定性关键词匹配：每只股票的业务线归属哪个 L3 方向。

    v0.19 改造：不再使用 LLM 做一次性全局判断（方差极大），
    改为从 L3 假设中动态提取关键词，用确定性子串匹配。
    只在零匹配时回退到 LLM。

    Args:
        industry_name: 行业名称
        ts_codes: 成分股列表
        name_map: ts_code → 中文名
        mainbz_data: get_batch_mainbz 的输出
        hypotheses: L3 假设列表（含 investment_implication）
        search_result: 搜索素材（作为辅助上下文，用于扩展关键词）

    Returns:
        {ts_code: {related_items, matched_l3}, ...}
    """
    # 提取 L3 假设
    l3_hyps = _extract_l3_hypotheses(hypotheses)
    if not l3_hyps:
        return {ts: {"related_items": [], "matched_l3": None} for ts in ts_codes}

    # 提取关键词（确定性）
    l3_keywords = _extract_l3_keywords(l3_hyps)

    # 确定性匹配
    result = {}
    for ts in ts_codes:
        items = mainbz_data.get(ts, [])
        if not items:
            result[ts] = {"related_items": [], "matched_l3": None}
            continue

        related_items = []
        matched_l3 = None

        for it in items:
            item_name = it["bz_item"]
            for l3_id, keywords in l3_keywords.items():
                for kw in keywords:
                    if kw in item_name:
                        related_items.append(item_name)
                        if matched_l3 is None:
                            matched_l3 = l3_id
                        break  # 已匹配一条 L3，跳出 keyword 循环
                if item_name in related_items:
                    break  # 已匹配，跳出 L3 循环

        result[ts] = {
            "related_items": related_items,
            "matched_l3": matched_l3,
        }

    # 检查是否有任何股票被匹配到
    n_matched = sum(1 for v in result.values() if v["related_items"])
    if n_matched == 0:
        # 关键词零匹配 → 回退 LLM（极少数情况，如行业术语在业务线名中完全不同）
        logger.info(
            f"purity_scorer: keyword matched 0/{len(ts_codes)} stocks, "
            f"fallback to LLM"
        )
        return _llm_match_fallback(industry_name, ts_codes, name_map, mainbz_data, l3_hyps, search_result)

    logger.info(
        f"purity_scorer: keyword matched {n_matched}/{len(ts_codes)} stocks "
        f"(deterministic, {len(l3_hyps)} L3 directions, {sum(len(v) for v in l3_keywords.values())} keywords)"
    )
    return result


def _flatten_field(value) -> str:
    """安全地将字段值转为字符串。

    investment_implication 可能是 dict（如 {'受益环节': '...', '典型标的特征': '...'}），
    也可能是 str。此函数统一处理两种类型。
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # 将 dict 的 value 拼接成字符串（key 如"受益环节"在 STOP_WORDS 中会被过滤掉）
        parts = []
        for k, v in value.items():
            if isinstance(v, str):
                parts.append(v)
        return "，".join(parts)
    if value is None:
        return ""
    # 兜底：转字符串
    return str(value)


def _extract_l3_keywords(l3_hyps: list[dict]) -> dict[str, set[str]]:
    """从 L3 假设中动态提取关键词。

    规则：
    1. 从 investment_implication 提取名词短语（2-4 字的中文片段）
    2. 过滤掉通用词（公司/企业/行业/市场等）
    3. 保留专有名词和技术术语

    Returns:
        {L3_id: {keyword1, keyword2, ...}}
    """
    # 停用词：太泛的词匹配没有区分度
    STOP_WORDS = {
        "公司", "企业", "集团", "行业", "市场", "业务", "经营",
        "从事", "提供", "生产", "销售", "服务", "产品", "技术",
        "领域", "方向", "板块", "相关", "主要", "核心", "增长",
        "发展", "投资", "标的", "关注", "受益", "机会", "个股",
        "龙头", "优势", "领先", "布局", "产能", "需求", "供给",
        "收入", "营收", "利润", "占比", "纯正", "概念",
    }

    import re

    result: dict[str, set[str]] = {}
    for h in l3_hyps:
        h_id = h.get("id", "")
        keywords: set[str] = set()

        for field in ("investment_implication", "statement", "title"):
            raw = h.get(field, "")
            text = _flatten_field(raw) if raw else ""
            if not text:
                continue

            # 按标点拆，然后取 2-4 字片段
            segments = re.split(r"[，,。.、；;：:\s()（）\[\]【】]", text)
            for seg in segments:
                seg = seg.strip()
                if not seg or len(seg) < 2 or len(seg) > 6:
                    continue
                if seg in STOP_WORDS:
                    continue
                keywords.add(seg)

            # 额外：对长文本提取 2-4 字滑动窗口
            if len(text) > 10:
                clean = re.sub(r"[，,。.、；;：:\s()（）\[\]【】]", "", text)
                for win_len in (2, 3, 4):
                    for i in range(len(clean) - win_len + 1):
                        kw = clean[i:i + win_len]
                        if kw not in STOP_WORDS:
                            keywords.add(kw)

        result[h_id] = keywords

    return result


def _llm_match_fallback(
    industry_name: str,
    ts_codes: list[str],
    name_map: dict[str, str],
    mainbz_data: dict[str, list[dict]],
    l3_hyps: list[dict],
    search_result: dict | None = None,
) -> dict[str, dict]:
    """LLM 回退匹配（仅在关键词语法零匹配时使用）"""
    api_key = getattr(settings, "LLM_API_KEY", "")
    if not api_key:
        logger.warning("LLM API 未配置，纯度匹配回退到关键词兜底")
        return _keyword_fallback(ts_codes, mainbz_data, l3_hyps)

    # 构建业务线文本
    biz_text_parts = []
    stocks_with_data = set()
    for ts in ts_codes:
        items = mainbz_data.get(ts, [])
        if not items:
            continue
        stocks_with_data.add(ts)
        name = name_map.get(ts, ts)
        item_strs = [f"  - {it['bz_item']}（收入 {it['bz_sales']/1e8:.2f}亿）" for it in items]
        biz_text_parts.append(f"**{ts} ({name})**:\n" + "\n".join(item_strs))

    if not biz_text_parts:
        return _keyword_fallback(ts_codes, mainbz_data, l3_hyps)

    # 构建 L3 方向文本
    l3_text = ""
    for h in l3_hyps:
        polarity = _detect_polarity(h)
        tag = "✅ 推荐方向" if polarity == "positive" else "⚠️ 规避方向"
        l3_text += f"\n**{h.get('id', '?')}** [{tag}]: {h.get('statement', '')}\n"
        impl = _flatten_field(h.get("investment_implication", ""))
        l3_text += f"**投资含义**: {impl or '无'}\n"

    search_context = _build_search_context_for_purity(search_result, name_map)

    prompt = f"""你是一位投资研究分析师。请根据 L3 选股方向，判断每只股票的业务线归属。

## 行业
{industry_name}

## L3 选股方向
{l3_text}

{search_context}

## 成分股主营业务构成
{chr(10).join(biz_text_parts)}

## 任务

对每只股票：
1. 判断哪些业务线与 L3 方向相关（逐业务线判断）
2. 标注匹配了哪个 L3 假设
3. 如果股票没有任何业务线与 L3 方向相关，related_items 为空

判断规则：
- 业务线名称与 L3 投资含义中的关键词接近 → 匹配
- 业务线名称虽不直接相关，但【搜索素材】中明确描述了该公司的相关业务 → 匹配
- 业务线名称不相关且搜索素材无具体描述 → related_items 为空

## 输出（JSON，只输出 JSON）

```json
{{
  "matches": [
    {{"ts_code": "600105.SH", "related_items": ["超导及铜导体"], "matched_l3": "H3-1"}},
    {{"ts_code": "002735.SZ", "related_items": [], "matched_l3": null}}
  ]
}}
```

请确保覆盖所有股票。"""

    print("         -> 关键词零匹配，回退 LLM（业务线匹配，可能需要 30~60 秒）...", flush=True)
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
            timeout=120,
        )
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_biz_matches(content, ts_codes, mainbz_data, l3_hyps)
        else:
            logger.error(f"LLM biz match failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"LLM biz match exception: {e}")

    return _keyword_fallback(ts_codes, mainbz_data, l3_hyps)


def _detect_polarity(hypothesis: dict) -> str:
    """检测 L3 假设的极性：positive（推荐）或 negative（规避）"""
    if "polarity" in hypothesis:
        return hypothesis["polarity"]
    negative_keywords = ["规避", "排除", "避免", "炒作", "概念炒作", "纯概念"]
    text = " ".join([
        hypothesis.get("statement", ""),
        hypothesis.get("id", ""),
        hypothesis.get("title", ""),
    ])
    for kw in negative_keywords:
        if kw in text:
            return "negative"
    return "positive"


def _build_search_context_for_purity(
    search_result: dict | None,
    name_map: dict[str, str],
) -> str:
    """从搜索素材中提取与成分股相关的上下文片段

    用于纯度打分 prompt，帮助 LLM 在不精确的 Tushare 分类名和
    实际业务之间做语义跳跃（如 "焊接材料" → 核聚变焊接）。
    """
    if not search_result:
        return ""
    
    results = search_result.get("results", [])
    if not results:
        return ""
    
    # 收集搜索素材中出现的公司名及其上下文
    all_names = set(name_map.values())
    company_hints: dict[str, list[str]] = {}
    
    for r in results[:20]:
        content = r.get("content", "")
        for name in all_names:
            if name in content:
                idx = content.find(name)
                start = max(0, idx - 40)
                end = min(len(content), idx + 100)
                snippet = content[start:end].replace("\n", " ").strip()
                if name not in company_hints:
                    company_hints[name] = []
                company_hints[name].append(snippet)
    
    if not company_hints:
        return ""
    
    parts = []
    for name, snippets in company_hints.items():
        unique = list(dict.fromkeys(snippets))[:2]  # 去重，最多2条
        for s in unique:
            parts.append(f"- 「{name}」: ...{s}...")
    
    return "## 搜索素材中的相关公司信息（帮你判断业务线的实际用途）\n" + "\n".join(parts)


def compute_purity_scores(
    ts_codes: list[str],
    mainbz_data: dict[str, list[dict]],
    biz_matches: dict[str, dict],
) -> dict[str, dict]:
    """计算每只股票的纯度分 = 相关业务收入 / 总收入

    Args:
        ts_codes: 成分股列表
        mainbz_data: get_batch_mainbz 的输出
        biz_matches: match_business_to_l3 的输出

    Returns:
        {
            "000657.SZ": {
                "purity_score": 0.55,
                "total_revenue": 52.3e8,
                "related_revenue": 28.7e8,
                "related_share": 0.55,
                "related_items": ["超导线材"],
                "matched_l3": "H3-1",
            },
            ...
        }
    """
    result = {}
    for ts in ts_codes:
        items = mainbz_data.get(ts, [])
        match_info = biz_matches.get(ts, {})
        related_items = match_info.get("related_items", [])
        matched_l3 = match_info.get("matched_l3")

        total_revenue = sum(it["bz_sales"] for it in items)
        related_revenue = sum(
            it["bz_sales"] for it in items
            if it["bz_item"] in related_items
        )

        if total_revenue > 0:
            purity = related_revenue / total_revenue
        else:
            purity = 0.0  # 无收入数据 → 纯度 0

        result[ts] = {
            "purity_score": round(purity, 4),
            "total_revenue": total_revenue,
            "related_revenue": related_revenue,
            "related_share": round(purity, 4),
            "related_items": related_items,
            "matched_l3": matched_l3,
        }

    return result


def _extract_l3_hypotheses(hypotheses: list[dict]) -> list[dict]:
    """提取活跃 L3 假设"""
    l3 = []
    for h in hypotheses:
        if h.get("chain_level") != 3:
            continue
        status = h.get("status", "")
        if status in ("disputed", "overturned", "unreachable"):
            continue
        l3.append(h)
    return l3


def _parse_biz_matches(
    llm_output: str,
    ts_codes: list[str],
    mainbz_data: dict[str, list[dict]],
    hypotheses: list[dict],
) -> dict[str, dict]:
    """解析 LLM 业务匹配输出"""
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
    json_str = match.group(1) if match else llm_output

    # 提取 L3 假设（用于回退）
    l3_hyps = _extract_l3_hypotheses(hypotheses)

    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        arr_match = re.search(r"\{[\s\S]*\}", json_str)
        if arr_match:
            try:
                result = json.loads(arr_match.group(0))
            except json.JSONDecodeError:
                return _keyword_fallback(ts_codes, mainbz_data, l3_hyps)
        else:
            return _keyword_fallback(ts_codes, mainbz_data, l3_hyps)

    matches = result.get("matches", [])
    biz_matches = {}
    for m in matches:
        ts = m.get("ts_code", "")
        if ts:
            biz_matches[ts] = {
                "related_items": m.get("related_items", []),
                "matched_l3": m.get("matched_l3"),
            }

    # 兜底未出现的股票
    for ts in ts_codes:
        if ts not in biz_matches:
            biz_matches[ts] = {"related_items": [], "matched_l3": None}

    return biz_matches


def _keyword_fallback(
    ts_codes: list[str],
    mainbz_data: dict[str, list[dict]],
    l3_hyps: list[dict],
) -> dict[str, dict]:
    """确定性关键词回退匹配（v0.19：使用动态关键词提取）。

    LLM 不可用或解析失败时使用。从 L3 假设中动态提取关键词，
    用确定性子串匹配。同一输入永远同一输出。
    """
    # 动态提取关键词（替换旧版硬编码关键词）
    l3_keywords = _extract_l3_keywords(l3_hyps)

    result = {}
    for ts in ts_codes:
        items = mainbz_data.get(ts, [])
        related = []
        matched_l3 = None
        for it in items:
            item_name = it["bz_item"]
            for l3_id, keywords in l3_keywords.items():
                for kw in keywords:
                    if kw in item_name:
                        related.append(item_name)
                        if matched_l3 is None:
                            matched_l3 = l3_id
                        break
                if item_name in related:
                    break

        result[ts] = {
            "related_items": related,
            "matched_l3": matched_l3,
        }

    n_matched = sum(1 for v in result.values() if v["related_items"])
    logger.info(f"Keyword fallback: matched {n_matched}/{len(ts_codes)} stocks")
    return result


def _safe_float(val) -> Optional[float]:
    """安全转 float"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
