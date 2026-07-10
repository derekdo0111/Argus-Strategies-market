"""
稳定性对比脚本 —— 同一行业跑两遍，对比关键数字

用法:
    cd "d:\project\Investment Strategy"
    python scripts/stability_compare.py [行业名] [选项]

    python scripts/stability_compare.py              # 默认: 人工智能
    python scripts/stability_compare.py 可控核聚变    # 指定行业
    python scripts/stability_compare.py --no-run     # 只比较已有备份，不跑管道

输出:
    - data/prosperity/raw/{行业}/stock_pool_run1.yaml  (备份)
    - data/prosperity/raw/{行业}/stock_pool_run2.yaml  (备份)
    - data/prosperity/raw/{行业}/run{n}_output.txt      (管道输出日志)
    - data/prosperity/raw/{行业}/stability_report.md    (对比报告)
"""

import io
import sys
import os
import re
import shutil
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional

# Windows 编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ----- 配置 -----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "prosperity" / "raw"

# ----- 日志输出捕获 -----
class TeeOutput:
    """同时输出到 stdout 和内存缓冲区"""

    def __init__(self):
        self.buffer = io.StringIO()
        self._original_stdout = None

    def __enter__(self):
        import builtins
        self._original_print = builtins.print

        def _tee_print(*args, **kwargs):
            # 写入原始 stdout
            self._original_print(*args, **kwargs)
            # 写入缓冲区
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            self.buffer.write(sep.join(str(a) for a in args) + end)

        builtins.print = _tee_print
        return self

    def __exit__(self, *args):
        import builtins
        builtins.print = self._original_print

    def getvalue(self):
        return self.buffer.getvalue()


# ----- 指标提取 -----
def extract_metrics(output_text: str) -> dict:
    """从管道输出中提取关键指标"""
    metrics = {}

    # 验证状态: confirmed=X partial=Y disputed=Z unverified=W
    m = re.search(
        r"confirmed=(\d+)\s+partial=(\d+)\s+disputed=(\d+)\s+unverified=(\d+)",
        output_text,
    )
    if m:
        metrics["verify_confirmed"] = int(m.group(1))
        metrics["verify_partial"] = int(m.group(2))
        metrics["verify_disputed"] = int(m.group(3))
        metrics["verify_unverified"] = int(m.group(4))

    # Counter: overturned=X unreachable=Y
    m2 = re.search(
        r"overturned=(\d+)\s+unreachable=(\d+)",
        output_text,
    )
    if m2:
        metrics["counter_overturned"] = int(m2.group(1))
        metrics["counter_unreachable"] = int(m2.group(2))

    # Screening: stock pool: N stocks
    m3 = re.search(r"stock pool:\s*(\d+)\s*stocks", output_text)
    if m3:
        metrics["stock_pool_size"] = int(m3.group(1))

    # 假设数: N hypotheses generated
    m4 = re.search(r"(\d+)\s*hypotheses generated", output_text)
    if m4:
        metrics["hypothesis_count"] = int(m4.group(1))

    # 总耗时
    m5 = re.search(r"elapsed=(\d+)s\s*\(([\d.]+)min\)", output_text)
    if m5:
        metrics["elapsed_seconds"] = int(m5.group(1))
        metrics["elapsed_minutes"] = float(m5.group(2))

    # Rating
    m6 = re.search(r"rating=(\S+)", output_text)
    if m6:
        metrics["rating"] = m6.group(1).strip()

    return metrics


# ----- Stock Pool 对比 -----
def compare_stock_pools(pool1_path: Path, pool2_path: Path) -> dict:
    """对比两次 stock_pool.yaml"""
    import yaml

    with open(pool1_path, encoding="utf-8") as f:
        pool1 = yaml.safe_load(f)
    with open(pool2_path, encoding="utf-8") as f:
        pool2 = yaml.safe_load(f)

    # 以 ts_code 为 key
    s1 = {s["ts_code"]: s for s in pool1} if pool1 else {}
    s2 = {s["ts_code"]: s for s in pool2} if pool2 else {}

    all_codes = set(s1.keys()) | set(s2.keys())
    only_in_1 = set(s1.keys()) - set(s2.keys())
    only_in_2 = set(s2.keys()) - set(s1.keys())

    # 纯度分差异
    purity_diffs = []
    for ts in all_codes:
        p1 = s1.get(ts, {}).get("purity_score", 0)
        p2 = s2.get(ts, {}).get("purity_score", 0)
        diff = abs(p1 - p2)
        if diff > 0.0001:
            purity_diffs.append({
                "ts_code": ts,
                "name": s1.get(ts, s2.get(ts, {})).get("name", "?"),
                "run1_purity": p1,
                "run2_purity": p2,
                "diff": diff,
            })

    # 排名变化
    rank_changes = []
    for ts in all_codes:
        r1 = s1.get(ts, {}).get("rank", None)
        r2 = s2.get(ts, {}).get("rank", None)
        if r1 is not None and r2 is not None and r1 != r2:
            rank_changes.append({
                "ts_code": ts,
                "name": s1.get(ts, s2.get(ts, {})).get("name", "?"),
                "run1_rank": r1,
                "run2_rank": r2,
                "delta": r2 - r1,
            })

    return {
        "pool1_size": len(pool1),
        "pool2_size": len(pool2),
        "common_stocks": len(all_codes) - len(only_in_1) - len(only_in_2),
        "only_in_run1": [{"ts_code": ts, "name": s1[ts].get("name", "?")} for ts in only_in_1],
        "only_in_run2": [{"ts_code": ts, "name": s2[ts].get("name", "?")} for ts in only_in_2],
        "purity_diffs": sorted(purity_diffs, key=lambda x: x["diff"], reverse=True),
        "rank_changes": sorted(rank_changes, key=lambda x: abs(x["delta"]), reverse=True),
        "raw_pool1": s1,
        "raw_pool2": s2,
    }


# ----- 报告生成 -----
def generate_report(
    industry: str,
    run1_metrics: dict,
    run2_metrics: dict,
    pool_comparison: dict,
    run1_output_file: Path,
    run2_output_file: Path,
) -> str:
    """生成 Markdown 格式的稳定性报告"""

    def metric_row(label: str, key: str, fmt: str = "d"):
        v1 = run1_metrics.get(key, "?")
        v2 = run2_metrics.get(key, "?")
        match = "✅" if v1 == v2 else "❌"
        if fmt == ".4f":
            s1 = f"{v1:.4f}" if isinstance(v1, (int, float)) else str(v1)
            s2 = f"{v2:.4f}" if isinstance(v2, (int, float)) else str(v2)
        elif fmt == ".2f":
            s1 = f"{v1:.2f}" if isinstance(v1, (int, float)) else str(v1)
            s2 = f"{v2:.2f}" if isinstance(v2, (int, float)) else str(v2)
        else:
            s1 = str(v1)
            s2 = str(v2)
        return f"| {label} | {s1} | {s2} | {match} |"

    # ----- 稳定性评分 -----
    score = 100
    deductions = []

    if run1_metrics.get("verify_confirmed") != run2_metrics.get("verify_confirmed"):
        score -= 20
        deductions.append("验证 confirmed 数不一致 (-20)")
    if run1_metrics.get("verify_partial") != run2_metrics.get("verify_partial"):
        score -= 15
        deductions.append("验证 partial 数不一致 (-15)")
    if run1_metrics.get("verify_disputed") != run2_metrics.get("verify_disputed"):
        score -= 10
        deductions.append("验证 disputed 数不一致 (-10)")
    if run1_metrics.get("stock_pool_size") != run2_metrics.get("stock_pool_size"):
        score -= 10
        deductions.append("股池大小不一致 (-10)")

    n_purity_diff = len(pool_comparison.get("purity_diffs", []))
    n_rank_change = len(pool_comparison.get("rank_changes", []))
    if n_purity_diff > 0:
        d = min(n_purity_diff * 5, 20)
        score -= d
        deductions.append(f"{n_purity_diff} 只股票纯度分不一致 (-{d})")
    if n_rank_change > 0:
        d = min(n_rank_change * 3, 15)
        score -= d
        deductions.append(f"{n_rank_change} 只股票排名变化 (-{d})")

    rating = "优秀" if score >= 90 else ("良好" if score >= 75 else ("一般" if score >= 60 else "差"))
    rating_emoji = "🟢" if score >= 90 else ("🟡" if score >= 75 else ("🟠" if score >= 60 else "🔴"))

    # ----- 组装报告 -----
    lines = []
    lines.append(f"# {industry} — 稳定性对比报告")
    lines.append(f"")
    lines.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 版本: v0.11.0 / 确定性验证已实现 + 关键词纯度分")
    lines.append(f"")
    lines.append(f"## {rating_emoji} 综合评分: {score}/100 — {rating}")
    lines.append(f"")
    if deductions:
        for d in deductions:
            lines.append(f"- {d}")
    else:
        lines.append(f"- ✅ 两次运行完全一致！")
    lines.append(f"")

    # ---- 管道指标对比 ----
    lines.append(f"## 📊 管道指标对比")
    lines.append(f"")
    lines.append(f"| 指标 | Run 1 | Run 2 | 一致? |")
    lines.append(f"|------|-------|-------|-------|")
    lines.append(metric_row("假设数", "hypothesis_count"))
    lines.append(metric_row("验证 confirmed", "verify_confirmed"))
    lines.append(metric_row("验证 partial", "verify_partial"))
    lines.append(metric_row("验证 disputed", "verify_disputed"))
    lines.append(metric_row("验证 unverified", "verify_unverified"))
    lines.append(metric_row("Counter overturned", "counter_overturned"))
    lines.append(metric_row("Counter unreachable", "counter_unreachable"))
    lines.append(metric_row("股池大小", "stock_pool_size"))
    lines.append(metric_row("耗时(秒)", "elapsed_seconds"))
    lines.append(metric_row("耗时(分)", "elapsed_minutes", ".2f"))
    lines.append(f"| 评级 | {run1_metrics.get('rating', '?')} | {run2_metrics.get('rating', '?')} | {'✅' if run1_metrics.get('rating') == run2_metrics.get('rating') else '❌'} |")
    lines.append(f"")

    # ---- 股池对比 ----
    lines.append(f"## 📈 股池对比")
    lines.append(f"")
    lines.append(f"| 维度 | Run 1 | Run 2 |")
    lines.append(f"|------|-------|-------|")
    lines.append(f"| 股票数 | {pool_comparison['pool1_size']} | {pool_comparison['pool2_size']} |")
    lines.append(f"| 共同股票 | {pool_comparison['common_stocks']} | {pool_comparison['common_stocks']} |")
    only1 = pool_comparison.get("only_in_run1", [])
    only2 = pool_comparison.get("only_in_run2", [])
    lines.append(f"| 仅 Run1 有 | {len(only1)} | — |")
    lines.append(f"| 仅 Run2 有 | — | {len(only2)} |")
    lines.append(f"")

    if only1:
        lines.append(f"**仅在 Run 1 出现的股票**:")
        for s in only1:
            lines.append(f"- {s['ts_code']} ({s['name']})")
        lines.append(f"")
    if only2:
        lines.append(f"**仅在 Run 2 出现的股票**:")
        for s in only2:
            lines.append(f"- {s['ts_code']} ({s['name']})")
        lines.append(f"")

    # ---- 纯度分差异 ----
    purity_diffs = pool_comparison.get("purity_diffs", [])
    if purity_diffs:
        lines.append(f"## 🔬 纯度分差异 (差异 > 0.01%)")
        lines.append(f"")
        lines.append(f"共 **{len(purity_diffs)}** 只股票纯度分不一致")
        lines.append(f"")
        lines.append(f"| 股票 | Run1 纯度 | Run2 纯度 | 差异 |")
        lines.append(f"|------|-----------|-----------|------|")
        for d in purity_diffs[:30]:
            lines.append(f"| {d['ts_code']} ({d['name']}) | {d['run1_purity']:.4f} | {d['run2_purity']:.4f} | {d['diff']:.4f} |")
        if len(purity_diffs) > 30:
            lines.append(f"| ... | ... | ... | ... |")
            lines.append(f"| *(共 {len(purity_diffs)} 条，仅显示前 30)* | | | |")
        lines.append(f"")

    # ---- 排名变化 ----
    rank_changes = pool_comparison.get("rank_changes", [])
    if rank_changes:
        lines.append(f"## 🔄 排名变化")
        lines.append(f"")
        lines.append(f"共 **{len(rank_changes)}** 只股票排名变化")
        lines.append(f"")
        lines.append(f"| 股票 | Run1 排名 | Run2 排名 | Δ |")
        lines.append(f"|------|-----------|-----------|---|")
        for r in rank_changes[:30]:
            direction = "↑" if r["delta"] < 0 else "↓"
            lines.append(f"| {r['ts_code']} ({r['name']}) | #{r['run1_rank']} | #{r['run2_rank']} | {direction}{abs(r['delta'])} |")
        if len(rank_changes) > 30:
            lines.append(f"| ... | ... | ... | ... |")
        lines.append(f"")

    # ---- 一致性检查 ----
    lines.append(f"## 🎯 一致性检查")
    lines.append(f"")

    # 验证状态一致性
    vr = all([
        run1_metrics.get("verify_confirmed") == run2_metrics.get("verify_confirmed"),
        run1_metrics.get("verify_partial") == run2_metrics.get("verify_partial"),
        run1_metrics.get("verify_disputed") == run2_metrics.get("verify_disputed"),
        run1_metrics.get("verify_unverified") == run2_metrics.get("verify_unverified"),
    ])
    lines.append(f"- {'✅' if vr else '❌'} 验证状态分布: {'一致' if vr else '不一致'}")

    hs = run1_metrics.get("hypothesis_count") == run2_metrics.get("hypothesis_count")
    lines.append(f"- {'✅' if hs else '❌'} 假设数: {'一致' if hs else '不一致'}")

    sp = run1_metrics.get("stock_pool_size") == run2_metrics.get("stock_pool_size")
    lines.append(f"- {'✅' if sp else '❌'} 股池大小: {'一致' if sp else '不一致'}")

    same = len(purity_diffs) == 0
    lines.append(f"- {'✅' if same else '❌'} 纯度分: {'完全一致' if same else f'{len(purity_diffs)} 只有差异'}")

    lines.append(f"")

    # ---- 关键发现 ----
    lines.append(f"## 💡 关键发现")
    lines.append(f"")

    if score == 100:
        lines.append(f"**完美稳定！** 两次运行结果完全一致。")
        lines.append(f"")
        lines.append(f"确定性验证 + 关键词纯度分的改造达到了预期效果：")
        lines.append(f"- 验证状态的 `_synthesize_status()` 确定性规则确保了 `confirmed/partial/disputed` 分布不漂移")
        lines.append(f"- 纯度分的关键词匹配 (`match_business_to_l3`) 确保了同样输入永远同样输出")
    elif score >= 75:
        lines.append(f"**基本稳定**，但有轻微漂移。")
        lines.append(f"")
        if not vr:
            lines.append(f"- 验证状态有变化 → 可能 `source_count`/`data_alignment` 的 LLM 原子判断仍有波动")
        if not same:
            lines.append(f"- 纯度分有差异 → 可能触发了 LLM 回退匹配（关键词零匹配时）")
    else:
        lines.append(f"**显著不稳定**，需要进一步排查。")
        lines.append(f"")
        lines.append(f"可能原因：")
        lines.append(f"- Search (Tavily) 结果变化 → 假设不同 → 验证结果不同")
        lines.append(f"- Hypothesize LLM 输出波动 → 后续所有步骤受波及")
        lines.append(f"- 关键词提取受假设文本影响 → 纯度分间接受影响")

    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"### 文件清单")
    lines.append(f"")
    lines.append(f"| 文件 | 内容 |")
    lines.append(f"|------|------|")
    lines.append(f"| `data/prosperity/raw/{industry}/run1_output.txt` | Run 1 管道完整输出 |")
    lines.append(f"| `data/prosperity/raw/{industry}/run2_output.txt` | Run 2 管道完整输出 |")
    lines.append(f"| `data/prosperity/raw/{industry}/stock_pool_run1.yaml` | Run 1 股池 |")
    lines.append(f"| `data/prosperity/raw/{industry}/stock_pool_run2.yaml` | Run 2 股池 |")
    lines.append(f"| `data/prosperity/raw/{industry}/stability_report.md` | 本报告 |")

    return "\n".join(lines)


# ----- 主流程 -----
def run_pipeline(industry: str) -> tuple[Optional[str], Optional[dict]]:
    """运行管道并返回输出文本 + 指标。失败返回 None。"""
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

    import logging
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # 抑制 httpx 日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    from app.strategies.prosperity.coordinator import Coordinator

    print(f"\n{'=' * 60}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始运行: {industry}")
    print(f"{'=' * 60}\n")

    tee = TeeOutput()
    with tee:
        try:
            c = Coordinator()
            result = c.run_full_pipeline(industry, force=True)
        except Exception as e:
            print(f"\n[FAIL] 管道异常: {e}")
            return tee.getvalue(), None

    output = tee.getvalue()
    metrics = extract_metrics(output)

    if result.get("status") == "completed":
        print(f"\n[OK] 管道完成: {industry}")
        return output, metrics
    else:
        print(f"\n[FAIL] 管道失败: {result.get('error', 'unknown')}")
        return output, None


def backup_stock_pool(industry: str, run_label: str) -> Optional[Path]:
    """备份 stock_pool.yaml"""
    src = DATA_DIR / industry / "stock_pool.yaml"
    dst = DATA_DIR / industry / f"stock_pool_{run_label}.yaml"

    if not src.exists():
        print(f"[WARN] stock_pool.yaml 不存在: {src}")
        return None

    shutil.copy2(src, dst)
    print(f"[BACKUP] {src.name} → {dst.name}")
    return dst


def save_output(output: str, industry: str, run_label: str) -> Path:
    """保存管道输出日志"""
    dst = DATA_DIR / industry / f"{run_label}_output.txt"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(output, encoding="utf-8")
    print(f"[SAVE] 输出日志 → {dst.name} ({len(output)} 字符)")
    return dst


def main():
    parser = argparse.ArgumentParser(description="高景气策略稳定性对比")
    parser.add_argument(
        "industry", nargs="?", default="人工智能",
        help="行业名称 (默认: 人工智能)",
    )
    parser.add_argument(
        "--no-run", action="store_true",
        help="不跑管道，只对比已有备份 (stock_pool_run1.yaml / run2.yaml)",
    )
    parser.add_argument(
        "-o", "--output", default=None,
        help="报告输出路径 (默认: data/prosperity/raw/{行业}/stability_report.md)",
    )
    args = parser.parse_args()

    industry = args.industry
    industry_dir = DATA_DIR / industry
    industry_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'#' * 60}")
    print(f"# 稳定性对比: {industry}")
    print(f"{'#' * 60}")

    if args.no_run:
        print("\n[SKIP] --no-run 模式: 跳过管道，直接对比已有备份\n")
    else:
        # ===== Run 1 =====
        print(f"\n>>> Run 1 / 2 <<<\n")
        output1, metrics1 = run_pipeline(industry)

        if output1:
            save_output(output1, industry, "run1")
            backup_stock_pool(industry, "run1")
            if metrics1:
                print(f"\n[Run 1 指标] {metrics1}")
            else:
                print(f"\n[WARN] Run 1 指标提取失败")
        else:
            print("[FATAL] Run 1 失败，无法继续")
            return

        print(f"\n{'~' * 40}")
        print(f"等待 5 秒后开始 Run 2...")
        time.sleep(5)

        # ===== Run 2 =====
        print(f"\n>>> Run 2 / 2 <<<\n")
        output2, metrics2 = run_pipeline(industry)

        if output2:
            save_output(output2, industry, "run2")
            backup_stock_pool(industry, "run2")
            if metrics2:
                print(f"\n[Run 2 指标] {metrics2}")
            else:
                print(f"\n[WARN] Run 2 指标提取失败")
        else:
            print("[FATAL] Run 2 失败，无法完整对比")
            return

    # ===== 读取已有的输出日志提取指标 =====
    if args.no_run:
        run1_output_file = industry_dir / "run1_output.txt"
        run2_output_file = industry_dir / "run2_output.txt"

        if not run1_output_file.exists() or not run2_output_file.exists():
            print("[FATAL] 输出日志不存在，请先不带 --no-run 运行")
            print(f"  需要: {run1_output_file}")
            print(f"  需要: {run2_output_file}")
            return

        output1 = run1_output_file.read_text(encoding="utf-8")
        output2 = run2_output_file.read_text(encoding="utf-8")
        metrics1 = extract_metrics(output1)
        metrics2 = extract_metrics(output2)
    else:
        run1_output_file = industry_dir / "run1_output.txt"
        run2_output_file = industry_dir / "run2_output.txt"

    # ===== 对比 stock_pool =====
    pool1_path = industry_dir / "stock_pool_run1.yaml"
    pool2_path = industry_dir / "stock_pool_run2.yaml"

    if pool1_path.exists() and pool2_path.exists():
        pool_comparison = compare_stock_pools(pool1_path, pool2_path)
    else:
        print(f"[WARN] 股票池备份不全，跳过股池对比")
        print(f"  Run1: {'✅' if pool1_path.exists() else '❌'} {pool1_path}")
        print(f"  Run2: {'✅' if pool2_path.exists() else '❌'} {pool2_path}")
        pool_comparison = {
            "pool1_size": "?", "pool2_size": "?",
            "common_stocks": "?", "only_in_run1": [],
            "only_in_run2": [], "purity_diffs": [], "rank_changes": [],
            "raw_pool1": {}, "raw_pool2": {},
        }

    # ===== 生成报告 =====
    report = generate_report(
        industry=industry,
        run1_metrics=metrics1,
        run2_metrics=metrics2,
        pool_comparison=pool_comparison,
        run1_output_file=run1_output_file,
        run2_output_file=run2_output_file,
    )

    report_path = Path(args.output) if args.output else (industry_dir / "stability_report.md")
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"[OK] 报告已保存: {report_path}")
    print(f"{'=' * 60}")

    # 打印摘要
    print(f"\n--- 摘要 ---")
    if metrics1 and metrics2:
        print(f"  假设数:    Run1={metrics1.get('hypothesis_count','?')}  Run2={metrics2.get('hypothesis_count','?')}")
        print(f"  confirmed: Run1={metrics1.get('verify_confirmed','?')}  Run2={metrics2.get('verify_confirmed','?')}")
        print(f"  partial:   Run1={metrics1.get('verify_partial','?')}  Run2={metrics2.get('verify_partial','?')}")
        print(f"  disputed:  Run1={metrics1.get('verify_disputed','?')}  Run2={metrics2.get('verify_disputed','?')}")
        print(f"  股池大小:  Run1={metrics1.get('stock_pool_size','?')}  Run2={metrics2.get('stock_pool_size','?')}")

    n_diff = len(pool_comparison.get("purity_diffs", []))
    n_rank = len(pool_comparison.get("rank_changes", []))
    print(f"  纯度分差异: {n_diff} 只")
    print(f"  排名变化:   {n_rank} 只")
    print()


if __name__ == "__main__":
    main()
