"""分段验证脚本：任意步骤独立重播 N 次，对比 LLM 输出稳定性。

用法：
  # Record — 全流程跑一次，每步后自动存 checkpoint
  python scripts/segmented_verify.py --industry 人工智能 --record --force

  # Replay 单步 N 次
  python scripts/segmented_verify.py --industry 人工智能 --step hypothesize --runs 3
  python scripts/segmented_verify.py --industry 人工智能 --step verify      --runs 3
  python scripts/segmented_verify.py --industry 人工智能 --step counter     --runs 3
  python scripts/segmented_verify.py --industry 人工智能 --step screening   --runs 3
  python scripts/segmented_verify.py --industry 人工智能 --step report      --runs 3

  # 一键全部
  python scripts/segmented_verify.py --industry 人工智能 --all --runs 3

设计：
  - Record 时拦截 Tavily + counter query LLM 调用，缓存到 checkpoint 旁
  - Replay 时从 checkpoint 注入上游数据，仅重跑目标 Agent，mock 写入
  - 每步对比指标不同（见 _compare_* 系列函数）
"""

import argparse
import copy
import json
import os
import re
import sys
import time
import yaml
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

# 确保 backend 在 path 中
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import requests as http_requests

# ═══════════════════════════════════════════════════
# 缓存层（类同 convergence_experiment）
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
    """缓存 VerifyAgent 的 LLM 生成反例搜索词（按 chain_label）。"""

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
# 指标提取
# ═══════════════════════════════════════════════════

def extract_hypothesize_metrics(hypotheses: list[dict], run_label: str) -> dict:
    """提取假设阶段的对比指标。"""
    return {
        "label": run_label,
        "count": len(hypotheses),
        "ids": sorted([h.get("id", "?") for h in hypotheses]),
        "id_set": set(h.get("id", "?") for h in hypotheses),
        "levels": Counter(h.get("chain_level") for h in hypotheses),
        "details": [
            {
                "id": h.get("id", "?"),
                "title": (h.get("title", "") or "")[:80],
                "level": h.get("chain_level"),
                "derives_from": h.get("derives_from", []),
                "statement": (h.get("statement", "") or "")[:200],
            }
            for h in hypotheses
        ],
    }


def extract_verify_metrics(verification: dict, run_label: str) -> dict:
    """提取验证阶段的对比指标。"""
    hyps = verification.get("hypotheses", [])
    statuses = verification.get("statuses", {})
    return {
        "label": run_label,
        "verified_count": verification.get("verified_count", len(hyps)),
        "statuses": dict(statuses),
        "details": [
            {
                "id": h.get("id", "?"),
                "status": h.get("status", "unverified"),
                "source_count": h.get("source_count"),
                "data_alignment": h.get("data_alignment", ""),
                "counter_conflict": h.get("counter_conflict", ""),
                "confidence": h.get("confidence", ""),
                "sentiment": h.get("sentiment", ""),
                "verified_sentiment": h.get("verified_sentiment", ""),
            }
            for h in hyps
        ],
    }


def extract_counter_metrics(cascaded: list[dict], run_label: str) -> dict:
    """提取 counter 阶段的对比指标。"""
    status_counter = Counter(h.get("status") for h in cascaded)
    sentiment_changes = sum(1 for h in cascaded if "original_sentiment" in h)
    return {
        "label": run_label,
        "total": len(cascaded),
        "statuses": dict(status_counter),
        "sentiment_changes": sentiment_changes,
        "details": [
            {
                "id": h.get("id", "?"),
                "status": h.get("status", "?"),
                "sentiment": h.get("sentiment", ""),
                "original_sentiment": h.get("original_sentiment", ""),
            }
            for h in cascaded
        ],
    }


def extract_screening_metrics(screening_result: dict, run_label: str) -> dict:
    """提取 screening 阶段的对比指标。"""
    pool = screening_result.get("stock_pool", [])
    return {
        "label": run_label,
        "pool_size": len(pool),
        "symbols": sorted([s.get("ts_code", s.get("symbol", "?")) for s in pool]),
        "ranks": {s.get("ts_code", s.get("symbol", "?")): s.get("rank")
                  for s in pool if s.get("rank")},
        "purity_scores": {
            s.get("ts_code", s.get("symbol", "?")): s.get("purity_score")
            for s in pool if s.get("purity_score") is not None
        },
    }


def extract_report_metrics(report_result: dict, run_label: str) -> dict:
    """提取 report 阶段的对比指标。"""
    return {
        "label": run_label,
        "rating": report_result.get("rating", "?"),
        "prosperity_level": report_result.get("prosperity_level", "?"),
        "signal_strength": report_result.get("signal_strength", 0),
        "stock_count": report_result.get("stock_count", 0),
    }


# ═══════════════════════════════════════════════════
# 差异对比
# ═══════════════════════════════════════════════════

def compare_metrics(all_metrics: list[dict]) -> dict:
    """对比多轮运行结果，返回差异摘要。"""
    if len(all_metrics) < 2:
        return {"identical": True, "differences": []}

    baseline = all_metrics[0]
    diffs = []

    for i, m in enumerate(all_metrics[1:], 1):
        run_diffs = {}

        # ID 集合对比（适用于 hypothesize / verify / counter）
        if "id_set" in baseline and "id_set" in m:
            only_baseline = baseline["id_set"] - m["id_set"]
            only_current = m["id_set"] - baseline["id_set"]
            if only_baseline or only_current:
                run_diffs["id_set"] = {
                    "only_in_run1": sorted(only_baseline),
                    "only_in_run" + str(i + 1): sorted(only_current),
                }

        if "ids" in baseline and "ids" in m:
            if baseline["ids"] != m["ids"]:
                run_diffs["ids_order"] = True

        # 数量
        if "count" in baseline and "count" in m:
            if baseline["count"] != m["count"]:
                run_diffs["count"] = f"{baseline['count']} → {m['count']}"

        # 状态分布
        if "statuses" in baseline and "statuses" in m:
            if baseline["statuses"] != m["statuses"]:
                run_diffs["statuses"] = f"{baseline['statuses']} → {m['statuses']}"

        # 股池
        if "pool_size" in baseline and "pool_size" in m:
            if baseline["pool_size"] != m["pool_size"]:
                run_diffs["pool_size"] = f"{baseline['pool_size']} → {m['pool_size']}"

        if "symbols" in baseline and "symbols" in m:
            b_set = set(baseline["symbols"])
            m_set = set(m["symbols"])
            only_b = b_set - m_set
            only_m = m_set - b_set
            if only_b or only_m:
                run_diffs["symbols"] = {
                    "only_in_run1": sorted(only_b),
                    "only_in_run" + str(i + 1): sorted(only_m),
                }

        # 评级
        if "rating" in baseline and "rating" in m:
            if baseline["rating"] != m["rating"]:
                run_diffs["rating"] = f"{baseline['rating']} → {m['rating']}"

        # 信号强度
        if "signal_strength" in baseline and "signal_strength" in m:
            diff = abs(baseline["signal_strength"] - m["signal_strength"])
            if diff > 0.01:
                run_diffs["signal_strength"] = (
                    f"{baseline['signal_strength']:.2f} → "
                    f"{m['signal_strength']:.2f} (Δ={diff:.2f})"
                )

        # Detail-level comparison
        if "details" in baseline and "details" in m:
            detail_diffs = _compare_details(
                baseline["details"], m["details"],
                label1="run1", label2=f"run{i+1}",
            )
            if detail_diffs:
                run_diffs["detail_diffs"] = detail_diffs

        if run_diffs:
            diffs.append({f"run1_vs_run{i+1}": run_diffs})

    return {
        "identical": len(diffs) == 0,
        "differences": diffs,
    }


def _compare_details(d1: list[dict], d2: list[dict],
                     label1: str, label2: str) -> list[dict]:
    """逐条对比 detail 记录。"""
    by_id_1 = {item["id"]: item for item in d1}
    by_id_2 = {item["id"]: item for item in d2}
    all_ids = set(by_id_1.keys()) | set(by_id_2.keys())
    detail_diffs = []

    for h_id in sorted(all_ids):
        item1 = by_id_1.get(h_id, {})
        item2 = by_id_2.get(h_id, {})
        item_diffs = {}

        for field in ["status", "source_count", "data_alignment",
                       "counter_conflict", "confidence", "sentiment",
                       "verified_sentiment", "title"]:
            v1 = item1.get(field)
            v2 = item2.get(field)
            if v1 != v2:
                item_diffs[field] = f"{v1} → {v2}"

        if item_diffs:
            detail_diffs.append({"id": h_id, **item_diffs})

    return detail_diffs


# ═══════════════════════════════════════════════════
# 回放环境
# ═══════════════════════════════════════════════════

class ReplayEnv:
    """回放环境：mock DB/write，注入缓存，提供干净 Agent 实例。"""

    def __init__(self, data_dir: Path, tavily_cache: TavilyCache,
                 counter_query_cache: CounterQueryCache):
        self.data_dir = data_dir
        self.tavily_cache = tavily_cache
        self.counter_query_cache = counter_query_cache

    def _intercept_tavily(self):
        """拦截所有 Tavily API 调用，走缓存。"""
        import requests as _requests
        original_post = _requests.post

        def patched_post(url, **kwargs):
            url_str = str(url) if not isinstance(url, str) else url
            if "api.tavily.com/search" in url_str:
                json_body = kwargs.get("json", {}) or {}
                query = json_body.get("query", "")
                depth = json_body.get("search_depth", "advanced")
                max_results = json_body.get("max_results", 10)

                cached = self.tavily_cache.get(query, depth, max_results)
                if cached is not None:
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.json.return_value = {"results": list(cached)}
                    return resp
                # 缓存未命中 → 真正调用并缓存
                resp = original_post(url, **kwargs)
                if resp.status_code == 200:
                    self.tavily_cache.set(
                        query, depth, max_results,
                        resp.json().get("results", []),
                    )
                return resp
            return original_post(url, **kwargs)

        return patch("requests.post", side_effect=patched_post)

    def _intercept_counter_queries(self):
        """拦截 VerifyAgent._generate_counter_queries，走缓存。"""
        from app.strategies.prosperity.agents.verify_agent import VerifyAgent
        original_gen = VerifyAgent._generate_counter_queries

        def patched_gen(self_agent, industry_name, chain, chain_label):
            cached = self.counter_query_cache.get(chain_label)
            if cached is not None:
                return list(cached)
            result = original_gen(self_agent, industry_name, chain, chain_label)
            self.counter_query_cache.set(chain_label, list(result))
            return result

        return patch.object(VerifyAgent, "_generate_counter_queries", new=patched_gen)

    def _mock_db(self):
        """Mock get_db_session 返回假 DB session。"""
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        mock_session.query.return_value.filter_by.return_value.all.return_value = []
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_session.query.return_value.order_by.return_value.all.return_value = []
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.flush = MagicMock()
        mock_session.close = MagicMock()

        mock_factory = MagicMock(return_value=mock_session)

        patches = [
            patch("app.strategies.prosperity.models.get_session", mock_factory),
            patch("app.strategies.prosperity.agents.hypothesize_agent.get_db_session", mock_factory),
            patch("app.strategies.prosperity.agents.verify_agent.get_db_session", mock_factory),
        ]
        return patches

    def _mock_file_writes(self):
        """Mock 磁盘文件写入方法。"""
        patches = [
            # wiki index + log
            patch("app.strategies.prosperity.agents.hypothesize_agent.update_index", MagicMock()),
            patch("app.strategies.prosperity.agents.hypothesize_agent.append_log", MagicMock()),
            patch("app.strategies.prosperity.agents.verify_agent.update_index", MagicMock()),
            patch("app.strategies.prosperity.agents.verify_agent.append_log", MagicMock()),
            patch("app.strategies.prosperity.agents.report_agent.update_index", MagicMock()),
            patch("app.strategies.prosperity.agents.report_agent.append_log", MagicMock()),
            patch("app.strategies.prosperity.agents.screening_agent.update_index", MagicMock()),
            patch("app.strategies.prosperity.agents.screening_agent.append_log", MagicMock()),
            # HypothesizeAgent: wiki + DB write
            patch("app.strategies.prosperity.agents.hypothesize_agent.HypothesizeAgent._persist_hypotheses",
                  MagicMock()),
            # VerifyAgent: wiki + DB write
            patch("app.strategies.prosperity.agents.verify_agent.VerifyAgent._update_hypothesis_pages",
                  MagicMock()),
            patch("app.strategies.prosperity.agents.verify_agent.VerifyAgent._update_db",
                  MagicMock()),
            # ReportAgent: synthesis report write
            patch("app.strategies.prosperity.agents.report_agent.ReportAgent._update_industry_page",
                  MagicMock()),
        ]
        return patches

    def all_mocks(self) -> list:
        """返回所有 mock 的 context manager 列表。"""
        return [
            self._intercept_tavily(),
            self._intercept_counter_queries(),
            *self._mock_db(),
            *self._mock_file_writes(),
        ]


# ═══════════════════════════════════════════════════
# Record — 全流程跑一次 + 存 checkpoint
# ═══════════════════════════════════════════════════

def record(industry_name: str, force: bool = False):
    """全流程跑一次，拦截 Tavily + counter query，存全部 checkpoint。"""
    from app.core.config import settings
    from app.strategies.prosperity.coordinator import Coordinator
    from app.strategies.prosperity.tools.checkpoint import CheckpointStore
    from app.strategies.prosperity.industry_history import IndustryHistory

    data_dir = Path(settings.PROSPERITY_DATA_DIR)
    ck = CheckpointStore(data_dir, industry_name)

    # 缓存文件
    cache_dir = ck.checkpoint_dir
    tavily_cache = TavilyCache(cache_dir / "_tavily_cache.yaml")
    counter_query_cache = CounterQueryCache(cache_dir / "_counter_queries_cache.yaml")
    tavily_cache.mode = "record"
    counter_query_cache.mode = "record"

    env = ReplayEnv(data_dir, tavily_cache, counter_query_cache)

    print(f"\n{'='*60}")
    print(f"  Record Mode: {industry_name}")
    print(f"{'='*60}")

    # 拦截 Tavily 和 counter query
    with env._intercept_tavily(), \
         env._intercept_counter_queries():

        coord = Coordinator()

        # Patch run_full_pipeline 在每一步后存 checkpoint
        original_full = coord.run_full_pipeline

        def patched_full(*args, **kwargs):
            # 我们手动执行步骤来插入 checkpoint 保存
            return _record_with_checkpoints(coord, industry_name, ck, tavily_cache, counter_query_cache, force)

        coord.run_full_pipeline = patched_full

        result = coord.run_full_pipeline(industry_name, force=force)
        status = result.get("status", "?")
        print(f"\n  Record: {status}")

    # 保存缓存
    tavily_cache.save()
    counter_query_cache.save()

    # 列出所有 checkpoint
    checkpoints = ck.list_checkpoints()
    print(f"  Checkpoints saved: {checkpoints}")
    print(f"  Tavily cache: {tavily_cache.hits + tavily_cache.misses} entries "
          f"({tavily_cache.hits} hits, {tavily_cache.misses} misses)")
    print(f"  Counter query cache: {len(counter_query_cache._data)} chain labels")


def _record_with_checkpoints(coord, industry_name, ck, tavily_cache, counter_query_cache, force):
    """逐步执行 pipeline 并在每步后存 checkpoint。"""
    import time as _time
    from app.strategies.prosperity.industry_history import IndustryHistory

    session_id = coord.start_session(industry_name, force=force)
    t_start = _time.time()

    print(f"\n>>> Prosperity Pipeline (Record): {industry_name} (session {session_id})")
    print(f"{'-'*60}")

    try:
        # Step 1: Search
        print("  [1/7] search...")
        coord.update_step(session_id, "search")
        search_result = coord._run_search_agent(industry_name, session_id)
        coord.pipeline_cache[session_id] = {"search": search_result}

        # 保存 search checkpoint
        ck.save("search", search_result=search_result)
        print(f"  [1/7] search done — {len(search_result.get('results', []))} results, checkpoint saved")

        # Step 1.5: Learn
        print("  [learn] building industry model...")
        coord.update_step(session_id, "learn")
        coord._run_learning_agent(industry_name, search_result)
        history = coord._load_history(industry_name, session_id)

        # 序列化 history 快照
        history_snapshot = {
            "industry_name": history.industry_name if history else industry_name,
            "study_count": history.study_count if history else 1,
            "last_rating": history.last_rating if history else "",
            "last_study_date": history.last_study_date.isoformat() if (history and history.last_study_date) else None,
            "cooldown_days": history.cooldown_days if history else 0,
            "previous_hypotheses": history.previous_hypotheses if history else [],
            "last_synthesis_excerpt": history.last_synthesis_excerpt if history else "",
            "rating_history": history.rating_history if history else [],
            "pending_tracking_items": history.pending_tracking_items if history else [],
        }

        # Step 2: Hypothesize
        print("  [2/7] hypothesize...")
        coord.update_step(session_id, "hypothesize")
        hypotheses = coord._run_hypothesize_agent(industry_name, session_id, search_result, history)
        coord.pipeline_cache[session_id]["hypotheses"] = hypotheses
        ck.save("hypothesize", hypotheses=hypotheses, history_snapshot=history_snapshot)
        print(f"  [2/7] hypothesize done — {len(hypotheses)} hypotheses, checkpoint saved")

        # Step 3: Verify
        print("  [3/7] verify...")
        coord.update_step(session_id, "verify")
        verification = coord._run_verify_agent(industry_name, session_id, hypotheses, search_result, history)
        coord.pipeline_cache[session_id]["verification"] = verification
        ck.save("verify", verification=verification, history_snapshot=history_snapshot)
        statuses = verification.get("statuses", {})
        print(f"  [3/7] verify done — {statuses}, checkpoint saved")

        # Step 3.5: Counter
        print("  [4/7] counter...")
        coord.update_step(session_id, "counter")
        verified_hypotheses = verification.get("hypotheses", [])
        cascade_result = coord._run_counter_agent(industry_name, session_id, verified_hypotheses)
        verification["hypotheses"] = cascade_result
        ck.save("counter", verified_hypotheses=cascade_result)
        cascade_statuses = Counter(h.get("status") for h in cascade_result)
        print(f"  [4/7] counter done — {dict(cascade_statuses)}, checkpoint saved")

        # Step 5 实际上: Screening
        print("  [5/7] screening...")
        coord.update_step(session_id, "screening")
        screening_result = coord._run_screening_agent(industry_name, session_id, verification, search_result, history)
        coord.pipeline_cache[session_id]["screening"] = screening_result
        ck.save("screening", screening_result=screening_result, history_snapshot=history_snapshot)
        print(f"  [5/7] screening done — {len(screening_result.get('stock_pool', []))} stocks, checkpoint saved")

        # Step 6: Report
        print("  [6/7] report...")
        coord.update_step(session_id, "report")
        report_result = coord._run_report_agent(industry_name, session_id, verification, screening_result, history)
        ck.save("report", report_result=report_result, history_snapshot=history_snapshot)
        print(f"  [6/7] report done — {report_result.get('rating', '?')}, checkpoint saved")

        # Track (bonus)
        print("  [7/7] track...")
        track_input = {**report_result, "hypotheses": verification.get("hypotheses", [])}
        report_result = coord._run_track_agent(industry_name, session_id, track_input)

        coord.update_step(session_id, "done")

        total_elapsed = _time.time() - t_start
        print(f"{'-'*60}")
        print(f"[OK] Record complete [{industry_name}]: elapsed={total_elapsed:.0f}s "
              f"({total_elapsed/60:.1f}min)")

        return {
            "session_id": session_id,
            "status": "completed",
            "industry": industry_name,
            "report": report_result,
        }

    except Exception as e:
        print(f"\n[FAIL] Record failed (session {session_id}): {e}")
        return {"session_id": session_id, "status": "failed", "error": str(e)}


# ═══════════════════════════════════════════════════
# Replay — 单步 N 次回放
# ═══════════════════════════════════════════════════

def replay_step(industry_name: str, step: str, runs: int = 3):
    """从 checkpoint 加载数据，仅重放目标步骤 N 次，对比结果。"""
    from app.core.config import settings
    from app.strategies.prosperity.tools.checkpoint import CheckpointStore
    from app.strategies.prosperity.industry_history import IndustryHistory

    data_dir = Path(settings.PROSPERITY_DATA_DIR)
    ck = CheckpointStore(data_dir, industry_name)

    # 检查 checkpoint 是否存在
    missing = ck.missing_dependencies(step)
    if missing:
        print(f"\n  [ERROR] Missing checkpoints for {step}: {missing}")
        print(f"  Run --record first.")
        return

    if step not in ("hypothesize", "verify", "counter", "screening", "report"):
        print(f"  [ERROR] Unknown step: {step}")
        return

    # 加载缓存
    cache_dir = ck.checkpoint_dir
    tavily_cache = TavilyCache(cache_dir / "_tavily_cache.yaml")
    counter_query_cache = CounterQueryCache(cache_dir / "_counter_queries_cache.yaml")
    tavily_cache.mode = "replay"
    counter_query_cache.mode = "replay"

    print(f"\n{'='*60}")
    print(f"  Replay: {industry_name} / {step} × {runs} runs")
    print(f"{'='*60}")

    # 从 checkpoint 重建 history
    history = _rebuild_history(ck, step)

    all_metrics = []

    for run_idx in range(runs):
        label = f"run{run_idx + 1}"
        print(f"\n  --- {label} ---")
        t0 = time.time()

        env = ReplayEnv(data_dir, tavily_cache, counter_query_cache)
        mocks = env.all_mocks()

        # 使用 ExitStack 管理多个 context manager
        from contextlib import ExitStack
        with ExitStack() as stack:
            for m in mocks:
                stack.enter_context(m)
            result = _run_single_step(industry_name, step, ck, history)

        elapsed = time.time() - t0
        all_metrics.append(result)
        print(f"  {label} done ({elapsed:.1f}s)")

    # 对比
    comparison = compare_metrics(all_metrics)

    # 输出结果
    print(f"\n{'='*60}")
    print(f"  Results: {step} × {runs} runs")
    print(f"{'='*60}")

    if comparison["identical"]:
        print(f"\n  [OK] ALL IDENTICAL — {runs} runs, no differences")
    else:
        print(f"\n  [WARN] DIFFERENCES FOUND ({len(comparison['differences'])} comparisons):")
        for diff_block in comparison["differences"]:
            for pair_label, diffs in diff_block.items():
                print(f"\n  {pair_label}:")
                for key, val in diffs.items():
                    if key == "detail_diffs":
                        print(f"    detail_diffs ({len(val)} items):")
                        for item in val:
                            item_id = item.pop("id", "?")
                            changes = ", ".join(f"{k}: {v}" for k, v in item.items())
                            print(f"      {item_id}: {changes}")
                    else:
                        print(f"    {key}: {val}")

    # 摘要
    _print_summary(all_metrics, step)

    return all_metrics, comparison


def _run_single_step(industry_name: str, step: str, ck, history=None):
    """执行单步并提取指标。"""
    if step == "hypothesize":
        return _replay_hypothesize(industry_name, ck, history)
    elif step == "verify":
        return _replay_verify(industry_name, ck, history)
    elif step == "counter":
        return _replay_counter(industry_name, ck)
    elif step == "screening":
        return _replay_screening(industry_name, ck, history)
    elif step == "report":
        return _replay_report(industry_name, ck, history)
    else:
        raise ValueError(f"Unknown step: {step}")


def _replay_hypothesize(industry_name: str, ck, history=None) -> dict:
    """回放 HypothesizeAgent。"""
    from app.core.config import settings
    from app.strategies.prosperity.agents.hypothesize_agent import HypothesizeAgent

    search_cp = ck.load_deepcopy("search")
    search_result = search_cp["search_result"]

    agent = HypothesizeAgent(
        data_dir=Path(settings.PROSPERITY_DATA_DIR),
        rules_dir=Path(settings.PROSPERITY_RULES_DIR),
    )
    hypotheses = agent.form_hypotheses(industry_name, 0, search_result, history)
    return extract_hypothesize_metrics(hypotheses, "replay")


def _replay_verify(industry_name: str, ck, history=None) -> dict:
    """回放 VerifyAgent。"""
    from app.core.config import settings
    from app.strategies.prosperity.agents.verify_agent import VerifyAgent

    hypo_cp = ck.load_deepcopy("hypothesize")
    search_cp = ck.load_deepcopy("search")
    hypotheses = hypo_cp["hypotheses"]
    search_result = search_cp["search_result"]

    agent = VerifyAgent(
        data_dir=Path(settings.PROSPERITY_DATA_DIR),
        rules_dir=Path(settings.PROSPERITY_RULES_DIR),
    )
    verification = agent.verify(industry_name, 0, hypotheses, search_result, history, skip_cascade=True)
    return extract_verify_metrics(verification, "replay")


def _replay_counter(industry_name: str, ck) -> dict:
    """回放 CounterAgent。"""
    from app.core.config import settings
    from app.strategies.prosperity.agents.counter_agent import CounterAgent

    verify_cp = ck.load_deepcopy("verify")
    verified_hypotheses = verify_cp["verification"]["hypotheses"]

    agent = CounterAgent(
        data_dir=Path(settings.PROSPERITY_DATA_DIR),
        rules_dir=Path(settings.PROSPERITY_RULES_DIR),
    )
    cascaded = agent.cascade(industry_name, 0, verified_hypotheses)
    return extract_counter_metrics(cascaded, "replay")


def _replay_screening(industry_name: str, ck, history=None) -> dict:
    """回放 ScreeningAgent。"""
    from app.core.config import settings
    from app.strategies.prosperity.agents.screening_agent import ScreeningAgent

    counter_cp = ck.load_deepcopy("counter")
    search_cp = ck.load_deepcopy("search")
    verified_hypotheses = counter_cp["verified_hypotheses"]
    search_result = search_cp["search_result"]

    # 重建 verification dict（counter 只存了 hypotheses）
    verification = {"hypotheses": verified_hypotheses}

    agent = ScreeningAgent(
        data_dir=Path(settings.PROSPERITY_DATA_DIR),
        rules_dir=Path(settings.PROSPERITY_RULES_DIR),
    )
    screening_result = agent.screen(industry_name, 0, verification, search_result, history)
    return extract_screening_metrics(screening_result, "replay")


def _replay_report(industry_name: str, ck, history=None) -> dict:
    """回放 ReportAgent。"""
    from app.core.config import settings
    from app.strategies.prosperity.agents.report_agent import ReportAgent

    counter_cp = ck.load_deepcopy("counter")
    screening_cp = ck.load_deepcopy("screening")
    verified_hypotheses = counter_cp["verified_hypotheses"]
    screening_result = screening_cp["screening_result"]

    verification = {"hypotheses": verified_hypotheses}
    study_count = 1

    agent = ReportAgent(data_dir=Path(settings.PROSPERITY_DATA_DIR))
    report_result = agent.generate(industry_name, 0, verification, screening_result, study_count)
    return extract_report_metrics(report_result, "replay")


def _rebuild_history(ck, target_step: str):
    """从 checkpoint 重建 IndustryHistory 对象。"""
    from datetime import datetime as dt
    from app.strategies.prosperity.industry_history import IndustryHistory

    # 从 hypothesize checkpoint 取 history_snapshot（所有 replay 共用）
    hypo_cp = ck.load_deepcopy("hypothesize")
    snap = hypo_cp.get("history_snapshot", {})
    if not snap:
        return None

    last_study_date = None
    if snap.get("last_study_date"):
        try:
            last_study_date = dt.fromisoformat(snap["last_study_date"])
        except (ValueError, TypeError):
            pass

    return IndustryHistory(
        industry_name=snap.get("industry_name", ""),
        study_count=snap.get("study_count", 1),
        last_rating=snap.get("last_rating", ""),
        last_study_date=last_study_date,
        cooldown_days=snap.get("cooldown_days", 0),
        previous_hypotheses=snap.get("previous_hypotheses", []),
        last_synthesis_excerpt=snap.get("last_synthesis_excerpt", ""),
        rating_history=snap.get("rating_history", []),
        pending_tracking_items=snap.get("pending_tracking_items", []),
    )


def _print_summary(all_metrics: list[dict], step: str):
    """打印摘要表。"""
    print(f"\n  Summary:")

    if step == "hypothesize":
        for m in all_metrics:
            print(f"    {m['label']}: {m['count']} hypotheses, ids={m['ids']}")

    elif step == "verify":
        for m in all_metrics:
            print(f"    {m['label']}: {m['statuses']}")

    elif step == "counter":
        for m in all_metrics:
            print(f"    {m['label']}: {m['statuses']}, sentiment_changes={m['sentiment_changes']}")

    elif step == "screening":
        for m in all_metrics:
            print(f"    {m['label']}: pool_size={m['pool_size']}, symbols={m['symbols']}")

    elif step == "report":
        for m in all_metrics:
            print(f"    {m['label']}: rating={m['rating']}, "
                  f"signal={m['signal_strength']:.2f}, "
                  f"stocks={m['stock_count']}")


# ═══════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════

ALL_STEPS = ["hypothesize", "verify", "counter", "screening", "report"]


def main():
    parser = argparse.ArgumentParser(
        description="分段验证：记录管道中间状态，仅重放目标步骤 N 次对比稳定性",
    )
    parser.add_argument("--industry", required=True, help="行业名称")
    parser.add_argument("--record", action="store_true", help="全流程记录模式（存全部 checkpoint）")
    parser.add_argument("--step", choices=ALL_STEPS, help="仅验证指定步骤")
    parser.add_argument("--all", action="store_true", help="验证全部 5 步")
    parser.add_argument("--runs", type=int, default=3, help="回放次数（默认 3）")
    parser.add_argument("--force", action="store_true", help="跳过 5 天冷却期")
    parser.add_argument("--output", type=str, help="结果输出 JSON 文件路径（可选）")
    args = parser.parse_args()

    if args.record:
        record(args.industry, force=args.force)
        return

    if args.all:
        all_results = {}
        all_comparisons = {}
        for step in ALL_STEPS:
            metrics, comparison = replay_step(args.industry, step, args.runs)
            all_results[step] = metrics
            all_comparisons[step] = comparison

        # 总览
        print(f"\n{'='*60}")
        print(f"  OVERALL: {len(ALL_STEPS)} steps × {args.runs} runs")
        print(f"{'='*60}")
        identical_count = sum(1 for c in all_comparisons.values() if c["identical"])
        print(f"  Identical: {identical_count}/{len(ALL_STEPS)} steps")
        for step, comp in all_comparisons.items():
            status = "[OK] IDENTICAL" if comp["identical"] else "[WARN] DIFFS"
            print(f"    {step}: {status}")

        if args.output:
            output = {
                "industry": args.industry,
                "runs": args.runs,
                "timestamp": datetime.now().isoformat(),
                "results": {step: {"metrics": m, "comparison": c}
                            for step, (m, c) in zip(ALL_STEPS,
                                                    [(all_results[s], all_comparisons[s])
                                                     for s in ALL_STEPS])},
            }
            with open(args.output, "w", encoding="utf-8") as f:
                yaml.dump(output, f, allow_unicode=True, default_flow_style=False)
            print(f"\n  Results saved to {args.output}")
        return

    if args.step:
        metrics, comparison = replay_step(args.industry, args.step, args.runs)
        if args.output:
            output = {
                "industry": args.industry,
                "step": args.step,
                "runs": args.runs,
                "timestamp": datetime.now().isoformat(),
                "metrics": metrics,
                "comparison": comparison,
            }
            with open(args.output, "w", encoding="utf-8") as f:
                yaml.dump(output, f, allow_unicode=True, default_flow_style=False)
            print(f"\n  Results saved to {args.output}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
