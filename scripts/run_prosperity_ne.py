import sys, os
from datetime import datetime

# Windows 下避免 GBK 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, "backend")

# 减少技术噪音：只显示 WARNING+ 和用户可见的 print
import logging
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from app.strategies.prosperity.coordinator import Coordinator

print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
c = Coordinator()
result = c.run_full_pipeline("可控核聚变", force=True)
print(f"Result: status={result.get('status')}, session_id={result.get('session_id')}")

if result.get("status") == "completed":
    report = result.get("report", {})
    print(f"Report keys: {list(report.keys()) if report else 'N/A'}")
else:
    print(f"Error: {result.get('error', 'unknown')}")

