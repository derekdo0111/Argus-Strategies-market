"""test_new_energy_pool.py - test all 5 sources for stock pool"""
import sys, traceback
sys.path.insert(0, "backend")

from app.services.tushare_client import TushareClient
import pandas as pd

client = TushareClient()
industry_name = "新能源"

def safe_print(*args, **kwargs):
    """print with gbk-safe fallback"""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        s = " ".join(str(a) for a in args)
        print(s.encode("ascii", errors="replace").decode("ascii"), **kwargs)

safe_print("=" * 60)
safe_print(f"Target: {industry_name}")
safe_print(f"Token: {'set' if client.token else 'NOT SET'}")
safe_print("=" * 60)

def show_err(msg, e):
    safe_print(f"  [FAIL] {msg}: {str(e)[:200]}")

# =====================================================================
# Source 1: stock_basic industry field
# =====================================================================
safe_print("\n[1/6] stock_basic industry field")
try:
    stocks = client.get_stock_basic()
    industry_clean = industry_name.replace(" ", "")
    exact = stocks[stocks["industry"] == industry_clean]
    safe_print(f"  Exact match: {len(exact)} stocks")
    if exact.empty:
        fuzzy = stocks[stocks["industry"].str.contains(industry_clean, na=False)]
        safe_print(f"  Fuzzy match: {len(fuzzy)} stocks")
        if not fuzzy.empty:
            safe_print(f"  Sample: {fuzzy[['ts_code','name','industry']].head(5).to_string()}")
    else:
        safe_print(f"  Sample: {exact[['ts_code','name','industry']].head(5).to_string()}")
except Exception as e:
    show_err("stock_basic", e)

# =====================================================================
# Source 2: Shenwan index_classify
# =====================================================================
safe_print("\n[2/6] Shenwan index_classify (L1/L2/L3)")
for level in ("L1", "L2", "L3"):
    try:
        sw = client.get_industry(level=level)
        matches = sw[sw["industry_name"] == industry_name]
        safe_print(f"  L{level[-1]}: {len(matches)} stocks")
        if not matches.empty:
            safe_print(f"  Sample: {matches[['index_code','industry_name']].head(3).to_string()}")
    except Exception as e:
        show_err(f"L{level[-1]}", e)

# =====================================================================
# Source 3: concept_detail with specific name
# =====================================================================
safe_print("\n[3/6] concept_detail (targeted: '新能源')")
try:
    result = client.get_concept_detail(concept_name=industry_name)
    if result is not None and not result.empty:
        safe_print(f"  [OK] {len(result)} stocks returned")
        safe_print(f"  Top 5:\n{result[['ts_code','name']].head(5).to_string()}")
    else:
        safe_print("  [WARN] Empty DataFrame returned")
except Exception as e:
    show_err("concept_detail('新能源')", e)

# =====================================================================
# Source 4: concept_detail - full list, then filter
# =====================================================================
safe_print("\n[4/6] concept_detail (full list, then filter)")
try:
    result = client.call("concept_detail")
    if result is not None and not result.empty:
        col_names = list(result.columns)
        safe_print(f"  Columns: {col_names}")
        match_col = None
        for c in col_names:
            if "name" in c.lower() or "concept" in c.lower():
                match_col = c
                break
        if match_col:
            matching = result[result[match_col].str.contains(
                "新能源|光伏|储能|锂电|风电", na=False)]
            safe_print(f"  Total concepts: {len(result)}, Matched: {len(matching)}")
            if not matching.empty:
                safe_print(f"  Concepts: {matching[match_col].unique()[:10]}")
        else:
            safe_print(f"  Total: {len(result)} rows, no name/concept column found")
    else:
        safe_print("  [WARN] Empty DataFrame returned")
except Exception as e:
    show_err("concept_detail (full)", e)

# =====================================================================
# Source 5: Tushare "concept" API (concept list, not detail)
# =====================================================================
safe_print("\n[5/6] concept API (concept list)")
try:
    concept_list = client.call("concept")
    if concept_list is not None and not concept_list.empty:
        col_names = list(concept_list.columns)
        safe_print(f"  Columns: {col_names}")
        match_col = None
        for c in col_names:
            if "name" in c.lower():
                match_col = c
                break
        if match_col:
            matching = concept_list[concept_list[match_col].str.contains(
                "新能源|光伏|储能|锂电|风电", na=False)]
            safe_print(f"  Total: {len(concept_list)}, Matched new-energy: {len(matching)}")
            if not matching.empty:
                safe_print(f"  {matching[[match_col]].head(5).to_string()}")
    else:
        safe_print("  [WARN] Empty DataFrame returned")
except Exception as e:
    show_err("concept", e)

# =====================================================================
# Source 6: THS (TongHuaShun) index -> member
# =====================================================================
safe_print("\n[6/6] THS ths_index -> ths_member")
try:
    ths = client.get_ths_index(type="N")  # N = concept index
    if ths is not None and not ths.empty:
        matching = ths[ths["name"].str.contains("新能源", na=False)]
        safe_print(f"  Total THS concept boards: {len(ths)}")
        safe_print(f"  Matched '新能源': {len(matching)} boards")
        if not matching.empty:
            for _, row in matching.head(5).iterrows():
                safe_print(f"    {row['ts_code']} {row['name']} ({row.get('count','?')} stocks)")
            # Try pulling members of the first matched board
            first = matching.iloc[0]
            safe_print(f"\n  Pulling members for [{first['name']}]...")
            try:
                members = client.get_ths_member(ts_code=first["ts_code"])
                if members is not None and not members.empty:
                    col = "con_code" if "con_code" in members.columns else "ts_code"
                    safe_print(f"  [OK] {len(members)} members")
                    safe_print(f"  Top 5:\n{members[[col,'name']].head(5).to_string()}")
                else:
                    safe_print("  [WARN] Empty members")
            except Exception as e2:
                show_err("ths_member", e2)
    else:
        safe_print("  [WARN] ths_index returned empty")
except Exception as e:
    show_err("ths_index", e)

# =====================================================================
# Bonus: Search engine concept builder (current fallback)
# =====================================================================
safe_print("\n[Bonus] search_concept_stocks (current fallback)")
try:
    from app.strategies.prosperity.tools.concept_builder import search_concept_stocks
    concept_stocks = search_concept_stocks(industry_name)
    if concept_stocks:
        safe_print(f"  [OK] {len(concept_stocks)} stocks")
        for s in concept_stocks[:10]:
            safe_print(f"    {s.get('ts_code','?')} {s.get('name','?')} [{s.get('chain','?')}]")
    else:
        safe_print("  [WARN] Empty")
except Exception as e:
    show_err("search_concept_stocks", e)

safe_print("\n" + "=" * 60)
safe_print("Test complete")
