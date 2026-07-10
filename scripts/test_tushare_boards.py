"""test_tushare_boards.py — Tushare direct: list all available board info"""
import sys, os, time
# Fix GBK encoding in PowerShell
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
from app.services.tushare_client import TushareClient

client = TushareClient()

print("=" * 70)
print(f"[Direct] Tushare | Token: {client.token[:8]}...")
print("=" * 70)

# ============================================================
# 1. stock_basic -> industry field
# ============================================================
print("\n[1] stock_basic -- Tushare industry field")
try:
    stocks = client.get_stock_basic()
    industry_counts = stocks.groupby("industry").size().sort_values(ascending=False)
    print(f"    Total stocks: {len(stocks)}")
    print(f"    Industries: {len(industry_counts)}")
    print(f"    Top 20 (by stock count):")
    for ind, cnt in industry_counts.head(20).items():
        print(f"      {ind:<20s} {cnt:>5d}")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 2. Shenwan index_classify L1/L2/L3
# ============================================================
print("\n[2] Shenwan index_classify (SW2021)")
for level in ("L1", "L2", "L3"):
    try:
        time.sleep(0.4)
        sw = client.get_industry(level=level)
        count = len(sw)
        cols = list(sw.columns)
        print(f"  {level}: {count} items  cols={cols}")
        if "industry_name" in sw.columns:
            names = sw['industry_name'].head(10).tolist()
            print(f"    First 10: {names}")
    except Exception as e:
        print(f"  {level} ERROR: {e}")

# ============================================================
# 3. index_member -- Shenwan component stocks
# ============================================================
print("\n[3] Shenwan index_member (sample L1)")
try:
    time.sleep(0.4)
    sw_l1 = client.get_industry(level="L1")
    if not sw_l1.empty and "index_code" in sw_l1.columns:
        test_codes = sw_l1["index_code"].head(3).tolist()
        for code in test_codes:
            try:
                time.sleep(0.4)
                members = client.call("index_member", index_code=code)
                name = sw_l1[sw_l1["index_code"]==code]["industry_name"].values[0]
                print(f"  {code} {name}: {len(members)} members")
            except Exception as e:
                print(f"  {code}: ERROR {str(e)[:60]}")
    else:
        print(f"  No index_code column or empty")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 4. concept -- all concept boards list
# ============================================================
print("\n[4] concept -- all concept list")
try:
    time.sleep(0.4)
    concepts = client.call("concept")
    if concepts is not None and not concepts.empty:
        print(f"  Total: {len(concepts)} concepts")
        print(f"  Cols: {list(concepts.columns)}")
        name_col = [c for c in concepts.columns if "name" in c.lower()]
        if name_col:
            nc = name_col[0]
            sample = concepts[nc].head(15).tolist()
            print(f"  First 15: {sample}")
            # new energy related
            matching = concepts[concepts[nc].str.contains("新能源|光伏|储能|锂电|风电|碳中和|绿色|氢能|充电桩|特高压|核能", na=False)]
            print(f"  New-energy related: {len(matching)}")
            for _, row in matching.iterrows():
                print(f"    {row[nc]}")
    else:
        print(f"  EMPTY / no permission")
except Exception as e:
    print(f"  ERROR: {e}")

# ============================================================
# 5. concept_detail -- concept component stocks
# ============================================================
print("\n[5] concept_detail -- component stocks")
for cname in ["新能源", "人工智能", "芯片"]:
    try:
        time.sleep(0.4)
        detail = client.get_concept_detail(concept_name=cname)
        if detail is not None and not detail.empty:
            samples = detail["ts_code"].head(3).tolist() if "ts_code" in detail else []
            print(f"  '{cname}': {len(detail)} stocks  sample: {samples}")
        else:
            print(f"  '{cname}': EMPTY / not found")
    except Exception as e:
        print(f"  '{cname}' ERROR: {e}")

# ============================================================
# 6. ths_index -- THS sector list (2000 points)
# ============================================================
print("\n[6] ths_index -- THS sector list")
for ths_type in ("N", "I", "S"):
    label = {"N": "Concept", "I": "Industry", "S": "Featured"}.get(ths_type, ths_type)
    try:
        time.sleep(0.4)
        idx = client.get_ths_index(type=ths_type)
        if idx is not None and not idx.empty:
            print(f"  type={ths_type} ({label}): {len(idx)} sectors")
            print(f"    Cols: {list(idx.columns)}")
            if "name" in idx.columns:
                print(f"    First 15: {idx['name'].head(15).tolist()}")
        else:
            print(f"  type={ths_type} ({label}): EMPTY / no permission")
    except Exception as e:
        print(f"  type={ths_type} ({label}): ERROR {str(e)[:80]}")

# ============================================================
# 7. ths_member -- THS sector members (6000 points)
# ============================================================
print("\n[7] ths_member -- THS sector members")
THS_TEST = {
    "885800.TI": "新能源",
    "885431.TI": "新能源汽车",
    "885706.TI": "光伏概念",
    "885710.TI": "锂电池概念",
    "885921.TI": "储能",
    "885707.TI": "风电概念",
    "885709.TI": "充电桩",
}
for code, name in THS_TEST.items():
    try:
        time.sleep(0.5)
        members = client.get_ths_member(ts_code=code)
        if members is not None and not members.empty:
            samples = members["name"].head(3).tolist() if "name" in members else list(members.columns)[:3]
            print(f"  {code} {name}: {len(members)} stocks  samples: {samples}")
        else:
            print(f"  {code} {name}: EMPTY / no permission")
    except Exception as e:
        print(f"  {code} {name}: ERROR {str(e)[:80]}")

# ============================================================
# 8. trade_cal -- latest trading day
# ============================================================
print("\n[8] trade_cal -- latest trading day")
try:
    time.sleep(0.4)
    cal = client.call("trade_cal", exchange="SSE", start_date="20260601", end_date="20260701")
    if cal is not None and not cal.empty:
        last_trade = cal[cal["is_open"]==1].tail(1)
        if not last_trade.empty:
            print(f"  Latest: {last_trade['cal_date'].values[0]}")
    else:
        print(f"  EMPTY")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 70)
print("Done: Tushare board scan complete")
