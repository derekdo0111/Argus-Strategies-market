"""Data Summarizer — QRV 预处理引擎

v2.0.0: A1 从 9 字段扩展到 20+ 字段，新增 Layer3 数据充分性评估，
         新增 A7 生意属性硬算 (收款方式/轻资产/现金转化周期)，
         支持按行业动态加载指标 profile (P2)
v1.0.0: 初始版本，生成 6 个子摘要 (A1-A6)
"""

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.config import settings

logger = logging.getLogger(__name__)

# 行业配置文件默认路径
_INDUSTRY_PROFILES_PATH = settings.RULES_DIR / "v2" / "industry_profiles.yaml"


class DataSummarizer:
    """QRV 数据预处理器

    v2.0.0 升级:
    - A1 扩展至 20+ 字段 (EPS/FCF/CAPEX/商誉/固定资产比/应收周转/存货周转/在建比等)
    - 新增 A7 生意属性 (轻/重资产, 收款方式, 现金转化周期)
    - 新增 Layer 3 数据充分性评估 (告诉 LLM 哪些维度可深度分析/哪些跳过)
    - 按行业动态加载指标 profile (银行不关心产能, 制造业不关心不良率)

    输入：raw_data.yaml + computed.yaml + websearch.yaml
    输出：结构化摘要块 (A1-A7) + data_sufficiency
    """

    def __init__(self, raw_data: Optional[dict] = None,
                 computed_data: Optional[dict] = None,
                 websearch_data: Optional[dict] = None):
        self.raw = raw_data or {}
        self.computed = computed_data or {}
        self.websearch = websearch_data or {}
        # v2.0.0: 加载行业 profile
        self.industry = self._extract_industry()
        self.profile = self._load_industry_profile(self.industry)

    # ──────────────────────────────────────────────
    # 公开方法
    # ──────────────────────────────────────────────

    @classmethod
    def from_stock_dir(cls, stock_dir: Path) -> "DataSummarizer":
        """从股票缓存目录加载全部数据"""
        raw = cls._load_yaml(stock_dir / "raw_data.yaml")
        computed = cls._load_yaml(stock_dir / "computed.yaml")
        websearch = cls._load_yaml(stock_dir / "websearch.yaml")
        return cls(raw_data=raw, computed_data=computed, websearch_data=websearch)

    def build_summary(self) -> dict:
        """构建完整摘要，供 LLM prompt 使用

        v2.0.0: 新增 A7 生意属性 + data_sufficiency 充分性评估
        """
        summary = {
            "meta": self._build_meta(),
            "A1_core_financials": self._a1_core_financials(),
            "A2_revenue_structure": self._a2_revenue_structure(),
            "A3_dividend_repurchase": self._a3_dividend_repurchase(),
            "A4_cq_gate": self._a4_cq_gate(),
            "A5_pr_detail": self._a5_pr_detail(),
            "A6_valuation_snapshot": self._a6_valuation_snapshot(),
            "A7_business_profile": self._a7_business_profile(),
            "A8_valuation_percentile": self._a8_valuation_percentile(),
        }
        # v2.0.0: Layer 3 数据充分性评估
        summary["data_sufficiency"] = self._assess_data_sufficiency(summary)
        # v3.1.0: URL 证据链索引 (供报告末尾「参考来源」章节)
        summary["reference_index"] = self._build_reference_index()
        return summary

    def to_yaml_string(self) -> str:
        """输出为 YAML 字符串，注入到 LLM prompt"""
        return yaml.dump(
            self.build_summary(),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    # ──────────────────────────────────────────────
    # 子摘要方法
    # ──────────────────────────────────────────────

    def _build_meta(self) -> dict:
        """生成 meta 信息块"""
        basic = self.raw.get("basic_info", {})
        meta = self.raw.get("meta", {})
        return {
            "ts_code": basic.get("ts_code", meta.get("ts_code", "")),
            "name": basic.get("name", meta.get("name", "")),
            "industry": basic.get("industry", meta.get("industry", "")),
            "industry_profile": self.profile.get("name", self.industry) if self.profile else self.industry,
            "list_date": basic.get("list_date", ""),
            "generated_at": "",
        }

    def _extract_industry(self) -> str:
        """从 raw_data 提取行业分类"""
        basic = self.raw.get("basic_info", {})
        meta = self.raw.get("meta", {})
        return basic.get("industry", meta.get("industry", "未知"))

    def _load_industry_profile(self, industry: str) -> Optional[dict]:
        """从 industry_profiles.yaml 加载行业特殊规则 (P2)"""
        if not _INDUSTRY_PROFILES_PATH.exists():
            return None
        try:
            with open(_INDUSTRY_PROFILES_PATH, "r", encoding="utf-8") as f:
                profiles = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载行业配置文件失败: {e}")
            return None
        if not isinstance(profiles, dict):
            return None
        if industry in profiles:
            return profiles[industry]
        for key, prof in profiles.items():
            if key in industry or industry in key:
                return prof
        return None

    # ── A1: 核心财务指标 (v2.0.0: 9→20+ 字段) ──

    def _a1_core_financials(self) -> dict:
        """A1: 核心财务指标 5 年趋势 (v2.0.0 扩展版)

        从 raw_data.annual_financials 提取近 5 年核心财务指标，
        输出逐年数值表 + 趋势判断。

        扩展字段:
        - 利润表: revenue, net_profit, gross_margin, net_margin, roe,
                   eps, operating_profit, revenue_yoy, net_profit_yoy
        - 资产负债表: total_assets, total_liab, debt_ratio, current_ratio,
                       quick_ratio, receivables, inventory, goodwill,
                       fixed_assets, intangible_assets, total_equity
        - 现金流表: ocf, fcf, capex, depreciation
        - 派生: ocf_to_netprofit, fcf_to_netprofit, receivables_to_revenue,
                  receivables_turnover_days, inventory_turnover_days,
                  fixed_asset_ratio_pct, goodwill_to_equity_pct,
                  capex_to_depreciation
        """
        financials = self.raw.get("annual_financials", [])
        if not financials:
            return {"status": "no_data", "message": "无年度财务数据"}

        sorted_fin = sorted(
            financials, key=lambda x: int(x.get("year", 0)), reverse=True,
        )[:5]
        sorted_fin.reverse()

        rows = []
        for fy in sorted_fin:
            year = int(fy.get("year", 0))
            income = fy.get("income", {})
            bs = fy.get("balance_sheet", {})
            cf = fy.get("cashflow", {})

            # ── 原始值 ──
            revenue = self._sf(income.get("revenue"))
            net_profit = self._sf(income.get("net_profit"))
            gross_margin = self._sf(income.get("gross_margin"))
            net_margin = self._sf(income.get("net_margin"))
            roe = self._sf(income.get("roe"))
            eps = self._sf(income.get("eps"))
            op_profit = self._sf(income.get("operating_profit"))
            rev_yoy = self._sf(income.get("revenue_yoy"))
            np_yoy = self._sf(income.get("net_profit_yoy"))

            # v0.5.2: 费用端字段 (Tushare 原始字段名)
            sell_exp = self._sf(income.get("sell_exp"))
            admin_exp = self._sf(income.get("admin_exp"))
            rd_exp = self._sf(income.get("rd_exp"))
            total_profit = self._sf(income.get("total_profit"))
            operate_cost = self._sf(income.get("operate_cost"))
            fin_exp = self._sf(income.get("fin_exp"))

            ocf = self._sf(cf.get("operating_cf"))
            fcf = self._sf(cf.get("fcf"))
            capex = self._sf(cf.get("capex"))
            depr = self._sf(cf.get("depreciation")) or self._sf(cf.get("depr_amort"))

            total_assets = self._sf(bs.get("total_assets"))
            total_liab = self._sf(bs.get("total_liabilities"))
            total_equity = self._sf(bs.get("total_equity"))
            receivables = self._sf(bs.get("receivables"))
            inventory = self._sf(bs.get("inventory"))
            goodwill = self._sf(bs.get("goodwill"))
            fixed_assets = self._sf(bs.get("fixed_assets"))
            intangibles = self._sf(bs.get("intangible_assets"))
            cur_ratio = self._sf(bs.get("current_ratio"))
            quick_ratio = self._sf(bs.get("quick_ratio"))

            # ── 派生指标 ──
            ocf_np = round(ocf / net_profit, 3) if net_profit and ocf else None
            fcf_np = round(fcf / net_profit, 3) if net_profit and fcf else None
            debt_ratio = round(total_liab / total_assets * 100, 1) if total_assets and total_liab else None
            recv_ratio = round(receivables / revenue, 3) if revenue and receivables else None
            recv_days = round(receivables / revenue * 365, 0) if revenue and receivables else None
            inv_days = round(inventory / revenue * 365, 0) if revenue and inventory else None
            fixed_ratio = round(fixed_assets / total_assets * 100, 1) if total_assets and fixed_assets else None
            gw_equity = round(goodwill / total_equity * 100, 1) if total_equity and goodwill else None
            capex_depr = round(capex / depr, 2) if depr and capex else None

            rows.append({
                "year": year,
                # 利润表 — v0.5.3: 归一化后已是亿元，不再 ÷1e8
                "revenue_billion": round(revenue, 2) if revenue else None,
                "revenue_yoy_pct": round(rev_yoy, 1) if rev_yoy else None,
                "net_profit_billion": round(net_profit, 2) if net_profit else None,
                "net_profit_yoy_pct": round(np_yoy, 1) if np_yoy else None,
                "eps": round(eps, 3) if eps else None,
                "operating_profit_billion": round(op_profit, 2) if op_profit else None,
                # v0.5.2: gross_margin/roe/net_margin 在 raw_data 中已是百分比值 (e.g. 91.18),
                #         不再 ×100 避免二次放大
                "gross_margin_pct": round(gross_margin, 1) if gross_margin else None,
                "net_margin_pct": round(net_margin, 1) if net_margin else None,
                "roe_pct": round(roe, 1) if roe else None,
                # v0.5.2: 费用端 (亿元) — v0.5.3: 归一化后已是亿元
                "sell_exp_billion": round(sell_exp, 2) if sell_exp else None,
                "admin_exp_billion": round(admin_exp, 2) if admin_exp else None,
                "rd_exp_billion": round(rd_exp, 2) if rd_exp else None,
                "total_profit_billion": round(total_profit, 2) if total_profit else None,
                "operate_cost_billion": round(operate_cost, 2) if operate_cost else None,
                "fin_exp_billion": round(fin_exp, 2) if fin_exp else None,
                # v0.5.2: 费用率 (百分比)
                "sell_exp_to_revenue_pct": round(sell_exp / revenue * 100, 1) if revenue and sell_exp else None,
                "admin_exp_to_revenue_pct": round(admin_exp / revenue * 100, 1) if revenue and admin_exp else None,
                "rd_exp_to_revenue_pct": round(rd_exp / revenue * 100, 1) if revenue and rd_exp else None,
                # 现金流 — v0.5.3: 归一化后已是亿元
                "ocf_billion": round(ocf, 2) if ocf else None,
                "fcf_billion": round(fcf, 2) if fcf else None,
                "capex_billion": round(capex, 2) if capex else None,
                "depreciation_billion": round(depr, 2) if depr else None,
                "ocf_to_netprofit": ocf_np,
                "fcf_to_netprofit": fcf_np,
                # 资产负债表 — v0.5.3: 归一化后已是亿元
                "total_assets_billion": round(total_assets, 2) if total_assets else None,
                "total_equity_billion": round(total_equity, 2) if total_equity else None,
                "debt_ratio_pct": debt_ratio,
                "current_ratio": round(cur_ratio, 2) if cur_ratio else None,
                "quick_ratio": round(quick_ratio, 2) if quick_ratio else None,
                "receivables_to_revenue": recv_ratio,
                "receivables_turnover_days": recv_days,
                "inventory_billion": round(inventory, 2) if inventory else None,
                "inventory_turnover_days": inv_days,
                # 资产结构 — v0.5.3: 归一化后已是亿元
                "goodwill_billion": round(goodwill, 2) if goodwill else None,
                "goodwill_to_equity_pct": gw_equity,
                "fixed_asset_billion": round(fixed_assets, 2) if fixed_assets else None,
                "fixed_asset_ratio_pct": fixed_ratio,
                "intangible_assets_billion": round(intangibles, 2) if intangibles else None,
                "capex_to_depreciation": capex_depr,
            })

        trends = self._calc_trends(rows)

        # 取最新年度的关键信号
        latest = rows[-1] if rows else {}
        return {
            "years_covered": [r["year"] for r in rows],
            "yearly_data": rows,
            "trends": trends,
            "latest_signals": {
                "asset_lightness": self._classify_asset_lightness(latest.get("fixed_asset_ratio_pct")),
                "payment_terms": self._classify_payment_terms(latest.get("receivables_turnover_days")),
                "capex_mode": self._classify_capex(latest.get("capex_to_depreciation")),
            },
            "data_source": "raw_data.annual_financials (Tushare income/balance_sheet/cashflow)",
        }

    # ── A2-A6 (保持不变) ──

    def _a2_revenue_structure(self) -> dict:
        """A2: 业务收入结构线索 (透传, LLM自行从websearch提取)"""
        q_ws = self.websearch.get("q_websearch", {})
        snippets = q_ws.get("snippets", [])
        revenue_keywords = ["收入", "营收", "业务", "板块", "占比", "增速",
                            "revenue", "segment", "business"]
        relevant_snippets = []
        for i, s in enumerate(snippets):
            content = s.get("content", "") + s.get("title", "")
            if any(kw in content for kw in revenue_keywords):
                relevant_snippets.append({
                    "snippet_index": i,
                    "title": s.get("title", ""),
                    "url": s.get("url", ""),
                    "has_revenue_data": True,
                })
        return {
            "snippets_with_revenue_data": relevant_snippets,
            "total_snippets": len(snippets),
            "instruction": "LLM请从websearch.q_websearch的snippet中提取各业务线名称、金额、占比、YoY增速",
            "data_source": "websearch.q_websearch",
        }

    def _a3_dividend_repurchase(self) -> dict:
        """A3: 分红回购 5 年统计

        v0.5.3: 按财年聚合（而非取最近 5 条记录），
                金额已归一化为亿元，不再 ÷1e8。
        """
        dividends = self.raw.get("dividend_history", [])
        repurchases = self.raw.get("repurchase_history", [])

        # 按年份分组取 5 个财年（每年可能有多次分红，聚合总额）
        div_sorted = sorted(dividends, key=lambda x: int(x.get("year", 0)), reverse=True)
        year_div_map = {}
        for d in div_sorted:
            year = int(d.get("year", 0))
            if year not in year_div_map:
                year_div_map[year] = {"year": year, "dividend_per_share": 0.0, "total_dividend": 0.0}
            year_div_map[year]["dividend_per_share"] += self._sf(d.get("dividend_per_share"))
            year_div_map[year]["total_dividend"] += self._sf(d.get("total_dividend"))

        # 取最近 5 年
        recent_years = sorted(year_div_map.keys(), reverse=True)[:5]
        recent_years.sort()
        div_rows = []
        total_div = 0.0
        for yr in recent_years:
            d = year_div_map[yr]
            total_div += d["total_dividend"]
            div_rows.append({
                "year": yr,
                "dividend_per_share": round(d["dividend_per_share"], 4),
                "total_dividend_billion": round(d["total_dividend"], 2),
            })

        # 按年份聚合回购总额（与分红聚合逻辑对齐）
        rep_year_map: dict[int, float] = {}
        for r in repurchases:
            year_raw = r.get("year") or r.get("ann_date", "0")
            year_str = str(year_raw)
            year = int(year_str[:4]) if len(year_str) >= 4 else 0
            amount = self._sf(r.get("repurchase_amount"), field_name="A3.repurchase_amount")
            if year not in rep_year_map:
                rep_year_map[year] = 0.0
            rep_year_map[year] += amount

        recent_rep_years = sorted(rep_year_map.keys(), reverse=True)[:5]
        recent_rep_years.sort()
        rep_rows = []
        rep_total = 0.0
        for yr in recent_rep_years:
            amount = rep_year_map[yr]
            rep_total += amount
            rep_rows.append({
                "year": yr,
                "amount_billion": round(amount, 2) if amount else None,
            })
        return {
            "dividend_years": len(div_rows),
            "dividend_detail": div_rows,
            "total_dividend_5y_billion": round(total_div, 2) if total_div else None,
            "repurchase_detail": rep_rows,
            "total_repurchase_billion": round(rep_total, 2) if rep_total else None,
            "data_source": "raw_data.dividend_history + repurchase_history",
        }

    def _a4_cq_gate(self) -> dict:
        """A4: CQ 门 5 维度判定明细"""
        cq = self.computed.get("cash_quality", {})
        if not cq:
            return {"status": "no_data", "message": "computed.cash_quality 为空"}
        return {
            "overall_passed": cq.get("overall_passed"),
            "failed_dimensions": cq.get("failed_dimensions", []),
            "dimension_1_opcf_to_netprofit": {
                "label": "经营CF/净利润(3年均值)", "threshold": "> 0.8",
                "passed": cq.get("dimension_1_opcf_to_netprofit", {}).get("passed"),
                "avg_3y": round(cq.get("dimension_1_opcf_to_netprofit", {}).get("avg_3y", 0), 3),
                "ratios": [round(r, 3) for r in cq.get("dimension_1_opcf_to_netprofit", {}).get("ratios", [])],
            },
            "dimension_2_fcf_positive_years": {
                "label": "FCF正年数(近5年)", "threshold": ">= 4",
                "passed": cq.get("dimension_2_fcf_positive_years", {}).get("passed"),
                "positive_count": cq.get("dimension_2_fcf_positive_years", {}).get("positive_count"),
                "total_years": cq.get("dimension_2_fcf_positive_years", {}).get("total_years"),
            },
            "dimension_3_receivables_ratio": {
                "label": "应收/营收比(3年均值)", "threshold": "< 0.3",
                "passed": cq.get("dimension_3_receivables_ratio", {}).get("passed"),
                "avg_3y": round(cq.get("dimension_3_receivables_ratio", {}).get("avg_3y", 0), 3),
                "ratios": [round(r, 3) for r in cq.get("dimension_3_receivables_ratio", {}).get("ratios", [])],
            },
            "dimension_4_inventory_stability": {
                "label": "库存/营收CV(5年)", "threshold": "< 0.5",
                "passed": cq.get("dimension_4_inventory_stability", {}).get("passed"),
                "cv": round(cq.get("dimension_4_inventory_stability", {}).get("cv", 0), 3),
            },
            "dimension_5_ocf_stability": {
                "label": "经营CF CV(5年)", "threshold": "< 0.5",
                "passed": cq.get("dimension_5_ocf_stability", {}).get("passed"),
                "cv": round(cq.get("dimension_5_ocf_stability", {}).get("cv", 0), 3),
            },
        }

    def _a5_pr_detail(self) -> dict:
        """A5: PR 穿透回报率明细"""
        pr = self.computed.get("penetration_return", {})
        if not pr:
            return {"status": "no_data", "message": "computed.penetration_return 为空"}
        dc = pr.get("disposable_cash", {})
        dist = pr.get("distribution_ratio", 0)
        if isinstance(dist, dict):
            total_dividend_5y = self._sf(dist.get("total_dividend_5y", 0))
            dist_ratio = self._sf(dist.get("ratio", 0))
        else:
            total_dividend_5y = self._sf(pr.get("total_dividend_5y", 0))
            dist_ratio = self._sf(dist)
        pr_result = pr.get("pr_result", {})
        if isinstance(pr_result, dict):
            pr_val = self._sf(pr_result.get("pr", 0))
            threshold_val = self._sf(pr_result.get("threshold", 0))
            risk_free = self._sf(pr_result.get("risk_free_rate", 0))
            spread_val = self._sf(pr_result.get("spread", 0))
            passed = pr_result.get("passed", False)
        else:
            pr_val = self._sf(pr.get("pr", 0))
            threshold_val = self._sf(pr.get("threshold", 0))
            risk_free = self._sf(pr.get("risk_free_rate", 0))
            spread_val = self._sf(pr.get("spread", 0))
            passed = pr.get("passed", False)
        rep = pr.get("repurchase", {})
        if isinstance(rep, dict):
            repurchase = self._sf(rep.get("avg_repurchase_5y", 0))
        else:
            repurchase = self._sf(pr.get("annual_repurchase_cancellation", 0))
        return {
            # v0.5.3: 归一化后已是亿元，不再 ÷1e8
            "disposable_cash_avg_5y_billion": round(self._sf(dc.get("avg_5y", 0)), 4),
            "disposable_cash_cv": round(self._sf(dc.get("cv", 0)), 3),
            "cv_warning": dc.get("cv_warning", False),
            "disposable_cash_5y_values_billion": [
                round(v, 4) for v in dc.get("values_5y", [])
            ],
            "total_dividend_5y_billion": round(total_dividend_5y, 4),
            "distribution_ratio_pct": round(dist_ratio * 100, 1),
            "annual_repurchase_cancellation_billion": round(repurchase, 4),
            # NOTE: computed.yaml 中 pr/ threshold/ risk_free_rate/ spread 已存储为百分比形式
            # (如 pr=2.13=2.13%, risk_free=1.7=1.7%, spread=1.0=1.0%), 不再 ×100 避免二次放大
            "pr_pct": round(pr_val, 2),
            "threshold_pct": round(threshold_val, 2),
            "risk_free_rate_pct": round(risk_free, 2),
            "spread_pct": round(spread_val, 2),
            "passed": passed,
            "data_source": "computed.penetration_return (PR v2 formula)",
        }

    def _a6_valuation_snapshot(self) -> dict:
        """A6: 估值快照

        v0.5.3: total_mv 已是亿元，dividend_yield 已是 %，不再转换。
        v0.6.0: 注入行业对标中位数（PE/PB不在行业缓存中，用ROE/股息率/毛利率/负债率对标）。
        """
        basic = self.raw.get("basic_info", {})
        industry_bench = self._load_industry_stats()

        result = {
            "total_mv_billion": round(self._sf(basic.get("total_mv")), 2) if basic.get("total_mv") else None,
            "pe": self._sf(basic.get("pe")),
            "pb": self._sf(basic.get("pb")),
            "dividend_yield_pct": round(self._sf(basic.get("dividend_yield")), 2) if basic.get("dividend_yield") else None,
            "data_source": "raw_data.basic_info (Tushare daily行情)",
        }

        if industry_bench:
            result["industry_benchmark"] = {
                "industry": industry_bench.get("industry", ""),
                "n_stocks": industry_bench.get("n_stocks"),
                "median_roe_pct": industry_bench.get("median_roe"),
                "median_dividend_yield_pct": industry_bench.get("median_dividend_yield"),
                "median_gross_margin_pct": industry_bench.get("median_gross_margin"),
                "median_debt_ratio_pct": industry_bench.get("median_debt_ratio"),
                "data_source": "industry_stats.yaml (股池行业中位数)",
            }

        return result

    def _load_industry_stats(self) -> dict | None:
        """加载行业对标数据 — v0.6.0 新增"""
        industry = self._extract_industry()
        if not industry:
            return None

        stats_path = settings.STOCK_CACHE_DIR / "industry_stats.yaml"
        if not stats_path.exists():
            return None

        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                all_stats = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("行业对标数据加载失败", exc_info=True)
            return None

        for ind_name, ind_data in all_stats.items():
            if ind_name == industry:
                return {"industry": ind_name, **ind_data}

        # 模糊匹配：行业名包含关系
        for ind_name, ind_data in all_stats.items():
            if industry in ind_name or ind_name in industry:
                return {"industry": ind_name, **ind_data}

        return None

    # ── A7: 生意属性 (v2.0.0 新增) ──

    def _a7_business_profile(self) -> dict:
        """A7: 生意属性 — 收款方式、轻/重资产、现金转化周期 (v2.0.0新增)

        从 A1 的 latest_signals + yearly_data 中直接提取，
        部分维度为半定量 (需websearch补充叙事)。
        """
        a1 = self._a1_core_financials()
        if a1.get("status") == "no_data":
            return {"status": "no_data", "message": "无财务数据"}

        rows = a1.get("yearly_data", [])
        latest = rows[-1] if rows else {}
        signals = a1.get("latest_signals", {})

        # 收款方式 (半定量: 数字硬算 + websearch补充为什么)
        recv_days = latest.get("receivables_turnover_days")
        recv_ratio_5y = [r.get("receivables_to_revenue") for r in rows if r.get("receivables_to_revenue") is not None]

        payment_type = signals.get("payment_terms", "unknown")
        payment_narrative = {
            "advance_or_near_cash": "应收周转<60天, 回款迅速, 接近现款现货或先款后货",
            "normal_credit": "应收周转60-180天, 行业正常信用周期",
            "extended_credit": "应收周转>180天, 回款慢, 可能先货后款或客户议价力强",
            "unknown": "数据不足",
        }.get(payment_type, "")

        # 生意属性 (半定量)
        asset_type = signals.get("asset_lightness", "unknown")
        fixed_ratio = latest.get("fixed_asset_ratio_pct")
        inv_days = latest.get("inventory_turnover_days")
        gross_margin = latest.get("gross_margin_pct")

        capex_mode = signals.get("capex_mode", "unknown")
        capex_narrative = {
            "expansion": f"CAPEX/折旧={latest.get('capex_to_depreciation')}x > 1.2, 扩张期",
            "maintenance": f"CAPEX/折旧={latest.get('capex_to_depreciation')}x 在 0.8-1.2, 维持性投入",
            "underinvesting": f"CAPEX/折旧={latest.get('capex_to_depreciation')}x < 0.8, 投入不足可能吃老本",
            "unknown": "数据不足",
        }.get(capex_mode, "")

        # 现金转化周期 (应收账款周转 + 存货周转 - 应付周转)
        # 应付周转用 total_liab 近似 (实际需要应付账款, 但 schema 无)
        total_assets = latest.get("total_assets_billion")

        return {
            "payment_method": {
                "type": payment_type,
                "receivables_turnover_days": recv_days,
                "receivables_ratio_5y_trend": recv_ratio_5y,
                "narrative": payment_narrative,
                "quant_level": "semi_quantitative",  # 数字有, 但"为什么"需websearch
            },
            "business_nature": {
                "asset_type": asset_type,
                "fixed_asset_ratio_pct": fixed_ratio,
                "inventory_turnover_days": inv_days,
                "gross_margin_pct": gross_margin,
                "narrative": f"固定资产占比{fixed_ratio}%, 存货周转{inv_days}天, 毛利率{gross_margin}%. {asset_type}",
                "quant_level": "semi_quantitative",
            },
            "capex_profile": {
                "mode": capex_mode,
                "capex_to_depreciation": latest.get("capex_to_depreciation"),
                "narrative": capex_narrative,
                "quant_level": "semi_quantitative",
            },
            "data_source": "A1_core_financials (derived metrics)",
        }

    def _a8_valuation_percentile(self) -> dict:
        """A8: 估值历史分位 (PE/PB/股息率) — v0.6.0 新增

        从 raw_data.valuation_history 计算近5年分位点，
        输出当前值 + 5%/25%/50%/75%/95% 分位 + 当前百分位。
        """
        vh = self.raw.get("valuation_history", [])
        if not vh or len(vh) < 20:
            return {"status": "no_data",
                    "message": f"valuation_history 不足20条 (实际{len(vh)}条)"}

        pe_vals = sorted([v["pe"] for v in vh if v.get("pe", 0) > 0])
        pb_vals = sorted([v["pb"] for v in vh if v.get("pb", 0) > 0])
        dv_vals = sorted([v.get("dv_ratio", 0) for v in vh if v.get("dv_ratio", 0) > 0])

        def _pct(vals, p):
            """p: 0.00~1.00"""
            if not vals or len(vals) < 20:
                return None
            idx = max(0, min(int(len(vals) * p), len(vals) - 1))
            return round(vals[idx], 2)

        def _rank(vals, current):
            """current 在 vals 中的百分位 (0-100)"""
            if not vals or current is None or current <= 0:
                return None
            below = sum(1 for v in vals if v <= current)
            return round(below / len(vals) * 100, 1)

        basic = self.raw.get("basic_info", {})
        pe_now = basic.get("pe", 0)
        pb_now = basic.get("pb", 0)
        dv_now = basic.get("dividend_yield", 0)

        return {
            "data_points": len(vh),
            "data_source": "raw_data.valuation_history (Tushare daily_basic 2018+)",
            "pe": {
                "current": pe_now,
                "min_5y": _pct(pe_vals, 0.0),
                "p25": _pct(pe_vals, 0.25),
                "median": _pct(pe_vals, 0.50),
                "p75": _pct(pe_vals, 0.75),
                "max_5y": _pct(pe_vals, 1.0),
                "current_percentile": _rank(pe_vals, pe_now),
            },
            "pb": {
                "current": pb_now,
                "min_5y": _pct(pb_vals, 0.0),
                "p25": _pct(pb_vals, 0.25),
                "median": _pct(pb_vals, 0.50),
                "p75": _pct(pb_vals, 0.75),
                "max_5y": _pct(pb_vals, 1.0),
                "current_percentile": _rank(pb_vals, pb_now),
            },
            "dividend_yield": {
                "current": dv_now,
                "min_5y": _pct(dv_vals, 0.0),
                "p25": _pct(dv_vals, 0.25),
                "median": _pct(dv_vals, 0.50),
                "p75": _pct(dv_vals, 0.75),
                "max_5y": _pct(dv_vals, 1.0),
                "current_percentile": _rank(dv_vals, dv_now),
                "note": "存量数据缺少dv_ratio需--full重拉后补齐" if not dv_vals else None,
            },
        }

    # ──────────────────────────────────────────────
    # Layer 3: 数据充分性评估 (v2.0.0 新增)
    # ──────────────────────────────────────────────

    def _assess_data_sufficiency(self, summary: dict) -> dict:
        """评估每个分析维度的数据覆盖质量

        输出示例喂给 LLM:
        {
          "Q1_business_model": {"level": "rich", "note": "A1有5年完整财务..."},
          "R2_talent":         {"level": "missing", "note": "websearch未搜到人才结构数据, 跳过此维度"},
        }
        """
        a1 = summary.get("A1_core_financials", {})
        a2 = summary.get("A2_revenue_structure", {})
        a5 = summary.get("A5_pr_detail", {})
        a6 = summary.get("A6_valuation_snapshot", {})

        return {
            "Q1_business_model": self._rate_dim(
                "Q1", a1_status=a1.get("status") != "no_data",
                a2_snippets=len(a2.get("snippets_with_revenue_data", [])),
                note="收入结构表 — 数字从websearch提取 (semi-quantitative)"
            ),
            "Q1_payment_method": self._rate_payment(summary),
            "Q1_upstream_downstream": self._rate_websearch("q_websearch", threshold=1,
                note="上下游信息依赖websearch, 属于定性补充"),
            "Q2_moat": self._rate_websearch("q_websearch", threshold=2,
                note="护城河依赖websearch中的市占率/研发/竞品对比"),

            "Q3_growth_engine": self._rate_dim(
                "Q3", a1_status=a1.get("status") != "no_data",
                a2_snippets=len(a2.get("snippets_with_revenue_data", [])),
                note="增长驱动需websearch量价拆分, A1提供营收/利润趋势"
            ),

            "R1_external": self._rate_websearch("r1_websearch", threshold=1,
                note="外部环境完全依赖websearch"),
            "R1_national_strategy": self._rate_websearch("r1_websearch", threshold=1,
                note="国家战略定位属定性维度, 有政策文件引用即可"),

            "R2_management": self._rate_websearch("r2_websearch", threshold=1,
                note="管理层评估依赖websearch, A3提供分红数据补强"),
            "R2_talent": self._rate_websearch("r2_websearch", threshold=1,
                note="人才结构数据常缺失, 如未搜到则跳过"),

            "R3_structure": self._rate_websearch("r3_websearch", threshold=1,
                note="控股结构依赖websearch"),

            "V1_value_trap": {
                "level": "rich",
                "note": "A4提供CQ 5维度完整判定数据, A1提供资产负债数据"
            },
            "V2_valuation": self._rate_valuation(summary),
            "V3_stress_test": self._rate_dim(
                "V3", a5_has_data=a5.get("status") != "no_data",
                note="PR计算来自computed.yaml, 数据可用性取决于Tushare字段完整性"
            ),
        }

    def _rate_dim(self, dim: str, a1_status: bool = False,
                  a2_snippets: int = 0, a5_has_data: bool = False,
                  note: str = "") -> dict:
        if dim in ("Q1", "Q3"):
            if a1_status and a2_snippets >= 1:
                return {"level": "rich", "note": note or f"A1有完整财务, A2有{a2_snippets}条收入线索"}
            elif a1_status:
                return {"level": "partial", "note": "A1有完整财务, 但websearch未捕获收入结构"}
            return {"level": "missing", "note": "数据缺失"}
        if dim == "V3":
            if a5_has_data:
                return {"level": "rich", "note": note or "PR数据完整"}
            return {"level": "partial", "note": note or "PR数据部分缺失"}
        return {"level": "unknown", "note": note}

    def _rate_payment(self, summary: dict) -> dict:
        a1 = summary.get("A1_core_financials", {})
        if a1.get("status") == "no_data":
            return {"level": "missing", "note": "无财务数据"}
        rows = a1.get("yearly_data", [])
        if not rows:
            return {"level": "missing", "note": "无逐年数据"}
        latest = rows[-1]
        recv_days = latest.get("receivables_turnover_days")
        if recv_days is not None:
            return {"level": "rich",
                    "note": f"A1有应收周转{recv_days}天, 收款方式可量化分析 (半定量: 需websearch补充叙事)"}
        return {"level": "partial", "note": "A1应收数据不完整"}

    def _rate_websearch(self, ws_key: str, threshold: int = 1, note: str = "") -> dict:
        ws = self.websearch.get(ws_key, {})
        snippets = ws.get("snippets", [])
        est_count = (ws.get("query_count") or len(snippets)) if ws else 0
        snippet_count = len(snippets)
        if snippet_count >= threshold + 1:
            return {"level": "rich", "note": note or f"websearch有{snippet_count}条snippet"}
        elif snippet_count >= threshold:
            return {"level": "partial", "note": note or f"websearch仅有{snippet_count}条snippet"}
        elif ws and snippet_count > 0:
            return {"level": "partial", "note": note or f"websearch仅有{snippet_count}条snippet, 数据不充分"}
        return {"level": "missing", "note": note or f"websearch.{ws_key} 无数据, 跳过此维度"}

    def _rate_valuation(self, summary: dict) -> dict:
        a6 = summary.get("A6_valuation_snapshot", {})
        a8 = summary.get("A8_valuation_percentile", {})
        ws = self.websearch.get("v_websearch", {})
        snippets = ws.get("snippets", [])
        has_a6 = a6.get("pe") is not None
        has_a8 = a8.get("status") != "no_data"
        has_ws = len(snippets) >= 1
        if has_a6 and has_a8 and has_ws:
            return {"level": "rich",
                    "note": f"A6有PE={a6.get('pe')}/PB={a6.get('pb')}, "
                            f"A8有历史分位, websearch有{len(snippets)}条估值数据"}
        elif has_a6 and has_a8:
            return {"level": "rich",
                    "note": f"A6有当前估值 + A8有历史分位, 但websearch无同行对比"}
        elif has_a6:
            return {"level": "partial", "note": "A6有当前估值, 但无历史分位/同行对比"}
        return {"level": "missing", "note": "无估值数据"}

    # ──────────────────────────────────────────────
    # 参考来源索引 (v3.1.0 新增)
    # ──────────────────────────────────────────────

    def _build_reference_index(self) -> dict:
        """从 websearch 中提取所有 snippet 的 URL 索引。

        输出格式:
        {
          "W-q-1": {"url": "https://...", "title": "...", "source": "q_websearch"},
          "W-r1-3": {...},
          ...
        }
        LLM 在报告中使用 [W-q-3] 标记时，读者可通过此索引找到对应 URL。
        """
        index = {}
        ws_keys = ["q_websearch", "r1_websearch", "r2_websearch", "r3_websearch", "v_websearch"]
        prefix_map = {
            "q_websearch": "W-q",
            "r1_websearch": "W-r1",
            "r2_websearch": "W-r2",
            "r3_websearch": "W-r3",
            "v_websearch": "W-v",
        }
        for key in ws_keys:
            ws = self.websearch.get(key, {})
            snippets = ws.get("snippets", [])
            prefix = prefix_map.get(key, key)
            for i, s in enumerate(snippets):
                ref_id = f"{prefix}-{i + 1}"
                index[ref_id] = {
                    "url": s.get("url", ""),
                    "title": s.get("title", ""),
                    "source": key,
                }
        return index

    @staticmethod
    def _classify_asset_lightness(fixed_ratio_pct) -> str:
        """轻资产/重资产分类"""
        if fixed_ratio_pct is None:
            return "unknown"
        if fixed_ratio_pct < 20:
            return "light_asset"
        elif fixed_ratio_pct < 45:
            return "medium_asset"
        return "heavy_asset"

    @staticmethod
    def _classify_payment_terms(recv_days) -> str:
        """收款方式分类"""
        if recv_days is None:
            return "unknown"
        if recv_days < 60:
            return "advance_or_near_cash"
        elif recv_days < 180:
            return "normal_credit"
        return "extended_credit"

    @staticmethod
    def _classify_capex(capex_depr_ratio) -> str:
        """CAPEX 模式分类"""
        if capex_depr_ratio is None:
            return "unknown"
        if capex_depr_ratio > 1.2:
            return "expansion"
        elif capex_depr_ratio >= 0.8:
            return "maintenance"
        return "underinvesting"

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    @staticmethod
    def _sf(val: Any, field_name: str = "") -> float:
        """安全 float，None/''/异常 → 0.0

        v0.5.3: 新增 field_name 参数，None 时输出 WARNING 日志防止静默归零。
        """
        try:
            if val is None:
                if field_name:
                    logger.warning(f"DataSummarizer._sf: {field_name} is None → 0.0")
                return 0.0
            return float(val)
        except (ValueError, TypeError):
            if field_name:
                logger.warning(f"DataSummarizer._sf: {field_name} invalid → 0.0")
            return 0.0

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        """安全加载 YAML"""
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载 {path} 失败: {e}")
            return {}

    @staticmethod
    def _calc_trends(rows: list) -> dict:
        """计算指标趋势（最近 vs 最早的变化方向）"""
        if len(rows) < 2:
            return {}

        def _trend(key: str) -> str:
            vals = [r[key] for r in rows if r.get(key) is not None]
            if len(vals) < 2:
                return "insufficient_data"
            first, last = vals[0], vals[-1]
            if last > first * 1.05:
                return "up"
            elif last < first * 0.95:
                return "down"
            return "stable"

        return {
            "revenue": _trend("revenue_billion"),
            "net_profit": _trend("net_profit_billion"),
            "gross_margin": _trend("gross_margin_pct"),
            "net_margin": _trend("net_margin_pct"),
            "roe": _trend("roe_pct"),
            "ocf": _trend("ocf_billion"),
            "fcf": _trend("fcf_billion"),
            "receivables_turnover_days": _trend("receivables_turnover_days"),
        }
