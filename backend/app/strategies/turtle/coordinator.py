"""龟龟策略 Coordinator — 流程编排执行器

turtle-coordinator.md 定义流程+维护规则（公式四件套/硬门确定性/测试铁律），
本文件执行实际编排（Python硬逻辑）。

全量刷新流程: Step 1-5 (v0.3.0: CQ/PR改为软门)
按需分析流程: Step 6-8 (v0.4.0: QRV Agent v2 + DataSummarizer)
"""

import asyncio
import json
import logging
import os
import re as _quality_re
import time
import yaml
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse as _quality_urlparse

from app.core.config import settings
from app.strategies.turtle.utils import find_stock_dir

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# v0.7.6: WebSearch 置信度质量加权 (确定性规则引擎，非 LLM)
# ══════════════════════════════════════════════════════════════

def _source_credibility(url: str) -> float:
    """来源可信度 (0.0~1.0)，基于域名分类"""
    if not url:
        return 0.0
    try:
        domain = _quality_urlparse(url).netloc.lower()
    except Exception:
        return 0.1

    OFFICIAL = {'sse.com.cn', 'szse.cn', 'csrc.gov.cn', 'cninfo.com.cn'}
    AUTHORITATIVE = {'bloomberg.com', 'reuters.com', 'wsj.com'}
    RESEARCH = {'dfcfw.com', 'research'}
    MAINSTREAM = {
        'caixin.com', '36kr.com', 'cs.com.cn', 'people.com.cn',
        'yicai.com', 'cls.cn', 'eastmoney.com', 'stcn.com',
        'guancha.cn', 'yemacaijing.com', 'jiemian.com',
    }
    AGGREGATOR = {
        'sohu.com', 'sina.com', 'mp.cnfol.com', '163.com',
        'qq.com', 'ifeng.com', 'fengkouapp.com', 'iyiou.com',
        'pedaily.cn',
    }

    if any(d in domain for d in OFFICIAL):
        return 1.0
    if any(d in domain for d in AUTHORITATIVE):
        return 0.8
    if any(d in domain for d in RESEARCH):
        return 0.7
    if any(d in domain for d in MAINSTREAM):
        return 0.5
    if any(d in domain for d in AGGREGATOR):
        return 0.3
    return 0.1


def _info_density(content: str) -> float:
    """信息密度 (0.0~1.0)，基于内容中数字+单位组合的数量"""
    if not content:
        return 0.0
    hits = len(_quality_re.findall(
        r'\b\d+\.?\d*\s*(万亿|千亿|百亿|亿|[万千百]|元|%|倍|个)\b', content,
    ))
    if hits >= 5:
        return 1.0
    if hits >= 2:
        return 0.7
    if hits >= 1:
        return 0.4
    if len(content) > 80:
        return 0.2
    return 0.0


def _recency(text: str) -> float:
    """时效性 (0.0~1.0)，基于文本中出现的年份"""
    years = _quality_re.findall(r'(20\d{2})\s*年', text)
    if not years:
        return 0.3
    latest = max(int(y) for y in years)
    current = 2026
    if latest >= current - 1:
        return 1.0
    if latest >= current - 3:
        return 0.5
    return 0.2


def _quality_label(score: float) -> str:
    """质量总分 → 置信度四级标签"""
    if score >= 2.0:
        return "HIGH"
    if score >= 1.2:
        return "MEDIUM"
    if score > 0.0:
        return "LOW"
    return "NONE"


class CoordinatorState(str, Enum):
    """Coordinator 状态机"""
    IDLE = "idle"
    SCREENING = "screening"
    FETCHING = "fetching"
    COMPUTING = "computing"
    GATING = "gating"
    READY = "ready"
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"


@dataclass
class StepResult:
    """单个步骤的执行结果"""
    step_name: str
    success: bool
    message: str = ""
    data: dict = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class CoordinatorContext:
    """Coordinator 执行上下文"""
    state: CoordinatorState = CoordinatorState.IDLE
    trace_id: str = ""
    rule_version: str = "v2"
    current_step: str = ""
    step_results: list[StepResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TurtleCoordinator:
    """龟龟策略编排器

    负责：
    1. 确定性计算的步骤编排（Step 1-5）
    2. 步骤间数据完整性校验
    3. 错误处理和状态管理
    4. QRV Agent 编排（Step 6-8, v0.3.0）
    """

    def __init__(
        self,
        cache_dir: Path,
        rule_version: str = "v2",
        risk_free_rate: float | None = None,
    ):
        # v0.5.3: 从 settings 读取 TURTLE_RISK_FREE_RATE，环境变量覆盖硬编码默认值
        self.cache_dir = Path(cache_dir)
        self.rule_version = rule_version
        self.risk_free_rate = (
            risk_free_rate
            or getattr(settings, "TURTLE_RISK_FREE_RATE", 1.7)
        )
        self.ctx = CoordinatorContext(rule_version=rule_version)
        self.qrv_agent = None  # 懒初始化，避免循环import

    # ====================================================================
    # 全量刷新流程 (Step 1-5) — v0.3.0: CQ/PR 改为软门
    # ====================================================================

    async def run_full_refresh(
        self,
        stocks: list[dict] | None = None,
        *,
        fetch_data: bool = True,
        force: bool = False,
    ) -> list[dict]:
        """执行全量刷新：选股 → 数据拉取 → 计算 → 软门标记 → 股池

        v0.3.0: CQ/PR 改为软门，不淘汰，仅标记。

        Args:
            stocks: 全A股基础数据列表。None 则从 Tushare 实时拉取
            fetch_data: 是否执行 Step 2 数据拉取
            force: 强制重新拉取个股数据，忽略已有缓存

        Returns:
            通过计算的所有股票列表（含CQ/PR标记），按PR降序
        """
        from .screener import TurtleScreener
        from .cash_quality import CashQualityGate
        from .penetration_return import PenetrationReturnCalculator
        from app.services.data_fetcher import DataFetcher
        from app.core.logging import set_trace_id
        import uuid

        self.ctx.trace_id = set_trace_id(str(uuid.uuid4())[:8])

        # === Step 0: 拉取全A股基础信息（如果未提供） ===
        if stocks is None and fetch_data:
            print("[Step 0] Fetching all A-share basic info...", flush=True)
            logger.info("Step 0: 拉取全A股基础信息...")
            fetcher = DataFetcher(cache_dir=self.cache_dir)
            stocks_df = fetcher.fetch_stock_basic()
            if stocks_df.empty:
                self.ctx.state = CoordinatorState.ERROR
                self.ctx.errors.append("stock_basic 拉取失败")
                return []
            stocks = stocks_df.to_dict("records")
            logger.info(f"全A股基础信息: {len(stocks)} 只")

        if not stocks:
            self.ctx.state = CoordinatorState.ERROR
            self.ctx.errors.append("无输入股票数据")
            return []

        self.ctx.state = CoordinatorState.SCREENING

        # === Step 1: 选股器 ===
        print("[Step 1] Screener screening...", flush=True)
        self.ctx.current_step = "screener"
        screener = TurtleScreener()
        candidates, stats = screener.screen(stocks)
        print(f"[OK] Candidates: {len(candidates)} stocks", flush=True)
        logger.info(screener.get_fail_summary(stats))
        self.ctx.step_results.append(StepResult(
            step_name="screener",
            success=True,
            message=f"候选池: {len(candidates)} 只",
            data={"candidate_count": len(candidates), "stats": vars(stats)},
        ))

        if len(candidates) < 50:
            print(f"[WARN] Small candidate pool: {len(candidates)} (expected 80-150)", flush=True)
            logger.warning(f"候选池偏小: {len(candidates)}")
        if len(candidates) == 0:
            self.ctx.state = CoordinatorState.READY
            return []

        # SPEC Step1 L122: 输出 candidate_pool.yaml
        self._write_candidate_pool(candidates)

        # === Step 2: 数据拉取 ===
        self.ctx.state = CoordinatorState.FETCHING
        self.ctx.current_step = "data_fetch"

        if fetch_data:
            print(f"[Step 2] Fetching data for {len(candidates)} candidates...", flush=True)
            fetcher = DataFetcher(cache_dir=self.cache_dir)
            ts_codes = [c.ts_code for c in candidates]
            name_map = {c.ts_code: c.name for c in candidates}
            fetch_stats = fetcher.fetch_candidate_data(ts_codes, force=force, name_map=name_map)
            print(f"[OK] Data fetch: {fetch_stats.success_rate:.1f}% success rate", flush=True)
            self.ctx.step_results.append(StepResult(
                step_name="data_fetch",
                success=fetch_stats.success_rate >= 90,
                message=fetch_stats.summary(),
                data={
                    "total": fetch_stats.total,
                    "success": fetch_stats.success,
                    "failed": fetch_stats.failed,
                    "failed_codes": fetch_stats.failed_codes,
                },
            ))
            if fetch_stats.success_rate < 90:
                msg = f"拉取成功率 {fetch_stats.success_rate:.1f}% < 90%，终止流程"
                logger.error(msg)
                print(f"[ERROR] {msg}", flush=True)
                self.ctx.state = CoordinatorState.ERROR
                self.ctx.errors.append(msg)
                return []
        else:
            logger.info("跳过数据拉取（fetch_data=False）")
            self.ctx.step_results.append(StepResult(
                step_name="data_fetch",
                success=True,
                message="跳过数据拉取，使用已有缓存",
            ))

        # === Step 3-5: 对每只候选股计算 + 软门判定 (v0.3.0: 不淘汰) ===
        self.ctx.state = CoordinatorState.COMPUTING
        cash_quality_gate = CashQualityGate(rule_version=self.rule_version)
        pr_calculator = PenetrationReturnCalculator(
            risk_free_rate=self.risk_free_rate,
            spread=getattr(settings, "TURTLE_SPREAD", 1.0),
            rule_version=self.rule_version,
        )

        pool = []
        cq_pass = 0
        cq_fail = 0
        pr_pass = 0
        pr_fail = 0
        pr_excluded = 0  # v0.6.20: disposable_cash_avg <= 0 硬排除
        dim_fail_stats = {"dim1": 0, "dim2": 0, "dim3": 0, "dim4": 0, "dim5": 0,
                          "dim6": 0, "dim7": 0, "dim8": 0}
        pr_cv_warnings = 0

        print(f"[Step 3-5] Computing CQ/PR + soft gates for {len(candidates)} candidates...", flush=True)
        loop_start_t = time.time()
        skipped_missing = 0

        def _print_progress(i_done: int):
            elapsed = time.time() - loop_start_t
            done = i_done + 1
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(candidates) - done) / rate if rate > 0 else 0
            print(
                f"  [Progress] {done}/{len(candidates)} "
                f"({done/len(candidates)*100:.0f}%) "
                f"| CQ通过: {cq_pass} | PR通过: {pr_pass} "
                f"| 股池: {len(pool)} | PR排除: {pr_excluded} | 缺失: {skipped_missing} "
                f"| 速率 {rate:.1f}只/s | 预计剩余 {eta:.0f}s",
                flush=True,
            )

        for i, candidate in enumerate(candidates):
            ts_code = candidate.ts_code
            safe_name = candidate.name.replace("/", "-").replace("\\", "-")
            new_path = self.cache_dir / f"{safe_name}_{ts_code}" / "raw_data.yaml"
            old_path = self.cache_dir / ts_code / "raw_data.yaml"
            stock_dir = new_path.parent if new_path.exists() else old_path.parent
            raw_path = stock_dir / "raw_data.yaml"

            should_print = (i + 1) % 10 == 0 or i == len(candidates) - 1

            if not raw_path.exists():
                logger.warning(f"{ts_code}: raw_data.yaml 不存在，跳过")
                skipped_missing += 1
                if should_print:
                    _print_progress(i)
                continue

            with open(raw_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)

            # Step 3 前置校验
            if not self._validate_raw_data(raw_data, ts_code):
                skipped_missing += 1
                if should_print:
                    _print_progress(i)
                continue

            # Step 3: 现金质量计算
            cq_result = cash_quality_gate.compute(raw_data)

            # Step 4: 现金质量门 [软门 — v0.3.0: 标记不淘汰]
            if cq_result.overall_passed:
                cq_pass += 1
            else:
                cq_fail += 1
                for dim in cq_result.failed_dimensions:
                    dim_fail_stats[f"dim{dim}"] += 1

            # PR计算
            pr_result = pr_calculator.compute(raw_data)

            # Step 5: 穿透回报率门 [软门 — v0.3.0: 标记不淘汰]
            if pr_result.passed:
                pr_pass += 1
            else:
                pr_fail += 1
                if pr_result.disposable_cash_cv >= pr_calculator.CV_MAX:
                    pr_cv_warnings += 1

            # 写入 computed.yaml
            computed_data = {
                "meta": {
                    "ts_code": ts_code,
                    "name": candidate.name,
                    "rule_version": self.rule_version,
                    "computed_date": "",
                },
                "cash_quality": cash_quality_gate.to_computed_format(cq_result),
                "penetration_return": pr_calculator.to_computed_format(pr_result),
            }

            computed_dir = self.cache_dir / f"{safe_name}_{ts_code}"
            computed_dir.mkdir(parents=True, exist_ok=True)
            computed_path = computed_dir / "computed.yaml"
            with open(computed_path, "w", encoding="utf-8") as f:
                yaml.dump(computed_data, f, allow_unicode=True, default_flow_style=False)

            # 构建 gate_summary（v0.3.0 新增）
            gate_summary = {
                "screener": {"passed": True},
                "cash_quality": {
                    "passed": cq_result.overall_passed,
                    "failed_dimensions": cq_result.failed_dimensions,
                    "details": {
                        f"dim{k}": v for k, v in cq_result.details.items()
                    },
                },
                "penetration_return": {
                    "passed": pr_result.passed,
                    "pr": pr_result.pr,
                    "threshold": pr_result.threshold,
                    "disposable_cash_cv": pr_result.disposable_cash_cv,
                    "cv_warning": pr_result.disposable_cash_cv >= pr_calculator.CV_MAX,
                },
            }

            # v0.6.20: 可支配现金均值 ≤ 0 → 硬排除，不入股池
            if pr_result.disposable_cash_avg <= 0:
                pr_excluded += 1
                logger.info(f"{ts_code}: 可支配现金均值={pr_result.disposable_cash_avg:.1f} <= 0, 硬排除不入股池")
                if should_print:
                    _print_progress(i)
                continue

            pool.append({
                "ts_code": ts_code,
                "name": candidate.name,
                "industry": candidate.industry,
                "pr": pr_result.pr,
                "pe": candidate.pe,
                "pb": candidate.pb,
                "roe": candidate.roe,
                "dividend_yield": candidate.dividend_yield,
                "gross_margin": candidate.gross_margin,
                "debt_ratio": candidate.debt_ratio,
                "market_cap": candidate.total_mv,
                "cq_passed": cq_result.overall_passed,
                "pr_passed": pr_result.passed,
                "gate_summary": gate_summary,
            })

            if should_print:
                _print_progress(i)

        # 按PR降序排列
        pool.sort(key=lambda x: x["pr"], reverse=True)

        # v0.6.0: 计算行业对标数据
        self._compute_industry_stats(pool)

        # 输出统计
        logger.info(
            f"现金质量门维度失败统计: dim1(OCF/NP)={dim_fail_stats['dim1']}, "
            f"dim2(FCF)={dim_fail_stats['dim2']}, "
            f"dim3(应收)={dim_fail_stats['dim3']}, "
            f"dim4(存货)={dim_fail_stats['dim4']}, "
            f"dim5(OCF_CV)={dim_fail_stats['dim5']}, "
            f"dim6(FCF分红覆盖)={dim_fail_stats['dim6']}, "
            f"dim7(供应商挤压)={dim_fail_stats['dim7']}, "
            f"dim8(有息负债趋势)={dim_fail_stats['dim8']}"
        )

        self.ctx.state = CoordinatorState.READY
        self.ctx.step_results.extend([
            StepResult(
                step_name="cash_quality_gate",
                success=True,
                message=f"通过: {cq_pass}, 未通过(标记): {cq_fail}",
                data={"passed": cq_pass, "failed": cq_fail, "dim_fails": dim_fail_stats},
            ),
            StepResult(
                step_name="pr_gate",
                success=True,
                message=f"股池: {len(pool)} 只 (PR通过: {pr_pass}, 标记: {pr_fail}, "
                        f"硬排除(可支配现金≤0): {pr_excluded}, CV预警: {pr_cv_warnings})",
                data={"pool_size": len(pool), "pr_pass": pr_pass, "pr_fail": pr_fail,
                      "pr_excluded": pr_excluded},
            ),
        ])

        logger.info(
            f"全量刷新完成: 候选{len(candidates)} → "
            f"CQ通过{cq_pass}/未通过{cq_fail} → PR通过{pr_pass}/未通过{pr_fail}/排除{pr_excluded} → 股池{len(pool)}"
        )
        print(
            f"[Done] 全量刷新完成: 候选{len(candidates)} → "
            f"CQ通过{cq_pass}/未通过{cq_fail} → PR通过{pr_pass}/未通过{pr_fail}/排除{pr_excluded} → 软门股池{len(pool)}",
            flush=True,
        )

        return pool

    # ====================================================================
    # 按需分析流程 (Step 6-8) — v0.3.0 重写
    # ====================================================================

    async def analyze_single_stock(self, ts_code: str,
                                    force_websearch: bool = False) -> dict:
        """单股按需分析 (v0.3.0)

        Args:
            ts_code: 股票代码
            force_websearch: v0.6.0 强制重搜，跳过 WebSearch 缓存

        Returns:
            分析报告路径和摘要
        """
        self.ctx.state = CoordinatorState.ANALYZING
        self.ctx.current_step = "analyzing"

        # Step 6: 构建统一数据包 qrv_input.yaml
        print(f"[Step 6] Building qrv_input.yaml...", flush=True)
        qrv_input_path = await self._build_qrv_input(ts_code)
        if qrv_input_path is None:
            self.ctx.state = CoordinatorState.ERROR
            self.ctx.errors.append(f"{ts_code}: 数据包构建失败")
            return {"ts_code": ts_code, "error": "数据包构建失败"}

        # Step 7: WebSearch Agent (5次 Tavily 搜索)
        print(f"[Step 7] WebSearch Agent (5 Tavily searches)...", flush=True)
        websearch_data = await self._run_websearch(ts_code, qrv_input_path,
                                                     force=force_websearch)
        # 追加到 qrv_input.yaml
        self._append_websearch_to_qrv_input(qrv_input_path, websearch_data)

        # Step 8: QRV Agent (单次LLM分析)
        print(f"[Step 8] QRV Agent analysis (LLM call)...", flush=True)
        report_paths = await self._run_qrv_analysis(ts_code, qrv_input_path)

        self.ctx.state = CoordinatorState.DONE
        self.ctx.step_results.append(StepResult(
            step_name="qrv_analysis",
            success=True,
            message=f"QRV分析完成",
            data=report_paths,
        ))

        print(f"[Done] Single stock analysis: {ts_code}", flush=True)
        return {
            "ts_code": ts_code,
            **report_paths,
        }

    # ====================================================================
    # 单股全流程：数据拉取 → 计算 → QRV (v0.6.10)
    # ====================================================================

    async def run_single_stock_full(
        self,
        ts_code: str,
        force: bool = False,
        status_callback: Optional[Callable] = None,
    ) -> dict:
        """单股全流程分析：数据拉取 → 计算 CQ+PR → WebSearch → QRV Agent

        用于 API 按需触发，封装了原 run_single_stock_analysis.py 脚本的完整逻辑。

        Args:
            ts_code: 股票代码 (如 600900.SH)
            force: 强制重拉 Tushare 数据，忽略已有缓存
            status_callback: 可选进度回调 (status, message, progress)

        Returns:
            {"ts_code": ..., "qrv_analysis_md": ..., "qrv_analysis_json": ...}
        """
        def _update(status: str, message: str, progress: int = 0):
            if status_callback:
                status_callback(status, message, progress)
            logger.info(f"[{ts_code}] {status}: {message}")

        from app.services.data_fetcher import DataFetcher
        from .cash_quality import CashQualityGate
        from .penetration_return import PenetrationReturnCalculator

        # ── Step 0: 获取股票中文名 ──
        _update("fetching", f"正在获取 {ts_code} 基本信息...", 5)
        from app.services.tushare_client import TushareClient
        tc = TushareClient()
        stock_name = ts_code
        try:
            basic = tc.call("stock_basic", ts_code=ts_code, fields="ts_code,name")
            if not basic.empty:
                stock_name = str(basic.iloc[0].get("name", ts_code))
        except Exception:
            logger.warning(f"{ts_code}: 无法获取股票名，使用代码")

        # ── Step 1: 拉取财务数据 ──
        _update("fetching", f"正在拉取 {stock_name} 财务数据...", 10)
        fetcher = DataFetcher(cache_dir=self.cache_dir)
        stats = fetcher.fetch_candidate_data(
            [ts_code], force=force,
            name_map={ts_code: stock_name},
        )
        if stats.failed > 0:
            raise RuntimeError(f"数据拉取失败: {stats.failed_codes}")

        stock_dir = find_stock_dir(self.cache_dir, ts_code)
        if stock_dir is None:
            raise RuntimeError(f"找不到 {ts_code} 缓存目录")

        raw_path = stock_dir / "raw_data.yaml"
        if not raw_path.exists():
            raise RuntimeError(f"{ts_code}: raw_data.yaml 不存在")

        with open(raw_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        name = raw_data.get("meta", {}).get("name", stock_name)
        safe_name = name.replace("/", "-").replace("\\", "-")

        # ── Step 2: 计算 CQ + PR ──
        _update("computing", f"正在计算 {name} 现金质量 + 穿透回报率...", 30)

        cq_gate = CashQualityGate(rule_version=self.rule_version)
        cq_result = cq_gate.compute(raw_data)

        risk_free = float(getattr(settings, "TURTLE_RISK_FREE_RATE", 1.7))
        spread_val = float(getattr(settings, "TURTLE_SPREAD", 1.0))
        pr_calc = PenetrationReturnCalculator(risk_free_rate=risk_free, spread=spread_val)
        pr_result = pr_calc.compute(raw_data)

        # 写入 computed.yaml
        computed_data = {
            "meta": {"ts_code": ts_code, "name": name, "rule_version": self.rule_version},
            "cash_quality": cq_gate.to_computed_format(cq_result),
            "penetration_return": pr_calc.to_computed_format(pr_result),
        }
        computed_path = stock_dir / "computed.yaml"
        with open(computed_path, "w", encoding="utf-8") as f:
            yaml.dump(computed_data, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"{ts_code}: CQ={'PASS' if cq_result.overall_passed else 'FAIL'}, "
                    f"PR={pr_result.pr:.2f}% {'PASS' if pr_result.passed else 'FAIL'}")

        # ── Step 3: 构建 qrv_input ──
        _update("computing", f"正在构建 {name} 统一数据包...", 50)
        qrv_input_path = await self._build_qrv_input(ts_code)
        if qrv_input_path is None:
            raise RuntimeError(f"{ts_code}: 数据包构建失败")

        # ── Step 4: WebSearch ──
        _update("websearch", f"正在搜索 {name} 外部信息 (5次Tavily)...", 60)
        websearch_data = await self._run_websearch(ts_code, qrv_input_path, force=False)
        self._append_websearch_to_qrv_input(qrv_input_path, websearch_data)

        # ── Step 5: QRV Agent ──
        _update("analyzing", f"正在调用 LLM 分析 {name}...", 80)
        report_paths = await self._run_qrv_analysis(ts_code, qrv_input_path)

        _update("done", f"{name} 分析完成", 100)

        return {
            "ts_code": ts_code,
            **report_paths,
        }

    # ── Step 6: 构建 qrv_input.yaml ──

    async def _build_qrv_input(self, ts_code: str) -> Optional[Path]:
        """Step 6: 构建统一数据包

        整合 raw_data + computed + screener + gate_results → qrv_input.yaml
        """
        import yaml

        # 确定缓存路径
        stock_dir = find_stock_dir(self.cache_dir, ts_code)
        if stock_dir is None:
            logger.error(f"{ts_code}: 找不到缓存目录")
            return None

        raw_path = stock_dir / "raw_data.yaml"
        computed_path = stock_dir / "computed.yaml"

        if not raw_path.exists():
            logger.error(f"{ts_code}: raw_data.yaml 不存在")
            return None

        with open(raw_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        computed_data = {}
        if computed_path.exists():
            with open(computed_path, "r", encoding="utf-8") as f:
                computed_data = yaml.safe_load(f)

        # 构建 gate_summary
        gate_summary = {
            "screener": self._get_screener_info(ts_code, stock_dir),
            "cash_quality": computed_data.get("cash_quality", {}),
            "penetration_return": computed_data.get("penetration_return", {}),
        }

        # 组装统一数据包
        qrv_input = {
            "meta": {
                "ts_code": ts_code,
                "name": raw_data.get("meta", {}).get("name", ""),
                "rule_version": self.rule_version,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            "company_profile": {
                "ts_code": ts_code,
                "name": raw_data.get("meta", {}).get("name", ""),
                "industry": raw_data.get("basic_info", {}).get("industry", ""),
                "list_date": raw_data.get("basic_info", {}).get("list_date", ""),
                "total_mv": raw_data.get("basic_info", {}).get("total_mv", 0),
                "pe": raw_data.get("basic_info", {}).get("pe", 0),
                "pb": raw_data.get("basic_info", {}).get("pb", 0),
                "dividend_yield": raw_data.get("basic_info", {}).get("dividend_yield", 0),
            },
            "financial_data": {
                "annual_financials": raw_data.get("annual_financials", []),
            },
            "cq_results": computed_data.get("cash_quality", {}),
            "pr_results": computed_data.get("penetration_return", {}),
            "dividend_repurchase": {
                "dividend_history": raw_data.get("dividend_history", []),
                "repurchase_history": raw_data.get("repurchase_history", []),
            },
            "gate_summary": gate_summary,
            "websearch_results": {},  # Step 7 填充
        }

        qrv_path = stock_dir / "qrv_input.yaml"
        with open(qrv_path, "w", encoding="utf-8") as f:
            yaml.dump(qrv_input, f, allow_unicode=True, default_flow_style=False)

        logger.info(f"{ts_code}: qrv_input.yaml 已构建")
        return qrv_path

    def _get_screener_info(self, ts_code: str, stock_dir: Path) -> dict:
        """从 candidate_pool.yaml 获取该股选股器信息"""
        pool_path = self.cache_dir / "candidate_pool.yaml"
        if pool_path.exists():
            with open(pool_path, "r", encoding="utf-8") as f:
                pool = yaml.safe_load(f)
            for c in pool:
                if c.get("ts_code") == ts_code:
                    return {"passed": True, "industry": c.get("industry", "")}
        return {"passed": True}

    # ── Step 7: WebSearch Agent ──

    async def _run_websearch(self, ts_code: str, qrv_input_path: Path,
                             force: bool = False) -> dict:
        """Step 7: 执行 5 次 Tavily 搜索

        读取 qrv_input.yaml 获取公司名和框架，执行搜索。
        v0.6.0: 7天缓存复用，--force-websearch 可强制重搜。
        """
        # 检查缓存
        if not force:
            stock_dir = find_stock_dir(self.cache_dir, ts_code)
            if stock_dir:
                ws_cache = stock_dir / "websearch.yaml"
                if ws_cache.exists():
                    cache_age = time.time() - ws_cache.stat().st_mtime
                    if cache_age < 7 * 86400:  # 7天内有效
                        with open(ws_cache, "r", encoding="utf-8") as f:
                            cached = yaml.safe_load(f)
                        if cached and isinstance(cached, dict) and len(cached) >= 3:
                            logger.info(
                                f"{ts_code}: WebSearch 缓存命中 (age={cache_age/86400:.1f}d, "
                                f"{len(cached)} 模块)"
                            )
                            return cached

        with open(qrv_input_path, "r", encoding="utf-8") as f:
            qrv_input = yaml.safe_load(f)

        company_name = qrv_input.get("company_profile", {}).get("name", ts_code)
        industry = qrv_input.get("company_profile", {}).get("industry", "")

        # 从 turtle_qrv.yaml 读取搜索配置
        search_configs = self._load_qrv_search_config()

        results = {}
        for search_cfg in search_configs:
            search_id = search_cfg["id"]
            try:
                result = await self._tavily_search(
                    company_name=company_name,
                    industry=industry,
                    keywords=search_cfg["keywords"],
                    description=search_cfg["description"],
                )
                results[search_id] = result
                logger.info(f"WebSearch {search_id}: {len(result.get('snippets', []))} 条结果")
            except Exception as e:
                logger.error(f"WebSearch {search_id} 失败: {e}")
                results[search_id] = {"error": str(e), "snippets": []}

        # 写入 websearch.yaml
        stock_dir = find_stock_dir(self.cache_dir, ts_code)
        if stock_dir:
            ws_path = stock_dir / "websearch.yaml"
            with open(ws_path, "w", encoding="utf-8") as f:
                yaml.dump(results, f, allow_unicode=True, default_flow_style=False)

        return results

    def _load_qrv_search_config(self) -> list[dict]:
        """从 turtle_qrv.yaml 加载搜索配置"""
        rules_dir = settings.RULES_DIR
        qrv_yaml = rules_dir / "v2" / "turtle_qrv.yaml"
        try:
            with open(qrv_yaml, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            return config.get("websearch", {}).get("searches", [])
        except Exception as e:
            logger.warning(f"无法加载 turtle_qrv.yaml: {e}，使用默认搜索配置")
            return self._default_search_config()

    @staticmethod
    def _default_search_config() -> list[dict]:
        """默认搜索配置（兜底）"""
        return [
            {"id": "q_websearch", "description": "商业模式+护城河",
             "keywords": ["商业模式 竞争优势", "护城河 竞争壁垒"]},
            {"id": "r1_websearch", "description": "外部环境",
             "keywords": ["行业政策 监管风险", "宏观环境 经济周期"]},
            {"id": "r2_websearch", "description": "管理层+治理",
             "keywords": ["管理层 变更", "股权激励 MD&A"]},
            {"id": "r3_websearch", "description": "控股结构",
             "keywords": ["实控人 股权质押", "关联交易"]},
            {"id": "v_websearch", "description": "估值概述",
             "keywords": ["估值 价值陷阱", "PE PB 历史分位"]},
        ]

    async def _tavily_search(
        self,
        company_name: str,
        industry: str,
        keywords: list[str],
        description: str,
    ) -> dict:
        """执行单次 Tavily 搜索

        对每个关键词发起一次搜索，合并结果。
        """
        api_key = getattr(settings, "TAVILY_API_KEY", "")
        if not api_key:
            logger.warning("TAVILY_API_KEY 未配置，返回空搜索结果")
            return {"description": description, "snippets": [], "confidence": "NONE"}

        # 替换模板中的【公司名】
        queries = [kw.replace("【公司名】", company_name) for kw in keywords]

        all_snippets = []
        for query in queries:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": api_key,
                            "query": query,
                            "search_depth": "basic",
                            "max_results": 5,
                            "include_answer": True,
                        },
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            answer = data.get("answer", "")
                            if answer:
                                qs_a = _info_density(answer) + _recency(answer)  # answer无URL
                                all_snippets.append({
                                    "type": "answer",
                                    "content": answer,
                                    "confidence": _quality_label(qs_a),
                                    "quality_score": round(qs_a, 2),
                                })
                            for r in data.get("results", [])[:3]:
                                url_r = r.get("url", "")
                                content_r = r.get("content", "")
                                qs_r = (
                                    _source_credibility(url_r)
                                    + _info_density(content_r)
                                    + _recency(content_r)
                                )
                                all_snippets.append({
                                    "type": "result",
                                    "title": r.get("title", ""),
                                    "url": url_r,
                                    "content": content_r,
                                    "confidence": _quality_label(qs_r),
                                    "quality_score": round(qs_r, 2),
                                })
            except Exception as e:
                logger.error(f"Tavily search '{query}' 失败: {e}")

        # v0.7.6: 质量加权置信度 (来源可信度 + 信息密度 + 时效性)
        total_quality = sum(s.get("quality_score", 0) for s in all_snippets)
        if total_quality >= 12:
            confidence = "HIGH"
        elif total_quality >= 6:
            confidence = "MEDIUM"
        elif total_quality >= 2:
            confidence = "LOW"
        else:
            confidence = "NONE"

        return {
            "description": description,
            "snippets": all_snippets,
            "confidence": confidence,
            "query_count": len(queries),
        }

    def _append_websearch_to_qrv_input(self, qrv_path: Path, websearch_data: dict):
        """将 WebSearch 结果追加到 qrv_input.yaml"""
        with open(qrv_path, "r", encoding="utf-8") as f:
            qrv_input = yaml.safe_load(f)

        qrv_input["websearch_results"] = websearch_data

        with open(qrv_path, "w", encoding="utf-8") as f:
            yaml.dump(qrv_input, f, allow_unicode=True, default_flow_style=False)

        logger.info("WebSearch 结果已追加到 qrv_input.yaml")

    # ── Step 8: QRV Agent (委托给 QRVAgent) ──

    async def _run_qrv_analysis(self, ts_code: str, qrv_input_path: Path) -> dict:
        """Step 8: QRV Agent 单次 LLM 分析

        委托给 .qrv_agent.QRVAgent 执行。
        coordinator 只负责 Step 6-7 (数据包构建 + WebSearch)。
        """
        if self.qrv_agent is None:
            from .qrv_agent import QRVAgent  # 延迟导入，断开循环import
            self.qrv_agent = QRVAgent(
                cache_dir=self.cache_dir,
                rule_version=self.rule_version,
            )
        result = await self.qrv_agent.analyze_async(ts_code)
        return result

    # ====================================================================
    # 辅助方法
    # ====================================================================

    def _write_candidate_pool(self, candidates: list) -> None:
        """SPEC Step1 L122: 写入 candidate_pool.yaml"""
        pool_path = self.cache_dir / "candidate_pool.yaml"
        data = [
            {
                "ts_code": c.ts_code,
                "name": c.name,
                "industry": c.industry,
                "total_mv": c.total_mv,
                "pe": c.pe,
                "pb": c.pb,
                "dividend_yield": c.dividend_yield,
            }
            for c in candidates
        ]
        with open(pool_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"candidate_pool.yaml 已写入: {len(candidates)} 只")

    def _validate_raw_data(self, raw_data: dict, ts_code: str) -> bool:
        """Step 3 前置校验: 检查 raw_data 是否具备计算所需的必要字段

        Returns:
            True if valid, False if insufficient
        """
        financials = raw_data.get("annual_financials", [])
        if len(financials) < 3:
            logger.warning(f"{ts_code}: 财务数据不足3年 ({len(financials)}年)，跳过计算")
            return False

        if len(financials) < 5:
            logger.info(f"{ts_code}: 财务数据不足5年 ({len(financials)}年), "
                        f"CQ可通过但PR将标记不完整")

        # 检查必须的嵌套结构
        required_paths = [
            ("income", "net_profit"),
            ("income", "revenue"),
            ("cashflow", "operating_cf"),
            ("balance_sheet", "receivables"),
        ]
        for parent, child in required_paths:
            missing_count = sum(
                1 for f in financials
                if parent not in f or child not in f[parent]
            )
            if missing_count == len(financials):
                logger.warning(f"{ts_code}: 所有年份缺少 {parent}.{child}，跳过计算")
                return False

        # 检查 basic_info 中的 total_mv (PR计算需要)
        basic = raw_data.get("basic_info", {})
        if not basic.get("total_mv") or basic.get("total_mv", 0) <= 0:
            logger.warning(f"{ts_code}: total_mv 缺失或为0，跳过PR计算")
            return False

        # v0.7.1: 检查 v0.7.0 新增字段是否存在于缓存中，缺失则 WARNING
        optional_fields = {
            "cashflow": ["dividend_paid_cf"],           # dim6 FCF分红覆盖
            "balance_sheet": ["accounts_payable", "notes_payable",  # dim7 供应商挤压
                            "st_borrow", "lt_borrow", "bonds_payable",  # dim8 有息负债
                            "noncurrent_liab_due_in_1y"],
        }
        for parent, children in optional_fields.items():
            for child in children:
                present = any(
                    parent in f and child in f[parent]
                    for f in financials
                )
                if not present:
                    logger.warning(
                        f"{ts_code}: {parent}.{child} 在所有年份均缺失，"
                        f"相关 CQ 维度将因数据不足标记为通过。"
                        f"建议 --full 全量重拉获取该字段。"
                    )

        return True

    def _compute_industry_stats(self, pool: list[dict]):
        """v0.6.0: 按行业计算对标数据，写入 industry_stats.yaml

        从股池中提取 industry × PE/ROE/股息率/毛利率/负债率，
        按行业分组计算中位数，供 A6 估值快照注入行业对标。
        """
        if not pool:
            return

        from collections import defaultdict

        groups: dict[str, list[dict]] = defaultdict(list)
        for item in pool:
            ind = (item.get("industry") or "").strip()
            # 从 pool 顶层字段读取（v0.6.0: 已在 pool 构建时写入）
            pe = item.get("pe", 0)
            roe = item.get("roe", 0)
            dy = item.get("dividend_yield", 0)
            gm = item.get("gross_margin", 0)
            dr = item.get("debt_ratio", 0)
            if ind and any(v > 0 for v in [pe, roe, dy, gm, dr]):
                groups[ind].append({
                    "pe": pe, "roe": roe, "dividend_yield": dy,
                    "gross_margin": gm, "debt_ratio": dr,
                })

        import statistics
        stats: dict[str, dict] = {}
        for ind, items in groups.items():
            stats[ind] = {
                "median_pe": round(statistics.median([x["pe"] for x in items if x["pe"] > 0]), 2) if items else None,
                "median_roe": round(statistics.median([x["roe"] for x in items if x["roe"] > 0]), 2) if items else None,
                "median_dividend_yield": round(statistics.median([x["dividend_yield"] for x in items if x["dividend_yield"] > 0]), 2) if items else None,
                "median_gross_margin": round(statistics.median([x["gross_margin"] for x in items if x["gross_margin"] > 0]), 2) if items else None,
                "median_debt_ratio": round(statistics.median([x["debt_ratio"] for x in items if x["debt_ratio"] > 0]), 2) if items else None,
                "n_stocks": len(items),
            }

        stats_path = self.cache_dir / "industry_stats.yaml"
        with open(stats_path, "w", encoding="utf-8") as f:
            yaml.dump(stats, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"行业对标数据已写入: {stats_path} ({len(stats)} 个行业)")

    def get_status(self) -> dict:
        """获取当前 Coordinator 状态"""
        return {
            "state": self.ctx.state.value,
            "current_step": self.ctx.current_step,
            "trace_id": self.ctx.trace_id,
            "rule_version": self.ctx.rule_version,
            "errors": self.ctx.errors,
        }
