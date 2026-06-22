"""WebSearch Extractor — 从 websearch 原始文本预提取结构化事实 (P1)

v1.0.0: 使用规则匹配 + 轻量正则, 从 websearch snippets 中预提取
         收入结构、市占率、管理层事实、行业数据等结构化 key-value,
         供 DataSummarizer Layer 2 消费。

设计原则:
  - 不做 LLM 调用 (避免成本/延迟), 纯规则引擎
  - 提取失败时优雅降级 (返回空/标记 missing)
  - 可在后续升级为小模型提取
"""

import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WebSearchExtractor:
    """从 websearch 原始文本中预提取结构化事实

    输入: websearch.yaml 的完整 dict
    输出: {
        "revenue_segments": [...],
        "market_share": {...},
        "management_facts": [...],
        "industry_data": {...},
        "talent_structure": {...},
        "national_policy": [...],
        "supply_chain": {...},
    }
    """

    def extract(self, websearch_data: dict, company_name: str = "") -> dict:
        """主入口: 从 websearch 全量数据提取结构事实"""
        result: dict[str, Any] = {
            "revenue_segments": [],
            "market_share": {},
            "management_facts": [],
            "industry_data": {},
            "talent_structure": {},
            "national_policy": [],
            "supply_chain": {},
            "corporate_events": [],
        }
        company = company_name or ""

        # 遍历所有搜索模块
        all_snippets = self._flatten_snippets(websearch_data)

        # 1. 收入结构提取
        result["revenue_segments"] = self._extract_revenue_segments(all_snippets)

        # 2. 市占率提取
        result["market_share"] = self._extract_market_share(all_snippets)

        # 3. 管理层关键事实
        result["management_facts"] = self._extract_management_facts(all_snippets)

        # 4. 行业数据
        result["industry_data"] = self._extract_industry_data(all_snippets)

        # 5. 人才结构
        result["talent_structure"] = self._extract_talent_structure(all_snippets)

        # 6. 国家政策
        result["national_policy"] = self._extract_national_policy(all_snippets)

        # 7. 供应链信息
        result["supply_chain"] = self._extract_supply_chain(all_snippets)

        # 8. 重大事件与资本运作 ★v0.7.3
        result["corporate_events"] = self._extract_corporate_events(all_snippets)

        return result

    # ── 工具 ──

    def _flatten_snippets(self, websearch: dict) -> list[dict]:
        """将 websearch 各模块的 snippets 展平为统一列表"""
        flat = []
        for key in ("q_websearch", "r1_websearch", "r2_websearch",
                     "r3_websearch", "v_websearch"):
            module = websearch.get(key, {})
            for i, s in enumerate(module.get("snippets", [])):
                s_copy = dict(s)
                s_copy["_module"] = key
                s_copy["_index"] = i
                flat.append(s_copy)
        return flat

    # ── 提取器 ──

    def _extract_revenue_segments(self, snippets: list[dict]) -> list[dict]:
        """提取业务板块收入数据

        Pattern: "PBG收入约270亿同比下滑5%" or "创新业务272亿增长21.2%"
        """
        results = []
        pattern = re.compile(
            r'(?P<segment>[A-Za-z\u4e00-\u9fff\u3000-\u303f]+?)(?:业务|收入|板块)?'
            r'.*?(?:营收|收入|约)?\s*(?P<amount>\d+(?:\.\d+)?)\s*亿'
            r'.*?(?:同比)?(?P<direction>下滑|增长|下降|增加|减少)?\s*(?P<change>\d+(?:\.\d+)?)\s*%?',
        )

        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            for m in pattern.finditer(content):
                seg = m.group("segment").strip()
                amt = m.group("amount")
                direction = m.group("direction") or ""
                change = m.group("change") or ""
                if len(seg) >= 2 and len(seg) <= 20:  # 合理长度
                    results.append({
                        "segment": seg,
                        "revenue_billion": float(amt),
                        "yoy_change_pct": -float(change) if "下滑" in direction or "下降" in direction or "减少" in direction else float(change),
                        "source_snippet": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    })
        return results

    def _extract_market_share(self, snippets: list[dict]) -> dict:
        """提取市占率

        Pattern: "市占率37.9%, 第二名大华12%" or "全球第一, 市场份额25.3%"
        """
        result: dict[str, Any] = {}
        share_pattern = re.compile(
            r'(?:市占率|市场份额|占有率).*?(?P<pct>\d+(?:\.\d+)?)\s*%',
        )
        rank_pattern = re.compile(
            r'(?:全球|国内|行业).*?第[一二三123].*?(?:名|位)',
        )
        rival_pattern = re.compile(
            r'第[二两三].*?(?:名|位)\s*(?P<rival>[\u4e00-\u9fff]+?)\s*(?P<rpct>\d+(?:\.\d+)?)\s*%',
        )

        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            sm = share_pattern.search(content)
            if sm and "share" not in result:
                result["share_pct"] = float(sm.group("pct"))
            rm = rank_pattern.search(content)
            if rm and "rank" not in result:
                result["rank"] = rm.group()
            riv = rival_pattern.search(content)
            if riv and "rival_name" not in result:
                result["rival_name"] = riv.group("rival")
                result["rival_share_pct"] = float(riv.group("rpct"))
        return result

    def _extract_management_facts(self, snippets: list[dict]) -> list[dict]:
        """提取管理层关键事实"""
        facts = []
        keywords_map = {
            "ceo_change": r'(董事长|总经理|CEO|总裁).*?(变更|更换|辞职|离职|上任|接任)',
            "equity_incentive": r'股权激励.*?(\d+)[人个].*?(\d+(?:\.\d+)?)[%％]',
            "share_reduction": r'(减持|套现).*?(\d+(?:\.\d+)?)\s*亿',
            "negative_event": r'(违规|处罚|调查|立案|警示函|问询函)',
        }
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            for fact_type, pattern in keywords_map.items():
                m = re.search(pattern, content)
                if m:
                    facts.append({
                        "type": fact_type,
                        "text": m.group()[:100],
                        "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    })
        return facts[:10]

    def _extract_industry_data(self, snippets: list[dict]) -> dict:
        """提取行业规模/增速/渗透率"""
        result: dict[str, Any] = {}
        size_pattern = re.compile(r'市场(?:规模|总量).*?(\d+(?:\.\d+)?)\s*亿')
        growth_pattern = re.compile(r'(?:行业|市场).*?(?:增速|增长|CAGR).*?(\d+(?:\.\d+)?)\s*%')
        penetration_pattern = re.compile(r'(?:渗透率).*?(\d+(?:\.\d+)?)\s*%')

        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            if "market_size" not in result:
                m = size_pattern.search(content)
                if m: result["market_size_billion"] = float(m.group(1))
            if "growth_rate" not in result:
                m = growth_pattern.search(content)
                if m: result["growth_rate_pct"] = float(m.group(1))
            if "penetration" not in result:
                m = penetration_pattern.search(content)
                if m: result["penetration_pct"] = float(m.group(1))
        return result

    def _extract_talent_structure(self, snippets: list[dict]) -> dict:
        """提取人才结构"""
        result: dict[str, Any] = {}
        employee_pattern = re.compile(r'(?:员工|总人数).*?(\d+(?:\.\d+)?)\s*[万人]')
        rd_pattern = re.compile(r'研发人员.*?(\d+(?:\.\d+)?)\s*[人个].*?占比.*?(\d+(?:\.\d+)?)\s*%')
        per_capita_pattern = re.compile(r'人均创[收利].*?(\d+(?:\.\d+)?)\s*万元?')

        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            if "employee_count" not in result:
                m = employee_pattern.search(content)
                if m: result["employee_count"] = m.group(1)
            if "rd_personnel" not in result:
                m = rd_pattern.search(content)
                if m: 
                    result["rd_personnel"] = m.group(1)
                    result["rd_ratio_pct"] = float(m.group(2))
            if "revenue_per_capita" not in result:
                m = per_capita_pattern.search(content)
                if m: result["revenue_per_capita_wan"] = float(m.group(1))
        return result

    def _extract_national_policy(self, snippets: list[dict]) -> list[dict]:
        """提取国家政策引用"""
        policies = []
        policy_keywords = [
            r'十四五', r'十五五', r'国[家发]改委', r'工信部', r'国务院',
            r'自主可控', r'国产替代', r'信创', r'新质生产力', r'专精特新',
            r'东数西算', r'碳中和', r'双循环', r'一带一路', r'中国制造2025',
        ]
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            for kw in policy_keywords:
                if re.search(kw, content):
                    policies.append({
                        "keyword": kw,
                        "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                        "snippet_preview": content[:200],
                    })
                    break
        return policies[:5]

    def _extract_supply_chain(self, snippets: list[dict]) -> dict:
        """提取供应链/上下游信息"""
        result: dict[str, Any] = {}
        upstream_pattern = re.compile(r'(?:供应商|上游).*?前[5五]大.*?(\d+(?:\.\d+)?)\s*%')
        downstream_pattern = re.compile(r'(?:客户|下游).*?前[5五]大.*?(\d+(?:\.\d+)?)\s*%')
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            if "supplier_concentration" not in result:
                m = upstream_pattern.search(content)
                if m: result["supplier_concentration_pct"] = float(m.group(1))
            if "customer_concentration" not in result:
                m = downstream_pattern.search(content)
                if m: result["customer_concentration_pct"] = float(m.group(1))
        return result

    # ── v0.7.3: 重大事件与资本运作提取 ──

    def _extract_corporate_events(self, snippets: list[dict]) -> list[dict]:
        """提取重大资本运作事件：定增/并购/重组/重大合同/诉讼

        输出 schema:
        {
            "type": "placement|merger|restructure|major_contract|litigation",
            "date": "2026-03",         # best-effort, 可能为空
            "amount_billion": 83.5,    # 涉及金额(亿元), 可能为 null
            "target": "新潮传媒",       # 并购标的/交易对手
            "description": "原文片段",
            "source": "q_websearch[3]",
            "confidence": "HIGH|LOW"   # 金额+标的都提取到→HIGH
        }
        """
        events = []

        # ── 1. 定增 (placement) ──
        placement_pattern = re.compile(
            r'(?:定增|非公开发行|发行股份|募集资金|配股)'
            r'.*?(\d+(?:\.\d+)?)\s*(?:亿|元|万元)',
        )
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            m = placement_pattern.search(content)
            if m:
                amt_raw = float(m.group(1))
                # 判断单位: 万元→亿元, 亿元直接使用
                if "万元" in m.group():
                    amt = amt_raw / 1e4
                elif "元" in m.group() and "亿元" not in m.group() and "百亿" not in m.group():
                    amt = amt_raw / 1e8
                else:
                    amt = amt_raw  # 已为亿元或上下文足够
                events.append({
                    "type": "placement",
                    "date": self._extract_date(content),
                    "amount_billion": round(amt, 2) if amt < 10000 else None,  # 不合理大数→None
                    "target": None,
                    "description": m.group()[:120],
                    "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    "confidence": "HIGH" if (amt and amt < 10000) else "LOW",
                })

        # ── 2. 并购 (merger) ──
        merger_pattern = re.compile(
            r'(?:收购|并购|取得|要约收购|合并|控股收购)\s*'
            r'(?P<target>[\u4e00-\u9fffA-Za-z]{2,20}'
            r'(?:公司|集团|科技|传媒|医疗|医药|银行|保险|证券|基金|文化)?)'
            r'.*?(\d+(?:\.\d+)?)\s*(?:亿|元|万元)?',
        )
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            m = merger_pattern.search(content)
            if m:
                target = m.group("target").strip()
                events.append({
                    "type": "merger",
                    "date": self._extract_date(content),
                    "amount_billion": self._parse_amount(m.group(0)),
                    "target": target if len(target) >= 2 else None,
                    "description": m.group()[:120],
                    "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    "confidence": "HIGH" if target and len(target) >= 2 else "LOW",
                })

        # ── 3. 重组 (restructure) ──
        restructure_pattern = re.compile(
            r'(?:重大资产重组|资产注入|资产置换|借壳上市|整体上市|分拆上市)',
        )
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            m = restructure_pattern.search(content)
            if m:
                events.append({
                    "type": "restructure",
                    "date": self._extract_date(content),
                    "amount_billion": None,
                    "target": None,
                    "description": m.group()[:120],
                    "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    "confidence": "LOW",
                })

        # ── 4. 重大合同 (major_contract) ──
        contract_pattern = re.compile(
            r'(?:中标|签约|签署|签下).*?(?:合同|协议|订单)'
            r'.*?(\d+(?:\.\d+)?)\s*(?:亿|元|万)',
        )
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            m = contract_pattern.search(content)
            if m:
                events.append({
                    "type": "major_contract",
                    "date": self._extract_date(content),
                    "amount_billion": self._parse_amount(m.group(0)),
                    "target": None,
                    "description": m.group()[:120],
                    "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    "confidence": "HIGH" if m.group(1) else "LOW",
                })

        # ── 5. 重大诉讼 (litigation) ──
        litigation_pattern = re.compile(
            r'(?:诉讼|仲裁|起诉|被诉|应诉|判决).*?'
            r'.*?(\d+(?:\.\d+)?)\s*(?:亿|元|万元)?',
        )
        for s in snippets:
            content = s.get("content", "") + s.get("title", "")
            m = litigation_pattern.search(content)
            if m:
                events.append({
                    "type": "litigation",
                    "date": self._extract_date(content),
                    "amount_billion": self._parse_amount(m.group(0)),
                    "target": None,
                    "description": m.group()[:120],
                    "source": f"{s.get('_module', '')}[{s.get('_index', '')}]",
                    "confidence": "LOW",
                })

        # 去重：按 type + description 前 30 字符
        seen = set()
        deduped = []
        for e in events:
            key = (e["type"], e["description"][:30])
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        return deduped[:10]  # 最多 10 条

    @staticmethod
    def _extract_date(text: str) -> Optional[str]:
        """从文本中提取日期 (YYYY-MM 或 YYYY)"""
        # YYYY年MM月
        m = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月', text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        # YYYY-MM
        m = re.search(r'(\d{4})-(\d{1,2})', text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}"
        # 仅年份
        m = re.search(r'(\d{4})年', text)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _parse_amount(text: str) -> Optional[float]:
        """从文本中解析金额（亿元）"""
        m = re.search(r'(\d+(?:\.\d+)?)\s*(?:亿|元|万)', text)
        if not m:
            return None
        amt = float(m.group(1))
        if "亿" in m.group():
            return round(amt, 2) if amt < 10000 else None
        elif "万" in m.group():
            return round(amt / 1e4, 4)  # 万元→亿元
        else:
            return round(amt / 1e8, 6)  # 元→亿元

    def to_yaml_string(self, websearch_data: dict, company_name: str = "") -> str:
        """输出为 YAML 字符串"""
        import yaml
        return yaml.dump(
            self.extract(websearch_data, company_name),
            allow_unicode=True, default_flow_style=False, sort_keys=False,
        )
