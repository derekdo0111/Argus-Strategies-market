"""QRV Agent — Quality / Resilience / Valuation 综合分析

v0.5.0: DataSummarizer v2 (A1 20+字段 + A7生意属性 + Layer3 充分性评估)
          + WebSearchExtractor 预提取 + industry_profiles 行业适配
v0.4.0: 引入 DataSummarizer 预处理 + 去截断 + 完整CQ/PR传递
v0.3.0: 取代原 Step 8 (基本面门) + Step 9 (估值门)
单次 LLM 调用，读取 qrv_input.yaml，输出定量+定性分析报告。

调用入口：
- 命令行: python -m app.strategies.turtle.qrv_agent --ts_code 600900.SH
- 程序中: QRVAgent.analyze(ts_code)
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import yaml

# 确保 backend 可 import
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from .data_summarizer import DataSummarizer
from .utils import find_stock_dir

logger = logging.getLogger(__name__)


class QRVAgent:
    """QRV 综合分析 Agent"""

    def __init__(
        self,
        cache_dir: Path | None = None,
        rule_version: str = "v2",
        llm_model: str | None = None,
    ):
        self.cache_dir = cache_dir or settings.TURTLE_CACHE_DIR
        self.rule_version = rule_version
        self.llm_model = llm_model or getattr(settings, "LLM_MODEL", "deepseek-v4-flash")

    def analyze(self, ts_code: str) -> dict:
        """[DEPRECATED] 同步入口: 分析单只股票。请使用 await analyze_async() 替代，避免在已有事件循环时崩溃。"""
        import warnings
        warnings.warn("QRVAgent.analyze() is deprecated, use await analyze_async() instead", DeprecationWarning, stacklevel=2)
        return asyncio.run(self.analyze_async(ts_code))

    async def analyze_async(self, ts_code: str) -> dict:
        """异步分析单只股票"""
        print(f"\n{'='*60}")
        print(f"[QRV Agent] {ts_code}")
        print(f"{'='*60}\n")

        # 1. 加载 qrv_input.yaml
        stock_dir = find_stock_dir(self.cache_dir, ts_code)
        if stock_dir is None:
            return {"error": f"找不到 {ts_code} 的缓存目录"}

        qrv_path = stock_dir / "qrv_input.yaml"
        if not qrv_path.exists():
            return {"error": f"qrv_input.yaml 不存在，请先运行 Step 6-7"}

        with open(qrv_path, "r", encoding="utf-8") as f:
            qrv_input = yaml.safe_load(f)

        company_name = qrv_input.get("company_profile", {}).get("name", ts_code)
        print(f"[Info] Company: {company_name} ({ts_code})")

        # 2. 检查 WebSearch 数据
        ws = qrv_input.get("websearch_results", {})
        ws_sections = len([k for k in ws if isinstance(ws[k], dict) and ws[k].get("snippets")])
        print(f"[WebSearch] {ws_sections} modules have results")

        # 3. 检查门禁状态
        cq = qrv_input.get("cq_results", {})
        pr = qrv_input.get("pr_results", {})
        cq_passed = cq.get("overall_passed", False) if isinstance(cq, dict) else False
        pr_passed = pr.get("pr_result", {}).get("passed", False) if isinstance(pr, dict) else False
        print(f"[Gate] CQ: {'PASS' if cq_passed else 'FAIL'} | PR: {'PASS' if pr_passed else 'FAIL'}")

        # 4. 构建 LLM prompt
        prompt = self._build_prompt(company_name, ts_code, qrv_input)

        # 5. 调用 LLM
        print(f"[LLM] Calling {self.llm_model}...")
        llm_result = await self._call_llm(prompt)
        tokens = llm_result.get("tokens", 0)
        print(f"[LLM] Response: {tokens} tokens")

        # 6. 写入报告
        md_path = stock_dir / "qrv_analysis.md"
        json_path = stock_dir / "qrv_analysis.json"

        markdown_content = llm_result.get("markdown", "")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        # v0.7.11: 从 LLM markdown 输出中提取结构化打分
        scores = self._parse_scores(markdown_content)
        if scores:
            print(f"[Scores] Extracted: total={scores.get('total', 'N/A')}, "
                  f"Q={scores.get('Q_weighted', 'N/A')}, "
                  f"R={scores.get('R_weighted', 'N/A')}, "
                  f"V={scores.get('V_weighted', 'N/A')}")
        else:
            print(f"[Scores] Warning: could not extract scores from LLM output")

        json_report = {
            "meta": {
                "ts_code": ts_code,
                "name": company_name,
                "analysis_date": time.strftime("%Y-%m-%d"),
                "rule_version": self.rule_version,
            },
            "gate_status": {
                "cq_passed": cq_passed,
                "pr_passed": pr_passed,
            },
            "websearch_coverage": ws_sections,
            "llm_raw_response": llm_result.get("raw", ""),
            "tokens_used": tokens,
            "truncated": llm_result.get("truncated", False),  # v0.5.2
            "scores": scores,  # v0.7.11: 结构化评分
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_report, f, ensure_ascii=False, indent=2)

        print(f"\n[Report] Generated:")
        print(f"  Markdown: {md_path}")
        print(f"  JSON:     {json_path}\n")

        return {
            "ts_code": ts_code,
            "name": company_name,
            "qrv_analysis_md": str(md_path),
            "qrv_analysis_json": str(json_path),
            "tokens": tokens,
        }

    # ── 内部方法 ──

    def _build_prompt(self, company_name: str, ts_code: str, qrv_input: dict) -> str:
        """构建 LLM prompt

        v0.4.0: 引入 DataSummarizer 预提取关键数字表格，替换原始 YAML dump。
        不再截断数据，而是用结构化摘要 + 完整 websearch 传给 LLM。
        """
        # 从 turtle_qrv.yaml 加载模板
        rules_dir = settings.RULES_DIR / "v2"
        qrv_yaml = rules_dir / "turtle_qrv.yaml"
        template = ""
        if qrv_yaml.exists():
            with open(qrv_yaml, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            template = config.get("prompt_template", "")

        if not template:
            template = self._default_prompt()

        # === v0.4.0: 使用 DataSummarizer 构建结构化摘要 ===
        stock_dir = find_stock_dir(self.cache_dir, ts_code)
        if stock_dir:
            summarizer = DataSummarizer.from_stock_dir(stock_dir)
            data_summary = summarizer.build_summary()
        else:
            # 兜底：从 qrv_input 手动映射到 DataSummarizer 期望的格式
            raw_data = {
                "meta": qrv_input.get("company_profile", {}),
                "basic_info": qrv_input.get("company_profile", {}),
                "annual_financials": qrv_input.get("financial_data", {}).get("annual_financials", []),
            }
            div_rep = qrv_input.get("dividend_repurchase", {})
            raw_data["dividend_history"] = div_rep.get("dividend_history", [])
            raw_data["repurchase_history"] = div_rep.get("repurchase_history", [])

            computed_data = {
                "cash_quality": qrv_input.get("cq_results", {}),
                "penetration_return": qrv_input.get("pr_results", {}),
            }
            summarizer = DataSummarizer(
                raw_data=raw_data,
                computed_data=computed_data,
                websearch_data=qrv_input.get("websearch_results", {}),
            )
            data_summary = summarizer.build_summary()

        # === v0.5.0: WebSearchExtractor 预提取结构化事实 (Layer 2) ===
        from .websearch_extractor import WebSearchExtractor
        extractor = WebSearchExtractor()
        ws_data = qrv_input.get("websearch_results", {})
        extracted_facts = extractor.extract(ws_data, company_name)
        extracted_yaml = yaml.dump(
            extracted_facts, allow_unicode=True, default_flow_style=False, sort_keys=False,
        )

        data_summary_yaml = yaml.dump(
            data_summary, allow_unicode=True, default_flow_style=False, sort_keys=False
        )

        # === 只序列化 websearch（保持完整）+ data_summary + extracted_facts ===
        ws = qrv_input.get("websearch_results", {})
        ws_yaml = yaml.dump(ws, allow_unicode=True, default_flow_style=False)

        # 组合：摘要 + websearch预提取 + websearch完整数据 + 原始财务（截取最近7年做交叉验证）
        financials = qrv_input.get("financial_data", {}).get("annual_financials", [])
        if isinstance(financials, list) and len(financials) > 7:
            financials_recent = sorted(
                financials,
                key=lambda x: int(x.get("year", 0)),
                reverse=True,
            )[:7]
        else:
            financials_recent = financials

        financials_yaml = yaml.dump(
            {"recent_years": len(financials_recent), "annual_financials": financials_recent},
            allow_unicode=True,
            default_flow_style=False,
        )

        # 拼接最终数据包
        combined_data = (
            f"# data_summary (预处理提取，所有数字已核验，含data_sufficiency)\n{data_summary_yaml}\n\n"
            f"# extracted_facts (从websearch预提取的结构化事实 v0.5.0)\n{extracted_yaml}\n\n"
            f"# websearch_results (联网搜索完整结果)\n{ws_yaml}\n\n"
            f"# financial_data_recent (原始财务表，近{len(financials_recent)}年，用于交叉验证)\n{financials_yaml}"
        )

        total_chars = len(combined_data)
        print(f"[Data] Summary: {len(data_summary_yaml)} chars | Websearch: {len(ws_yaml)} chars | "
              f"Financials: {len(financials_yaml)} chars | Total: {total_chars} chars", flush=True)

        # 不再截断 —— 使用结构化摘要替代原始 YAML dump
        return template.format(
            company_name=company_name,
            ts_code=ts_code,
            qrv_input_yaml=combined_data,
        )

    @staticmethod
    def _parse_scores(markdown: str) -> dict | None:
        """从 LLM 输出的「综合打分卡」表格提取结构化分数

        匹配格式：
        | Q | Q1 生意本质+商业模式 | **8** | ... |
        | **综合** | — | **7.8/10** | — | — |

        Returns:
            dict with Q1_business, Q2_moat, Q3_growth, R1_environment,
            R2_management, R3_control, R4_events, V1_value_trap,
            V2_percentile, V3_stress_test, total, Q_weighted, R_weighted, V_weighted
            解析失败返回 None
        """
        import re

        # 模块名 → 输出 key 映射
        MODULE_MAP: dict[str, str] = {
            "Q1": "Q1_business",
            "Q2": "Q2_moat",
            "Q3": "Q3_growth",
            "R1": "R1_environment",
            "R2": "R2_management",
            "R3": "R3_control",
            "R4": "R4_events",
            "V1": "V1_value_trap",
            "V2": "V2_percentile",
            "V3": "V3_stress_test",
        }

        scores: dict[str, float] = {}

        # 逐行匹配：| Q/R/V | 模块名 ... | 分数 | ...
        line_pattern = re.compile(
            r'\|\s*(Q|R|V)\s*\|'
            r'\s*(Q\d|R\d|V\d)\s*[^|]*\|'
            r'\s*\**(\d+(?:\.\d+)?)\**\s*\|'
        )

        for line in markdown.splitlines():
            m = line_pattern.match(line.strip())
            if m:
                module_key = m.group(2)  # e.g. "Q1", "R4", "V3"
                try:
                    score = float(m.group(3))
                except ValueError:
                    continue
                if module_key in MODULE_MAP:
                    scores[MODULE_MAP[module_key]] = score

        # 提取综合总分：| **综合** | — | **7.8/10** | — | — |
        total_match = re.search(
            r'\*\*综合\*\*\s*\|[^|]*\|\s*\**(\d+(?:\.\d+)?)/10\**',
            markdown,
        )
        if total_match:
            scores["total"] = float(total_match.group(1))

        if not scores:
            return None

        # 计算 Q/R/V 加权均分
        for group, keys in [
            ("Q_weighted", ["Q1_business", "Q2_moat", "Q3_growth"]),
            ("R_weighted", ["R1_environment", "R2_management", "R3_control", "R4_events"]),
            ("V_weighted", ["V1_value_trap", "V2_percentile", "V3_stress_test"]),
        ]:
            group_scores = [scores[k] for k in keys if k in scores]
            if group_scores:
                scores[group] = round(sum(group_scores) / len(group_scores), 1)

        return scores

    @staticmethod
    def _default_prompt() -> str:
        return """你是一名资深CFA持证人，拥有15年A股价值投资经验。

## 核心铁律
1. **无数字不结论**：每个判断必须附具体数字
2. **无来源不引用**：每个数字标注出处
3. **数据缺失声明**：某维度无数据时写「数据缺失」
4. **表格优于段落**：能用表格的用表格
5. **先读 data_sufficiency**: 找data_summary末尾的data_sufficiency块, rich才深度分析, missing直接跳过

## 任务
基于提供的数据包，对【{company_name} {ts_code}】进行QRV三维综合分析。

## 数据包说明
- 板块A: data_summary (A1-A7 + data_sufficiency, 已核验)
- 板块A+: extracted_facts (从websearch预提取的结构化事实 v0.5.0)
- 板块B: websearch_results (联网搜索完整结果)
- 板块C: financial_data_recent (原始财务表，交叉验证用)

## 分析框架 (v3: 10维度)
### Q - 质量: Q1生意本质+商业模式 + Q2护城河+可攻破性 + Q3增长引擎
### R - 韧性: R1外部环境+国家战略 + R2管理层+人才结构 + R3控股结构
### V - 估值: V1价值陷阱 + V2历史分位 + V3压力测试

## 输出
每个模块强制输出指定表格，最终整体研判（打分卡 + 优势Top3 + 风险Top3 + 估值区间建议）

---
数据包：
{qrv_input_yaml}
"""

    async def _call_llm(self, prompt: str) -> dict:
        """调用 LLM API"""
        api_key = getattr(settings, "LLM_API_KEY", "")
        api_base = getattr(settings, "LLM_API_BASE", "https://api.deepseek.com/v1")
        max_tokens = getattr(settings, "LLM_MAX_TOKENS", 16384)
        temperature = getattr(settings, "LLM_TEMPERATURE", 0.2)

        if not api_key:
            return {"markdown": "# 占位报告\n\n[WARN] LLM_API_KEY 未配置", "raw": "", "tokens": 0, "truncated": False}

        for attempt in range(3):
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{api_base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.llm_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": max_tokens,
                            "temperature": temperature,
                        },
                        timeout=aiohttp.ClientTimeout(total=300),  # v0.5.2: 120→300s 大报告需要更长时间
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            content = data["choices"][0]["message"]["content"]
                            usage = data.get("usage", {})
                            finish_reason = data["choices"][0].get("finish_reason", "")

                            # v0.5.2: 截断检测 — finish_reason=="length" 表示 max_tokens 不够
                            if finish_reason == "length":
                                logger.warning(
                                    f"LLM输出被截断 (finish_reason=length, "
                                    f"output_tokens={usage.get('completion_tokens', 0)}, "
                                    f"max_tokens={max_tokens})"
                                )
                                print(f"  [WARN] LLM输出被截断! 建议增大 LLM_MAX_TOKENS (当前={max_tokens})", flush=True)

                            return {
                                "markdown": content,
                                "raw": json.dumps(data, ensure_ascii=False),
                                "tokens": usage.get("total_tokens", 0),
                                "truncated": finish_reason == "length",  # v0.5.2
                            }
                        else:
                            text = await resp.text()
                            print(f"  [WARN] LLM API error ({resp.status}): {text[:200]}")
                            if attempt < 2:
                                await asyncio.sleep(5)
            except Exception as e:
                print(f"  [WARN] LLM exception (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    await asyncio.sleep(5)

        return {"markdown": "# QRV 分析报告\n\n> [ERROR] LLM调用失败", "raw": "", "tokens": 0, "truncated": False}


# ====================================================================
# CLI 入口
# ====================================================================

async def main():
    parser = argparse.ArgumentParser(description="QRV Agent — 单股综合分析")
    parser.add_argument("--ts_code", required=True, help="股票代码，如 600900.SH")
    parser.add_argument("--cache-dir", help="缓存目录（默认 data/stock_cache）")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir) if args.cache_dir else settings.TURTLE_CACHE_DIR
    agent = QRVAgent(cache_dir=cache_dir)
    result = await agent.analyze_async(args.ts_code)

    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print("[Done] Analysis complete")


if __name__ == "__main__":
    asyncio.run(main())
