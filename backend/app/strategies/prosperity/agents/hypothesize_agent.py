"""HypothesizeAgent — 因果推理假设形成（v2）

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
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.strategies.prosperity.models import get_session as get_db_session, Hypothesis
from app.strategies.prosperity.tools.wiki_indexer import update_index, append_log

logger = logging.getLogger(__name__)

# 4 层推理链的定义
CHAIN_LEVELS = {
    0: {"name": "现状诊断", "question": "当前行业的客观状态是什么？", "min_count": 2, "max_count": 3},
    1: {"name": "一阶推演", "question": "如果 L0 成立，接下来必然发生什么？", "min_count": 2, "max_count": 4},
    2: {"name": "二阶推演", "question": "趋势发展下去，矛盾/机会/拐点在哪里？", "min_count": 2, "max_count": 4},
    3: {"name": "投资落点", "question": "这个推理对选股意味着什么？", "min_count": 2, "max_count": 3},
}


class HypothesizeAgent:
    """因果推理假设形成 Agent (v2)"""

    def __init__(self, data_dir: Path = None, rules_dir: Path = None):
        self.data_dir = data_dir or settings.PROSPERITY_DATA_DIR
        self.rules_dir = rules_dir or settings.PROSPERITY_RULES_DIR

    def form_hypotheses(
        self,
        industry_name: str,
        session_id: int,
        search_result: dict,
        history=None  # Optional[IndustryHistory]
    ) -> list[dict]:
        """
        从搜索结果中构建因果推理链。

        Returns:
            [{id, title, chain_level, derives_from, statement, reasoning,
              sources, confidence, time_horizon, investment_implication,
              key_indicators, verification_needed, tier, wiki_path}, ...]
        """
        logger.info(f"HypothesizeAgent v2: forming deduction chain for {industry_name}")

        # 构建 LLM prompt
        prompt = self._build_prompt(industry_name, search_result, history)

        # 调用 LLM
        llm_output = self._call_llm(prompt)

        # 解析 LLM 输出
        hypotheses = self._parse_hypotheses(llm_output)

        # 映射 chain_level → tier（向后兼容）
        for h in hypotheses:
            if "tier" not in h or not h.get("tier"):
                level = h.get("chain_level", 0)
                tier_map = {0: "core", 1: "sub", 2: "sub", 3: "data"}
                h["tier"] = tier_map.get(level, "core")

        # 写入 wiki + 数据库
        wiki_dir = self.data_dir / "wiki" / "hypotheses"
        wiki_dir.mkdir(parents=True, exist_ok=True)

        db = get_db_session()
        try:
            for h in hypotheses:
                # 写入 Markdown 页面
                md_content = self._render_hypothesis_page(industry_name, h, hypotheses)
                filename = f"{industry_name}-{self._safe_filename(h['title'])}.md"
                file_path = wiki_dir / filename
                file_path.write_text(md_content, encoding="utf-8")

                h["wiki_path"] = str(file_path.relative_to(self.data_dir))

                # 写入数据库（含新字段）
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
                    wiki_path=h["wiki_path"],
                )
                db.add(db_h)
            db.commit()
        finally:
            db.close()

        # 更新索引
        wiki_full = self.data_dir / "wiki"
        update_index(wiki_full)
        append_log(wiki_full, f"HypothesizeAgent v2: {len(hypotheses)} hypotheses (deduction chain) for {industry_name}")

        logger.info(f"HypothesizeAgent v2: {len(hypotheses)} hypotheses formed")
        return hypotheses

    def _build_prompt(self, industry_name: str, search_result: dict, history=None) -> str:
        """构建 LLM prompt — 4 层因果推理链 + 历史锚定

        历史锚定：从 IndustryHistory 取上次评级记录和报告摘要，
        确保 LLM 推理有延续性，避免每次从零开始导致方向漂移（Bug 4/5）。
        """
        # 构建搜索结果文本（新旧分流）
        results_text = ""
        new_count = search_result.get("new_count", 0)
        old_count = search_result.get("old_count", 0)
        all_results = search_result.get("results", [])

        if new_count > 0 or old_count > 0:
            # 已分流的场景
            new_results = all_results[:new_count]
            old_results = all_results[new_count:new_count + old_count]

            if new_results:
                results_text += "## 🆕 本期新情报\n\n"
                for i, r in enumerate(new_results[:20]):
                    results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')[:300]}\n来源: {r.get('url', '')}\n\n"

            if old_results:
                results_text += "## 📚 上次已覆盖（摘要）\n\n"
                for i, r in enumerate(old_results[:10]):
                    results_text += f"[旧#{i+1}] {r.get('title', '')}\n{r.get('content', '')[:100]}\n\n"
        else:
            # 首次研究或无新旧分流
            for i, r in enumerate(all_results[:20]):
                results_text += f"[{i+1}] {r.get('title', '')}\n{r.get('content', '')[:300]}\n来源: {r.get('url', '')}\n\n"

        # 构建历史锚定上下文（从 history 对象）
        history_text = self._build_history_context(history)

        return f"""你是一位行业研究分析师。请基于以下情报，构建「{industry_name}」的因果推理链。

## 行业历史背景（锚定参考）
{history_text if history_text else "（无历史记录，首次研究）"}

## 情报搜索结果
{results_text}

## 核心要求：推演而非罗列

每条假设必须有"上游 premise → 本环节结论 → 下游 consequence"的逻辑箭头。
目标是形成一个可操作的推理链，让投资决策者能理解：
📊 现在发生了什么 → 🔮 接下来会发生什么 → ⚠️ 哪里有机会或风险 → 🎯 应该关注哪些公司

严禁：孤立罗列事实、堆砌数据而不建立因果关系、L3 只说"利好XX行业"而不说具体特征。

## 输出结构：4 层推理链

### Level 0 — 现状诊断（2-3条）
"当前行业的客观状态是什么？"
要求：
- 每条引用至少 3 个情报信源
- 陈述可证实或证伪
- 方向明确（增速/方向/程度）
- id 格式: H0-1, H0-2, H0-3
- derives_from 为空数组 []

示例：
「存储芯片是本轮半导体景气周期的领涨引擎，受益于 AI 数据需求及涨价，HBM 出货量同比+300%」

### Level 1 — 一阶推演（2-4条）
"如果 Level 0 成立，接下来必然发生什么产业趋势？"
要求：
- 必须指明由哪条 L0 假设推导而来（derives_from 引用 L0 的 id）
- 逻辑链完整：因为 [引用 L0 结论] → 所以 [产业会发生什么变化] → 导致 [新状态]
- 必须引用至少 2 个信源
- id 格式: H1-1, H1-2, ...

示例（假设 H0-1 说存储景气）：
「存储厂商营收利润双增 → 多家宣布扩产计划 → 2026H2-2027H1 产能集中释放」
derives_from: ["H0-1"]

### Level 2 — 二阶推演（2-4条）
"一阶趋势发展下去，矛盾/机会/拐点在哪里？"
要求：
- 必须指明由哪条 L1 假设推导而来
- 包含：时间窗口估计、风险/收益判断、关键观察指标
- 必须引用至少 1 个信源 + 逻辑推理
- id 格式: H2-1, H2-2, ...

示例（假设 H1-1 说存储扩产）：
「产能集中释放 → 2027Q1 供需可能逆转 → 价格下行压力 → 关注量价拐点，跟踪指标：DRAM 合约价月度变化」
derives_from: ["H1-1"]
time_horizon: "1年"

### Level 3 — 投资落点（2-3条）
"这个推理链对选股意味着什么？必须给出可操作的选股方向。"
要求：
- 必须指明由哪条 L2 假设推导而来
- 必须填写 investment_implication，包含：受益环节、典型标的特征、排除特征
- 必须填写 key_indicators：可以跟踪的具体指标
- id 格式: H3-1, H3-2, ...

示例（假设 H2-1 说存储可能要拐点）：
「当前关注存储弹性标的（价/产能比低、HBM 绑定的公司），2027Q1 前需评估是否转防御」
investment_implication: "关注方向：HBM 绑定的存储设计/封测，典型特征：HBM 相关营收占比 >20%、毛利率 >40%；排除：纯通用 DRAM 代工"
key_indicators: ["DRAM 合约价月度环比", "HBM 产能利用率", "主要厂商 Capex 指引"]
time_horizon: "当前-2027Q1"

## 输出 JSON 格式（只输出 JSON，不要其他内容）

```json
[
  {{
    "id": "H0-1",
    "title": "简短标题（10字以内）",
    "chain_level": 0,
    "derives_from": [],
    "statement": "假设陈述（一句话，可证实/证伪）",
    "reasoning": "推理链：因为 [上游结论] → 所以 [本项判断] → 导致 [下游影响]",
    "confidence": "high",
    "sources": ["[1]", "[5]", "[9]"],
    "time_horizon": "当前",
    "investment_implication": null,
    "key_indicators": ["全球半导体月度销售额", "WSTS 预测数据"],
    "verification_needed": ["待验证数据点1"]
  }},
  {{
    "id": "H3-1",
    "title": "存储弹性标的窗口期",
    "chain_level": 3,
    "derives_from": ["H2-1"],
    "statement": "存储产能释放前，关注 HBM 绑定标的的业绩弹性",
    "reasoning": "因为 H2-1 判断 2027Q1 可能出现供需逆转 → 所以当前窗口仍有利可图但需选对结构 → 导致应聚焦 HBM 相关而非通用 DRAM",
    "confidence": "medium",
    "sources": ["[2]", "[8]"],
    "time_horizon": "当前-2027Q1",
    "investment_implication": "关注方向：HBM 绑定的存储设计/封测公司；典型特征：HBM 相关营收占比 >20%、毛利率 >40%；排除：纯通用 DRAM 代工、NOR Flash",
    "key_indicators": ["DRAM 合约价月度环比", "HBM 产能利用率", "主要厂商 Capex 指引"],
    "verification_needed": ["HBM 相关 A 股公司名单", "各公司 HBM 营收占比数据"]
  }}
]
```

关键规则：
1. id 必须严格按 H{{层级}}-{{序号}} 格式，不可重复
2. derives_from 必须引用上层的 id（L0 为空数组，L1 引用 L0，L2 引用 L1，L3 引用 L2）
3. L3 的 investment_implication 必须具体到可筛选标的的程度
4. L2 的 time_horizon 必须给出时间窗口估计
5. confidence 用 high/medium/low，基于信源丰度和确定性"""

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

    def _call_llm(self, prompt: str) -> str:
        """调用 DeepSeek LLM（temperature=0 确保输出确定性）"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        if not api_key:
            logger.warning("LLM_API_KEY not configured, returning empty hypotheses")
            return "[]"

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
                    "max_tokens": 8192,
                },
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.error(f"LLM returned {resp.status_code}: {resp.text[:300]}")
                return "[]"
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return "[]"

    def _parse_hypotheses(self, llm_output: str) -> list[dict]:
        """解析 LLM JSON 输出"""
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", llm_output)
        json_str = match.group(1) if match else llm_output
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON output")
            return []

    def _render_hypothesis_page(self, industry_name: str, h: dict, all_hypotheses: list[dict] = None) -> str:
        """渲染假设 Markdown 页面（v2 — 含推理链可视化）"""
        h_id = h.get("id", "?")
        chain_level = h.get("chain_level", 0)
        level_name = CHAIN_LEVELS.get(chain_level, {}).get("name", "未知层级")
        sources = "、".join(h.get("sources", []))
        verify_items = "\n".join(f"- {v}" for v in h.get("verification_needed", []))
        derives_from = h.get("derives_from", [])
        time_horizon = h.get("time_horizon", "")
        investment_implication = h.get("investment_implication", "")
        key_indicators = h.get("key_indicators", [])

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

        # 关键跟踪指标
        indicators_section = ""
        if key_indicators:
            indicators_section = "\n**关键跟踪指标**:\n" + "\n".join(f"- {k}" for k in key_indicators) + "\n"

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

        return f"""# {level_icon} [{level_name}] {h.get('title', '')}

> 行业: {industry_name} | ID: `{h_id}` | 层级: L{chain_level} | 状态: 🔍 UNVERIFIED
{upstream_section}{downstream_section}
## 假设

**陈述**: {h.get('statement', '')}

**推理链**: {h.get('reasoning', '')}
{horizon_section}
**支撑信源**: {sources}

**初始置信度**: {h.get('confidence', 'medium')}

**需要验证的数据点**:
{verify_items}
{indicators_section}{implication_section}
## 验证

（待验证）

## 反推

（待修正）

## 跟踪

（待确认）
"""

    def _safe_filename(self, title: str) -> str:
        """将标题转为安全的文件名"""
        return re.sub(r"[^\w\-]", "_", title)[:50]
