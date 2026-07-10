import sys, os
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "backend")

import logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from app.strategies.prosperity.coordinator import Coordinator

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 启动 人工智能 全链路分析...")
print("=" * 60)

c = Coordinator()
result = c.run_full_pipeline("人工智能", force=True)

print(f"\n{'=' * 60}")
print(f"结果: status={result.get('status')}, session_id={result.get('session_id')}")

if result.get("status") == "completed":
    report = result.get("report", {})
    print(f"股票数: {report.get('stock_count', 0)}")
    print(f"评级: {report.get('rating', '?')} | 信号强度: {report.get('signal_strength', 0)}")
    print(f"report_path: {report.get('report_path', '?')}")
else:
    print(f"Error: {result.get('error', 'unknown')}")
