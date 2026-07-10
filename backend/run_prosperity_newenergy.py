"""临时脚本：运行新能源行业高景气分析"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.strategies.prosperity.coordinator import Coordinator

c = Coordinator()
print("=" * 60)
print("开始分析：新能源")
print("=" * 60)
try:
    result = c.run_full_pipeline("新能源", force=True)
    print("\n" + "=" * 60)
    print("分析完成！")
    print(f"Session ID: {result.get('session_id')}")
    print(f"Status: {result.get('status')}")
    report = result.get('report_path', 'N/A')
    wiki = result.get('wiki_path', 'N/A')
    print(f"Report: {report}")
    print(f"Wiki: {wiki}")
    print("=" * 60)
except Exception as e:
    print(f"\n错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
