"""临时脚本：手动触发高景气策略全流程"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.strategies.prosperity.coordinator import Coordinator

coordinator = Coordinator()
result = coordinator.run_full_pipeline("人工智能", force=True)
print("\n=== DONE ===")
print(f"Status: {result.get('status', '?')}")
print(f"Rating: {result.get('rating', '?')}")
print(f"Signal: {result.get('total_signal', '?')}")
