"""诊断 fina_indicator 的 end_date 格式"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.tushare_client import TushareClient

c = TushareClient()
fina = c.get_fina_indicator('000568.SZ')
print("=== FINA INDICATOR end_dates (所有) ===")
for d in sorted(fina['end_date'].unique(), reverse=True):
    print(f"  '{d}' -> year='{d[:4]}'")
print(f"\nTotal: {len(fina['end_date'].unique())} unique dates")
