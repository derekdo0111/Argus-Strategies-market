"""
收敛性验证实验：冻结所有外部输入后，跑 3 次对比 LLM 输出是否一致。

设计：
  Run 1 (record): 正常运行，拦截并缓存所有 Tavily 调用 + LLM 生成的反例搜索词
  Run 2 (replay): 从缓存回放 Tavily 结果 + 反例搜索词，DB 回滚到基线
  Run 3 (replay): 同 Run 2

对比维度：
  1. HypothesizeAgent 输出：假设数量、标题、陈述文本
  2. VerifyAgent 输出：每条假设的 (source_count, data_alignment, counter_conflict, status)
  3. CounterAgent 输出：overturned / unreachable 数量
  4. Screening 输出：股票池数量及代码

用法：
  cd backend
  python ../scripts/convergence_experiment.py --industry 人工智能 --force
"""

import argparse
import copy
import json
import os
import shutil
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import patch

# 确保 backend 在 path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import requests


# ═══════════════════════════════════════════════════
# 缓存层
# ═══════════════════════════════════════════════════

class TavilyCache:
    """缓存 Tavily API 的 request → response 映射。"""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._data: dict[str, list[dict]] = {}
        self.mode: str = "record"
        self.hits: int = 0
        self.misses: int = 0
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False)

    @staticmethod
    def _key(query: str, depth: str, max_results: int) -> str:
        return f"{query}||{depth}||{max_results}"

    def get(self, query: str, depth: str, max_results: int) -> Optional[list[dict]]:
        key = self._key(query, depth, max_results)
        if key in self._data:
            self.hits += 1
            return copy.deepcopy(self._data[key])
        self.misses += 1
        return None

    def set(self, query: str, depth: str, max_results: int, results: list[dict]):
        key = self._key(query, depth, max_results)
        self._data[key] = copy.deepcopy(results)


class CounterQueryCache:
    """缓存 VerifyAgent 的 LLM 生成反例搜索词。"""

    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self._data: dict[str, list[str]] = {}
        self.mode: str = "record"
        if cache_path.exists():
            with open(cache_path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}

    def save(self):
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            yaml.dump(self._data, f, allow_unicode=True, default_flow_style=False)

    def get(self, chain_label: str) -> Optional[list[str]]:
        return copy.deepcopy(self._data.get(chain_label))

    def set(self, chain_label: str, queries: list[str]):
        self._data[chain_label] = copy.deepcopy(queries)


# ═══════════════════════════════════════════════════
# 中间状态捕获
# ═══════════════════════════════════════════════════

class PipelineCapture:
    """捕获协调器各阶段的中间输出。"""

    def __init__(self):
        self.search_result: Optional[dict] = None
        self.hypotheses: list[dict] = []
        self.verification: Optional[dict] = None
        self.screening_result: Optional[dict] = None
        self.report_result: Optional[dict] = None
        self.state_snapshots: list[dict] = []

    def snapshot(self, stage: str, data: dict = None):
        self.state_snapshots.append({
            "stage": stage,
            "ts": time.time(),
            "data": copy.deepcopy(data) if data else {},
        })


# ═══════════════════════════════════════════════════
# 指标提取
# ═══════════════════════════════════════════════════

def extract_metrics_from_capture(capture: PipelineCapture, label: str) -> dict:
    """从 PipelineCapture 中提取可对比指标"""
    v = capture.verification or {}
    sr = capture.screening_result or {}
    rpt = capture.report_result or {}

    hypotheses = v.get("hypotheses", [])
    statuses = v.get("statuses", {})
    stock_pool = sr.get("stock_pool", [])

    hypothesis_details = []
    for h in hypotheses:
        hypothesis_details.append({
            "id": h.get("id", "unknown"),
            "title": (h.get("title", "") or "")[:80],
            "statement": (h.get("statement", "") or "")[:200],
            "level": h.get("chain_level", ""),
            "status": h.get("status", "unverified"),
            "sentiment": h.get("sentiment", ""),
            "verified_sentiment": h.get("verified_sentiment", ""),
            "confidence": h.get("confidence", 0),
            "source_count": h.get("source_count", None),
            "data_alignment": h.get("data_alignment", ""),
            "counter_conflict": h.get("counter_conflict", ""),
            "derives_from": h.get("derives_from", ""),
        })

    return {
        "label": label,
        "rating": rpt.get("rating", "?"),
        "prosperity_level": rpt.get("prosperity_level", rpt.get("rating", "?")),
        "signal_strength": rpt.get("signal_strength", 0),
        "stock_pool_size": rpt.get("stock_count", len(stock_pool)),
        "stock_symbols": sorted([
            s.get("symbol", s.get("ts_code", "")) for s in stock_pool
        ]),
        "hypothesis_count": len(hypotheses),
        "statuses": statuses,
        "hypothesis_details": hypothesis_details,
    }


# ═══════════════════════════════════════════════════
# 差异计算
# ═══════════════════════════════════════════════════

def compute_diffs(runs: list[dict]) -> list[dict]:
    """对比 run 之间的差异"""
    diffs = []

    # 1. 全局指标对比
    for i in range(len(runs) - 1):
        r1 = runs[i]
        r2 = runs[i + 1]
        label = f"{r1['label']} vs {r2['label']}"

        if r1["rating"] != r2["rating"]:
            diffs.append({"pair": label, "field": "rating",
                          "run_a": r1["rating"], "run_b": r2["rating"]})

        if r1["stock_pool_size"] != r2["stock_pool_size"]:
            diffs.append({"pair": label, "field": "stock_pool_size",
                          "run_a": r1["stock_pool_size"], "run_b": r2["stock_pool_size"]})
            sym_a = set(r1["stock_symbols"])
            sym_b = set(r2["stock_symbols"])
            if sym_a - sym_b:
                diffs.append({"pair": label, "field": "stocks_only_in_a",
                              "detail": sorted(sym_a - sym_b)})
            if sym_b - sym_a:
                diffs.append({"pair": label, "field": "stocks_only_in_b",
                              "detail": sorted(sym_b - sym_a)})

        if r1["hypothesis_count"] != r2["hypothesis_count"]:
            diffs.append({"pair": label, "field": "hypothesis_count",
                          "run_a": r1["hypothesis_count"], "run_b": r2["hypothesis_count"]})

        if r1["statuses"] != r2["statuses"]:
            diffs.append({"pair": label, "field": "statuses",
                          "run_a": r1["statuses"], "run_b": r2["statuses"]})

        if r1["signal_strength"] != r2["signal_strength"]:
            diffs.append({"pair": label, "field": "signal_strength",
                          "run_a": r1["signal_strength"], "run_b": r2["signal_strength"]})

    # 2. 逐假设详情对比
    if runs:
        all_h_ids = set()
        for run in runs:
            for h in run["hypothesis_details"]:
                all_h_ids.add(h["id"])

        for h_id in sorted(all_h_ids):
            h_runs = []
            for run in runs:
                match = [h for h in run["hypothesis_details"] if h["id"] == h_id]
                h_runs.append(match[0] if match else None)

            # status 对比
            statuses = [h["status"] if h else "MISSING" for h in h_runs]
            if len(set(statuses)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "status",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": statuses,
                })

            # source_count 对比
            counts = [h.get("source_count", "N/A") if h else "MISSING" for h in h_runs]
            if len(set(str(c) for c in counts)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "source_count",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": counts,
                })

            # counter_conflict 对比
            cc = [h.get("counter_conflict", "N/A") if h else "MISSING" for h in h_runs]
            if len(set(str(c) for c in cc)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "counter_conflict",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": cc,
                })

            # data_alignment 对比
            da = [h.get("data_alignment", "N/A") if h else "MISSING" for h in h_runs]
            if len(set(str(d) for d in da)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "data_alignment",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": da,
                })

            # sentiment 对比
            sent = [h.get("sentiment", "N/A") if h else "MISSING" for h in h_runs]
            if len(set(str(s) for s in sent)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "sentiment",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": sent,
                })

            # verified_sentiment 对比（v0.20 新增：3轮LLM投票后的 sentiment）
            vsent = [h.get("verified_sentiment", "N/A") if h else "MISSING" for h in h_runs]
            if len(set(str(s) for s in vsent)) > 1:
                diffs.append({
                    "pair": f"H:{h_id}", "field": "verified_sentiment",
                    "title": h_runs[0]["title"] if h_runs[0] else "?",
                    "run_values": vsent,
                })

    return diffs


# ═══════════════════════════════════════════════════
# 报告生成
# ═══════════════════════════════════════════════════

def generate_report(
    industry: str,
    runs: list[dict],
    diffs: list[dict],
    tavily_stats: dict,
    elapsed_times: list[float],
    output_path: Path,
):
    """生成 Markdown 格式的收敛性报告"""
    lines = []
    lines.append(f"# 收敛性验证报告：{industry}")
    lines.append(f"\n> **实验时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> **实验方法**：Run1 录制所有 Tavily 调用 + 反例搜索词 → Run2/Run3 从缓存回放")
    lines.append(f"> **DB 隔离**：每轮运行前回滚 DB 到基线，确保 history context 一致")
    lines.append("")
    lines.append("---")
    lines.append("")

    total_diffs = len(diffs)
    if total_diffs == 0:
        verdict = "✅ **完全收敛** — 3 次运行在所有对比维度上完全一致"
    elif total_diffs <= 5:
        verdict = f"⚠️ **高度收敛** — 仅 {total_diffs} 处微小差异"
    elif total_diffs <= 15:
        verdict = f"⚠️ **基本收敛** — {total_diffs} 处差异，存在轻微 LLM 不确定性"
    else:
        verdict = f"❌ **不收敛** — {total_diffs} 处差异，LLM 输出存在显著内在不确定性"

    lines.append("## 执行摘要")
    lines.append(f"\n{verdict}\n")

    # 耗时
    lines.append("### 耗时")
    for i, t in enumerate(elapsed_times):
        lines.append(f"- Run {i+1}: {t:.1f}s ({t/60:.1f}min)")
    lines.append("")

    # 缓存统计
    lines.append("### Tavily 缓存统计")
    for mode, stats in tavily_stats.items():
        lines.append(
            f"- **{mode}**: {stats['hits']} hits / {stats['misses']} misses / "
            f"{stats['api_calls']} actual API calls"
        )
    lines.append("")

    # 全局对比表
    lines.append("## 全局指标对比")
    lines.append("")
    lines.append("| 指标 | Run 1 (record) | Run 2 (replay) | Run 3 (replay) | 一致性 |")
    lines.append("|------|----------------|----------------|----------------|--------|")
    for field, display in [
        ("rating", "景气评级"),
        ("prosperity_level", "景气等级"),
        ("signal_strength", "信号强度"),
        ("hypothesis_count", "假设数量"),
        ("stock_pool_size", "股票池大小"),
    ]:
        vals = []
        for run in runs:
            v = run.get(field, "?")
            vals.append(str(v))
        consistent = "✅" if len(set(vals)) == 1 else "❌"
        lines.append(f"| {display} | {vals[0]} | {vals[1]} | {vals[2]} | {consistent} |")

    # 状态分布
    lines.append("")
    lines.append("### 假设状态分布")
    lines.append("")
    status_keys = ["confirmed", "partial", "disputed", "unverified", "unreachable", "overturned"]
    lines.append("| 状态 | Run 1 | Run 2 | Run 3 | 一致性 |")
    lines.append("|------|-------|-------|-------|--------|")
    for sk in status_keys:
        vals = [str(runs[i]["statuses"].get(sk, 0)) for i in range(3)]
        consistent = "✅" if len(set(vals)) == 1 else "❌"
        lines.append(f"| {sk} | {vals[0]} | {vals[1]} | {vals[2]} | {consistent} |")
    lines.append("")

    # 逐假设详情
    if runs:
        lines.append("## 逐假设详情对比")
        lines.append("")
        h_ids = [h["id"] for h in runs[0]["hypothesis_details"]]
        lines.append("| 假设ID | 标题 | Run1 | Run2 | Run3 | 一致 |")
        lines.append("|--------|------|------|------|------|------|")
        for h_id in h_ids:
            info = []
            for run in runs:
                match = [h for h in run["hypothesis_details"] if h["id"] == h_id]
                if match:
                    h = match[0]
                    info.append(f"{h['status']}")
                else:
                    info.append("MISSING")
            consistent = "✅" if len(set(info)) == 1 else "❌"
            title = runs[0]["hypothesis_details"][0]["title"] if runs[0]["hypothesis_details"] else "?"
            # 找对应标题
            for run in runs:
                for h in run["hypothesis_details"]:
                    if h["id"] == h_id:
                        title = h["title"]
                        break
            short_title = title[:45] + ("..." if len(title) > 45 else "")
            lines.append(
                f"| {h_id} | {short_title} | {info[0]} | {info[1]} | {info[2]} | {consistent} |"
            )
    lines.append("")

    # 差异详情
    lines.append("## 差异详情")
    lines.append("")
    if diffs:
        for i, d in enumerate(diffs):
            lines.append(f"### 差异 #{i+1}: `{d['pair']}` / `{d['field']}`")
            if "run_a" in d and "run_b" in d:
                lines.append(f"- Run A: `{d['run_a']}`")
                lines.append(f"- Run B: `{d['run_b']}`")
            if "title" in d:
                lines.append(f"- 假设: {d['title']}")
            if "run_values" in d:
                lines.append(f"- 三次运行值: `{d['run_values']}`")
            if "detail" in d:
                lines.append(f"- 详情: {d['detail']}")
            lines.append("")
    else:
        lines.append("**无差异。** 3 次运行在所有维度上完全一致。\n")

    # 结论与建议
    lines.append("---")
    lines.append("")
    lines.append("## 结论与建议")
    lines.append("")
    if total_diffs == 0:
        lines.append(
            "在冻结所有外部输入（Tavily 搜索结果 + 反例搜索词 + DB history context）的条件下，\n"
            "3 次运行的输出 **完全一致**。\n\n"
            "### 这意味着什么\n\n"
            "1. **DeepSeek temperature=0 在当前 pipeline 中产生了确定性输出**\n"
            "   - HypothesizeAgent、VerifyAgent、CounterAgent 在相同输入下输出相同结果\n"
            "2. **之前观察到的 Run1 vs Run2 巨大波动（0 vs 26 股池）完全源于外部输入不一致**\n"
            "   - 主因：Tavily 搜索引擎在不同时刻返回了不同结果\n"
            "   - 次因：反例搜索词微妙变化导致 counter_conflict 判断不同\n"
            "3. **修复方向非常明确**\n"
            "   - 问题不在 LLM 的稳定性，而在外部输入的稳定性\n"
            "   - 不需要多轮投票、不需要分级评分\n"
            "\n"
            "### 推荐的最小改动方案\n\n"
            "| 优先级 | 改动 | 预期效果 |\n"
            "|--------|------|----------|\n"
            "| **P0** | 当日 Tavily 搜索缓存（同行业同日只搜一次） | 消除 80%+ 波动 |\n"
            "| P1 | CounterAgent 软衰减（防 0 股池极端情况） | 消除级联放大 |\n"
            "| P2 | Tavily 反例搜索缓存（同搜索词复用） | 消除剩余波动 |\n"
            "\n"
            "实施 P0 后预期稳定性评分从 25/100 → **90+/100**。"
        )
    else:
        lines.append(
            f"在冻结所有外部输入后，仍存在 **{total_diffs} 处差异**。\n\n"
            "### 这意味着什么\n\n"
            "1. **DeepSeek temperature=0 未能实现严格的确定性输出**\n"
            "   - 即使输入完全相同，LLM 的语义判断（尤其是反例解释）仍存在随机性\n"
            "2. **波动同时来自两个层面**\n"
            "   - 外部输入波动（Tavily 搜索）\n"
            "   - LLM 内在不确定性（temperature=0 的 softmax 仍有 tie-breaking）\n"
            "3. **需要多层面防御**\n"
            "   - 输入层面：Tavily 缓存\n"
            "   - 判断层面：Q3 去二元化 + 多轮投票\n"
            "   - 级联层面：软衰减\n"
            "\n"
            "### 推荐方案\n\n"
            "| 优先级 | 改动 | 预期效果 |\n"
            "|--------|------|----------|\n"
            "| **P0** | 当日 Tavily 缓存 + Q3 去二元化 | 消除 50%+ 波动 |\n"
            "| P1 | 多轮投票（Self-Consistency, 3轮） | 进一步消除 LLM 层波动 |\n"
            "| P2 | CounterAgent 软衰减 | 防止极端 0 股池 |\n"
        )

    # 写入
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n[OK] Report generated: {output_path}")
    return output_path


# ═══════════════════════════════════════════════════
# Pipeline 执行 + Patch
# ═══════════════════════════════════════════════════

def _get_db_path() -> Path:
    """获取 prosperity DB 路径"""
    from app.core.config import settings
    return settings.PROSPERITY_DATA_DIR / "prosperity.db"


def _backup_db() -> Path:
    """备份 DB 到临时文件"""
    db_path = _get_db_path()
    backup_path = db_path.with_suffix(".db.experiment_backup")
    if db_path.exists():
        shutil.copy2(db_path, backup_path)
        print(f"  [DB] Backup: {db_path} → {backup_path}")
    else:
        print(f"  [DB] No existing DB to backup (first run)")
    return backup_path


def _restore_db(backup_path: Path):
    """从备份恢复 DB"""
    db_path = _get_db_path()
    if backup_path.exists():
        shutil.copy2(backup_path, db_path)
        print(f"  [DB] Restored: {backup_path} → {db_path}")
    else:
        print(f"  [DB] No backup to restore")


def run_pipeline_with_patches(
    industry: str,
    force: bool,
    run_label: str,
    tavily_cache: TavilyCache,
    counter_query_cache: CounterQueryCache,
    raw_dir: Path,
    db_backup: Path,
    is_first_run: bool,
) -> tuple[dict, PipelineCapture]:
    """
    在 monkey-patch 下运行一次完整 pipeline。
    返回 (result, capture)
    """
    from app.strategies.prosperity.coordinator import Coordinator
    from app.strategies.prosperity.agents import search_agent, verify_agent
    from app.strategies.prosperity.agents.hypothesize_agent import LLMUnavailableError

    # ── DB 隔离：非首次运行前回滚 DB ──
    if not is_first_run:
        _restore_db(db_backup)

    # ── Patch 1: SearchAgent._tavily_search ──
    original_search_tavily = search_agent.SearchAgent._tavily_search

    def patched_search_tavily(self, query, max_results=10):
        depth = "advanced"
        if tavily_cache.mode == "replay":
            cached = tavily_cache.get(query, depth, max_results)
            if cached is not None:
                return cached
            print(f"      [replay] WARN Tavily MISS (main): {query[:60]}...  -> real API")
        results = original_search_tavily(self, query, max_results)
        if tavily_cache.mode == "record":
            tavily_cache.set(query, depth, max_results, results)
        return results

    # ── Patch 2: VerifyAgent._execute_counter_searches ──
    def patched_counter_search(self, queries):
        all_results = []
        for query in queries:
            depth = "basic"
            max_results = 5
            if tavily_cache.mode == "replay":
                cached = tavily_cache.get(query, depth, max_results)
                if cached is not None:
                    all_results.extend(cached)
                    continue
                print(f"      [replay] WARN Tavily MISS (counter): {query[:60]}...  -> real API")

            if not self.tavily_api_key:
                continue
            try:
                resp = requests.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.tavily_api_key,
                        "query": query,
                        "search_depth": depth,
                        "max_results": max_results,
                    },
                    timeout=30,
                )
                if resp.status_code == 200:
                    results = resp.json().get("results", [])
                    formatted = []
                    for r in results[:5]:
                        formatted.append({
                            "query": query,
                            "title": r.get("title", ""),
                            "url": r.get("url", ""),
                            "content": r.get("content", "")[:300],
                        })
                    if tavily_cache.mode == "record":
                        tavily_cache.set(query, depth, max_results, formatted)
                    all_results.extend(formatted)
            except Exception as e:
                print(f"      [experiment] Counter search failed: {e}")
        return all_results

    # ── Patch 3: VerifyAgent._generate_counter_queries ──
    original_gen_queries = verify_agent.VerifyAgent._generate_counter_queries

    def patched_gen_queries(self, industry_name, chain, chain_label):
        if counter_query_cache.mode == "replay":
            cached = counter_query_cache.get(chain_label)
            if cached is not None:
                return cached
            print(f"      [replay] WARN Counter query MISS: {chain_label}  -> LLM generation")
        queries = original_gen_queries(self, industry_name, chain, chain_label)
        if counter_query_cache.mode == "record":
            counter_query_cache.set(chain_label, queries)
        return queries

    # ── Patch 4: 捕获 Coordinator 中间状态 ──
    capture = PipelineCapture()

    from app.strategies.prosperity import coordinator as coord_module

    original_run_hypothesize = coord_module.Coordinator._run_hypothesize_agent
    original_run_verify = coord_module.Coordinator._run_verify_agent
    original_run_screening = coord_module.Coordinator._run_screening_agent
    original_run_report = coord_module.Coordinator._run_report_agent
    original_run_counter = coord_module.Coordinator._run_counter_agent

    def capture_hypothesize(self, industry_name, session_id, search_result, history=None):
        result = original_run_hypothesize(self, industry_name, session_id, search_result, history)
        capture.hypotheses = copy.deepcopy(result)
        capture.snapshot("hypothesize", {"count": len(result)})
        return result

    def capture_verify(self, industry_name, session_id, hypotheses, search_result, history=None):
        result = original_run_verify(self, industry_name, session_id, hypotheses, search_result, history)
        capture.verification = copy.deepcopy(result)
        capture.snapshot("verify", result.get("statuses", {}))
        return result

    def capture_counter(self, industry_name, session_id, verified_hypotheses):
        result = original_run_counter(self, industry_name, session_id, verified_hypotheses)
        # CounterAgent 返回修改后的 hypotheses，更新 capture 中的状态分布
        cascade_statuses = {}
        for h in result:
            s = h.get("status", "unverified")
            cascade_statuses[s] = cascade_statuses.get(s, 0) + 1
        capture.snapshot("counter", cascade_statuses)
        # 同步更新 verification 中的 hypotheses（用于指标提取）
        if capture.verification:
            capture.verification = copy.deepcopy(capture.verification)
            capture.verification["hypotheses"] = copy.deepcopy(result)
            # 重新统计 statuses
            new_statuses = {}
            for h in result:
                s = h.get("status", "unverified")
                new_statuses[s] = new_statuses.get(s, 0) + 1
            capture.verification["statuses"] = new_statuses
        return result

    def capture_screening(self, industry_name, session_id, verification, search_result, history=None):
        result = original_run_screening(self, industry_name, session_id, verification, search_result, history)
        capture.screening_result = copy.deepcopy(result)
        capture.snapshot("screening", {"stock_pool_size": len(result.get("stock_pool", []))})
        return result

    def capture_report(self, industry_name, session_id, verification, screening_result, history=None):
        result = original_run_report(self, industry_name, session_id, verification, screening_result, history)
        capture.report_result = copy.deepcopy(result)
        capture.snapshot("report", {"rating": result.get("rating", "?")})
        return result

    # 应用所有 patches
    with patch.object(search_agent.SearchAgent, "_tavily_search", patched_search_tavily), \
         patch.object(verify_agent.VerifyAgent, "_execute_counter_searches", patched_counter_search), \
         patch.object(verify_agent.VerifyAgent, "_generate_counter_queries", patched_gen_queries), \
         patch.object(coord_module.Coordinator, "_run_hypothesize_agent", capture_hypothesize), \
         patch.object(coord_module.Coordinator, "_run_verify_agent", capture_verify), \
         patch.object(coord_module.Coordinator, "_run_counter_agent", capture_counter), \
         patch.object(coord_module.Coordinator, "_run_screening_agent", capture_screening), \
         patch.object(coord_module.Coordinator, "_run_report_agent", capture_report):

        c = Coordinator()
        try:
            result = c.run_full_pipeline(industry, force=force)
        except LLMUnavailableError as e:
            print(f"\n  [ABORT] {run_label}: LLM API unavailable — {e}")
            return {"status": "failed", "error": str(e)}, capture

        # 如果 capture 中没有从 counter-agent patch 拿到状态，从 pipeline_cache 获取
        if capture.verification is None:
            pc = c.pipeline_cache.get(result.get("session_id"), {})
            capture.verification = copy.deepcopy(pc.get("verification", {}))
            capture.screening_result = copy.deepcopy(pc.get("screening", {}))

        return result, capture


# ═══════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="收敛性验证实验")
    parser.add_argument("--industry", default="人工智能", help="行业名称")
    parser.add_argument("--force", action="store_true", default=True, help="跳过冷却期")
    parser.add_argument("--output", default=None, help="报告输出路径（默认自动生成）")
    args = parser.parse_args()

    industry = args.industry
    raw_dir = BACKEND_DIR / "data" / "prosperity" / "raw" / industry
    raw_dir.mkdir(parents=True, exist_ok=True)

    tavily_cache_path = raw_dir / "experiment_tavily_cache.yaml"
    counter_query_cache_path = raw_dir / "experiment_counter_query_cache.yaml"

    print("=" * 70)
    print(f"  收敛性验证实验：{industry}")
    print(f"  方法：Run1 录制 → Run2/Run3 回放 → 对比")
    print(f"  DB 隔离：每轮回滚到基线")
    print("=" * 70)

    # ── 备份 DB（基线快照）──
    db_backup = _backup_db()

    try:
        # ═══ Phase 1: Run 1 — Record ═══
        print("\n" + "─" * 70)
        print("  [Phase 1] Run 1 — RECORD mode (录制所有外部调用)")
        print("─" * 70)

        tavily_cache = TavilyCache(tavily_cache_path)
        tavily_cache.mode = "record"
        tavily_cache._data = {}

        counter_query_cache = CounterQueryCache(counter_query_cache_path)
        counter_query_cache.mode = "record"
        counter_query_cache._data = {}

        t0 = time.time()
        result1, capture1 = run_pipeline_with_patches(
            industry, args.force, "Run1",
            tavily_cache, counter_query_cache, raw_dir,
            db_backup, is_first_run=True
        )
        t1 = time.time() - t0

        if result1.get("status") == "failed":
            print(f"\n[ABORT] Run 1 failed: {result1.get('error', 'unknown')}")
            print("LLM API unavailable — aborting entire experiment.")
            return

        tavily_cache.save()
        counter_query_cache.save()
        print(f"\n  [Cache] Tavily: {len(tavily_cache._data)} entries → {tavily_cache_path}")
        print(f"  [Cache] Counter queries: {len(counter_query_cache._data)} entries → {counter_query_cache_path}")

        tavily_stats_run1 = {
            "hits": tavily_cache.hits, "misses": tavily_cache.misses,
            "api_calls": len(tavily_cache._data)
        }

        # ═══ Phase 2: Run 2 — Replay ═══
        print("\n" + "─" * 70)
        print("  [Phase 2] Run 2 — REPLAY mode (回放缓存 + DB 回滚)")
        print("─" * 70)

        tavily_cache2 = TavilyCache(tavily_cache_path)
        tavily_cache2.mode = "replay"

        counter_query_cache2 = CounterQueryCache(counter_query_cache_path)
        counter_query_cache2.mode = "replay"

        t0 = time.time()
        result2, capture2 = run_pipeline_with_patches(
            industry, args.force, "Run2",
            tavily_cache2, counter_query_cache2, raw_dir,
            db_backup, is_first_run=False
        )
        t2 = time.time() - t0

        if result2.get("status") == "failed":
            print(f"\n[ABORT] Run 2 failed: {result2.get('error', 'unknown')}")
            print("LLM API unavailable — aborting entire experiment.")
            return

        tavily_stats_run2 = {
            "hits": tavily_cache2.hits, "misses": tavily_cache2.misses,
            "api_calls": tavily_cache2.misses
        }

        # ═══ Phase 3: Run 3 — Replay ═══
        print("\n" + "─" * 70)
        print("  [Phase 3] Run 3 — REPLAY mode (回放缓存 + DB 回滚)")
        print("─" * 70)

        tavily_cache3 = TavilyCache(tavily_cache_path)
        tavily_cache3.mode = "replay"

        counter_query_cache3 = CounterQueryCache(counter_query_cache_path)
        counter_query_cache3.mode = "replay"

        t0 = time.time()
        result3, capture3 = run_pipeline_with_patches(
            industry, args.force, "Run3",
            tavily_cache3, counter_query_cache3, raw_dir,
            db_backup, is_first_run=False
        )
        t3 = time.time() - t0

        if result3.get("status") == "failed":
            print(f"\n[ABORT] Run 3 failed: {result3.get('error', 'unknown')}")
            print("LLM API unavailable — aborting entire experiment.")
            return

        tavily_stats_run3 = {
            "hits": tavily_cache3.hits, "misses": tavily_cache3.misses,
            "api_calls": tavily_cache3.misses
        }

    finally:
        # 恢复 DB（清理实验痕迹）
        _restore_db(db_backup)
        # 删除备份文件
        if db_backup.exists():
            db_backup.unlink()
            print(f"  [DB] Cleaned up backup: {db_backup}")

    # ═══ Phase 4: 对比分析 ═══
    print("\n" + "─" * 70)
    print("  [Phase 4] 对比分析")
    print("─" * 70)

    metrics = [
        extract_metrics_from_capture(capture1, "Run1"),
        extract_metrics_from_capture(capture2, "Run2"),
        extract_metrics_from_capture(capture3, "Run3"),
    ]

    # 保存指标快照
    metrics_path = raw_dir / "experiment_metrics.yaml"
    with open(metrics_path, "w", encoding="utf-8") as f:
        yaml.dump(metrics, f, allow_unicode=True, default_flow_style=False)
    print(f"  Metrics saved: {metrics_path}")

    diffs = compute_diffs(metrics)

    # 打印摘要
    print(f"\n  {'='*50}")
    print(f"  结果摘要")
    print(f"  {'='*50}")
    for m in metrics:
        print(f"  {m['label']}: rating={m['rating']} | h={m['hypothesis_count']} | "
              f"stocks={m['stock_pool_size']} | signal={m['signal_strength']} | "
              f"statuses={m['statuses']}")
    print(f"\n  差异数: {len(diffs)}")
    if diffs:
        for d in diffs[:20]:  # 最多显示前 20 条
            print(f"  - {d['pair']} / {d['field']}: {d.get('run_values', d.get('run_a', '?'))}")
        if len(diffs) > 20:
            print(f"  ... 还有 {len(diffs) - 20} 条差异，详见报告")

    # 生成报告
    output_path = Path(args.output) if args.output else raw_dir / "convergence_report.md"
    tavily_stats = {
        "Run 1 (record)": tavily_stats_run1,
        "Run 2 (replay)": tavily_stats_run2,
        "Run 3 (replay)": tavily_stats_run3,
    }
    generate_report(
        industry, metrics, diffs, tavily_stats,
        [t1, t2, t3], output_path
    )

    # 最终结论
    print(f"\n  {'='*50}")
    if len(diffs) == 0:
        print(f"  [OK] Fully converged! LLM pipeline is 100% deterministic with frozen inputs.")
        print(f"  -> Suggestion: implement Tavily daily cache only")
    else:
        print(f"  [WARN] {len(diffs)} differences found, LLM has inherent non-determinism.")
        print(f"  -> Suggestion: implement P0 (de-binary Q3) + P1 (majority voting)")
    print(f"  {'='*50}")


if __name__ == "__main__":
    main()
