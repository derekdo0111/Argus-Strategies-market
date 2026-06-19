# -*- coding: utf-8 -*-
"""Single stock full pipeline (compute -> qrv_input -> websearch -> QRV)
Usage: python scripts/run_single_stock_analysis.py 600900.SH [--force]
"""
import asyncio
import sys
import yaml
from pathlib import Path

# v0.5.2: 修复 Windows GBK emoji 编码问题
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import settings
from app.services.data_fetcher import DataFetcher
from app.services.qrv_agent import QRVAgent
from app.strategies.turtle.cash_quality import CashQualityGate
from app.strategies.turtle.penetration_return import PenetrationReturnCalculator
from app.strategies.turtle.utils import find_stock_dir


async def main():
    ts_code = sys.argv[1] if len(sys.argv) > 1 else "600900.SH"
    force = "--force" in sys.argv or "--full" in sys.argv  # v0.5.2: 支持强制重拉
    force_websearch = "--force-websearch" in sys.argv  # v0.6.0: 跳过 WebSearch 缓存
    print(f"\n{'='*60}")
    print(f"[START] Single stock analysis: {ts_code} {'(force)' if force else ''}")
    print(f"{'='*60}\n", flush=True)

    cache_dir = settings.STOCK_CACHE_DIR

    # v0.5.2: 先查股票名称，确保创建 {name}_{ts_code} 目录（而非纯代码目录）
    print("[0/5] Getting stock name...", flush=True)
    from app.services.tushare_client import TushareClient
    tc = TushareClient()
    stock_name = ""
    try:
        basic = tc.call("stock_basic", ts_code=ts_code, fields="ts_code,name")
        if not basic.empty:
            stock_name = str(basic.iloc[0].get("name", ""))
    except Exception:
        print(f"      [WARN] Cannot fetch stock name for {ts_code}, using code as name", flush=True)
    if not stock_name:
        stock_name = ts_code
    print(f"      Name: {stock_name}", flush=True)

    # Step 1: Fetch data (with name_map to use {name}_{ts_code} dir)
    print("[1/5] Fetching financial data from Tushare...", flush=True)
    fetcher = DataFetcher(cache_dir=cache_dir)
    stats = fetcher.fetch_candidate_data([ts_code], force=force, name_map={ts_code: stock_name})
    print(f"      Result: success={stats.success}, failed={stats.failed}", flush=True)
    if stats.failed > 0:
        print(f"      FAILED: {stats.failed_codes}")
        return

    # Find stock dir
    stock_dir = find_stock_dir(cache_dir, ts_code)
    if stock_dir is None:
        print("      FAILED: Could not find stock cache directory")
        return

    raw_path = stock_dir / "raw_data.yaml"
    if not raw_path.exists():
        print("      FAILED: raw_data.yaml not found")
        return

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)
    name = raw_data.get("meta", {}).get("name", ts_code)
    print(f"      Stock: {name} ({ts_code})", flush=True)

    # Step 2: Direct compute CQ + PR (bypass screener)
    print("\n[2/5] Computing CQ + PR directly...", flush=True)
    safe_name = name.replace("/", "-").replace("\\", "-")

    # Cash Quality
    cq_gate = CashQualityGate(rule_version="v2")
    cq_result = cq_gate.compute(raw_data)
    print(f"      CQ: {'PASS' if cq_result.overall_passed else 'FAIL'} (dim fails: {cq_result.failed_dimensions})", flush=True)

    # PR
    risk_free = float(getattr(settings, "TURTLE_RISK_FREE_RATE", 1.7))
    spread_val = float(getattr(settings, "TURTLE_SPREAD", 1.0))
    pr_calc = PenetrationReturnCalculator(risk_free_rate=risk_free, spread=spread_val)
    pr_result = pr_calc.compute(raw_data)
    print(f"      PR: {pr_result.pr:.2f}% (threshold {risk_free + spread_val:.1f}%, CV={pr_result.disposable_cash_cv:.3f}) {'PASS' if pr_result.passed else 'FAIL'}", flush=True)

    # Write computed.yaml — v0.5.2: 写入 stock_dir (与 raw_data.yaml 同目录), 修复双文件夹 Bug
    computed_data = {
        "meta": {"ts_code": ts_code, "name": name, "rule_version": "v2"},
        "cash_quality": cq_gate.to_computed_format(cq_result),
        "penetration_return": pr_calc.to_computed_format(pr_result),
    }
    computed_path = stock_dir / "computed.yaml"
    with open(computed_path, "w", encoding="utf-8") as f:
        yaml.dump(computed_data, f, allow_unicode=True, default_flow_style=False)
    print(f"      computed.yaml written to: {computed_path}", flush=True)

    # Step 3: Build qrv_input using coordinator
    print("\n[3/5] Building unified data package (qrv_input.yaml)...", flush=True)
    from app.strategies.turtle.coordinator import TurtleCoordinator
    coordinator = TurtleCoordinator(cache_dir=cache_dir, risk_free_rate=risk_free)
    qrv_input_path = await coordinator._build_qrv_input(ts_code)
    if qrv_input_path is None:
        print("      FAILED: data package build failed")
        return
    print(f"      OK: {qrv_input_path}", flush=True)

    # Step 4: WebSearch
    print("\n[4/5] WebSearch (5 Tavily searches)...", flush=True)
    websearch_data = await coordinator._run_websearch(ts_code, qrv_input_path,
                                                        force=force_websearch)
    coordinator._append_websearch_to_qrv_input(qrv_input_path, websearch_data)
    ws_total = sum(len(v.get("snippets", [])) for v in websearch_data.values() if isinstance(v, dict))
    ws_modules = sum(1 for v in websearch_data.values() if isinstance(v, dict) and v.get("snippets"))
    print(f"      OK: {ws_modules}/5 modules returned results, {ws_total} snippets total", flush=True)
    for k, v in websearch_data.items():
        if isinstance(v, dict):
            print(f"        {k}: {len(v.get('snippets', []))} snippets ({v.get('confidence', 'N/A')})")

    # Step 5: QRV Agent
    print("\n[5/5] QRV Agent analysis (LLM call)...", flush=True)
    qrv = QRVAgent(cache_dir=cache_dir)
    result = await qrv.analyze_async(ts_code)

    if "error" in result:
        print(f"      FAILED: {result['error']}")
    else:
        print(f"\n{'='*60}")
        print(f"DONE. Tokens used: {result.get('tokens', 0)}")
        print(f"Markdown: {result['qrv_analysis_md']}")
        print(f"JSON:     {result['qrv_analysis_json']}")

        # TODO v0.6.0: HTML 渲染（markdown → 带样式的 HTML 报告）
        # qrv_html_path = stock_dir / "qrv_analysis.html"

        print(f"{'='*60}\n", flush=True)

        # Preview first 80 lines
        print("=== REPORT PREVIEW (first 80 lines) ===")
        with open(result["qrv_analysis_md"], "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 80:
                    print("... (truncated)")
                    break
                print(line, end="")


if __name__ == "__main__":
    asyncio.run(main())
