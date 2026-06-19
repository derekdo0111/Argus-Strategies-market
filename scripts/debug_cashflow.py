"""诊断 cashflow 数据匹配问题"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from app.services.tushare_client import TushareClient

c = TushareClient()
income = c.get_income('000568.SZ')
balance = c.get_balance_sheet('000568.SZ')
cashflow = c.get_cashflow('000568.SZ')

print("=== INCOME end_dates (最近20条) ===")
for d in sorted(income['end_date'].unique(), reverse=True)[:20]:
    rows = income[income['end_date']==d]
    rev = rows.iloc[0].get('revenue', 0)
    print(f"  {d}: revenue={rev:.0f}")

print("\n=== CASHFLOW end_dates with depr_fa_coga_dpba (最近20条) ===")
for d in sorted(cashflow['end_date'].unique(), reverse=True)[:20]:
    rows = cashflow[cashflow['end_date']==d]
    depr = rows.iloc[0].get('depr_fa_coga_dpba', float('nan'))
    print(f"  {d}: depr_fa_coga_dpba={depr}")

print("\n=== BALANCE end_dates (最近20条) ===")
for d in sorted(balance['end_date'].unique(), reverse=True)[:20]:
    print(f"  {d}")

print("\n=== Combined unique end_dates (desc, 最近30条) ===")
all_dates = set()
for df in [income, balance, cashflow]:
    if not df.empty:
        all_dates.update(df['end_date'].unique())
for d in sorted(all_dates, reverse=True)[:30]:
    year = d[:4]
    print(f"  {d} -> year={year}")

# 检查2025年第一个匹配的date
print("\n=== 2025 year data from each table (first match by sorted desc) ===")
year_2025_dates = [d for d in sorted(all_dates, reverse=True) if d[:4]=='2025']
if year_2025_dates:
    first_date = year_2025_dates[0]
    print(f"First date for 2025: {first_date}")
    cf_rows = cashflow[cashflow['end_date']==first_date]
    if not cf_rows.empty:
        row = cf_rows.iloc[0]
        print(f"  depr_fa={row.get('depr_fa_coga_dpba')}, amort_int={row.get('amort_intang_assets')}, fin_exp={row.get('finan_exp')}")
    else:
        print("  NO cashflow data for this date!")
