"""一次性脚本：清理 人工智能 行业的所有 DB 记录"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.strategies.prosperity.models import (
    get_engine, get_session,
    Industry, ResearchSession, Hypothesis,
    IndustryMetrics, StockPool, TrackingItem,
)
from sqlalchemy import text

engine = get_engine()
db = get_session(engine)

try:
    industry = db.query(Industry).filter_by(name="人工智能").first()
    if not industry:
        print("DB 中无 人工智能 记录，无需清理。")
    else:
        iid = industry.id
        
        # 1. tracking_items
        n_track = db.query(TrackingItem).filter_by(industry_id=iid).delete()
        print(f"  删除 tracking_items: {n_track} 条")
        
        # 2. hypotheses (via sessions)
        session_ids = [s.id for s in db.query(ResearchSession).filter_by(industry_id=iid).all()]
        n_hyp = 0
        for sid in session_ids:
            n_hyp += db.query(Hypothesis).filter_by(session_id=sid).delete()
        print(f"  删除 hypotheses: {n_hyp} 条")
        
        # 3. stock_pools (via sessions)
        n_pool = 0
        for sid in session_ids:
            n_pool += db.query(StockPool).filter_by(session_id=sid).delete()
        print(f"  删除 stock_pools: {n_pool} 条")
        
        # 4. industry_metrics
        n_met = db.query(IndustryMetrics).filter_by(industry_id=iid).delete()
        print(f"  删除 industry_metrics: {n_met} 条")
        
        # 5. research_sessions
        n_sess = db.query(ResearchSession).filter_by(industry_id=iid).delete()
        print(f"  删除 research_sessions: {n_sess} 条")
        
        # 6. industry
        db.delete(industry)
        print(f"  删除 industry: 人工智能")
        
        db.commit()
        print("[OK] DB 清理完成！")
except Exception as e:
    db.rollback()
    print(f"[FAIL] 清理失败: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()
