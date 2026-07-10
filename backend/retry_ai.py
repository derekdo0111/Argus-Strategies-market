"""重新跑 人工智能（清理失败 session 后）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.strategies.prosperity.models import get_engine, get_session, ResearchSession

engine = get_engine()
db = get_session(engine)
try:
    # 清理失败的 session
    n = db.query(ResearchSession).filter(ResearchSession.status == "failed").delete()
    db.commit()
    print(f"清理了 {n} 个失败 session")
finally:
    db.close()

from app.strategies.prosperity.coordinator import Coordinator

c = Coordinator()
print("=" * 60)
print("开始分析：人工智能")
print("=" * 60)
try:
    result = c.run_full_pipeline("人工智能", force=True)
    print("\n" + "=" * 60)
    print("分析完成！")
    print(f"Session ID: {result.get('session_id')}")
    print(f"Status: {result.get('status')}")
    print(f"Report: {result.get('report_path', 'N/A')}")
    print(f"Wiki: {result.get('wiki_path', 'N/A')}")
    print("=" * 60)
except Exception as e:
    print(f"\n[FAIL] {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
