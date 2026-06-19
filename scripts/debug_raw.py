import yaml
with open('data/stock_cache/000568.SZ/raw_data.yaml', 'r', encoding='utf-8') as f:
    d = yaml.safe_load(f)
af = d['annual_financials']
print('Total years:', len(af))
for y in af:
    inc = y.get('income', {})
    cf = y.get('cashflow', {})
    bs = y.get('balance_sheet', {})
    rev = inc.get('revenue', 0)
    np_ = inc.get('net_profit', 0)
    depr = cf.get('depr_amort', 0)
    ie = cf.get('interest_expense', 0)
    ocf = cf.get('operating_cf', 0)
    fcf = cf.get('fcf', 0)
    fa = bs.get('fixed_assets', 0)
    print("Year=%s: rev=%.0f np=%.0f depr=%.0f ie=%.0f ocf=%.0f fcf=%.0f fa=%.0f" % (
        y['year'], rev, np_, depr, ie, ocf, fcf, fa))
# Check for old field names
for y in af[:3]:
    cf = y.get('cashflow', {})
    print("\nFields in cashflow:", sorted(cf.keys()))
    break
