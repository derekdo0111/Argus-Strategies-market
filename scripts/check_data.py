import sys, io, yaml
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

codes = ["000568.SZ", "002818.SZ", "600809.SH", "000429.SZ"]
for code in codes:
    path = f"d:/project/Investment Strategy/data/stock_cache/{code}/raw_data.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        ann = d.get("annual_financials", [])[:5]
        if not ann:
            print(f"\n{code}: 无财务数据")
            continue
        print(f"\n=== {code} ({d['meta']['name']}) ===")
        for a in ann:
            rev = a['income'].get('revenue', 0)
            np = a['income'].get('net_profit', 0)
            ocf = a['cashflow'].get('operating_cf', 0)
            fcf = a['cashflow'].get('fcf', 0)
            rec = a['balance_sheet'].get('receivables', 0)
            inv = a['balance_sheet'].get('inventory', 0)
            print(f"  {a['year']}: rev={rev:>10.2f}  np={np:>8.2f}  ocf={ocf:>8.2f}  fcf={fcf:>8.2f}  rec={rec:>8.2f}  inv={inv:>8.2f}")
    except Exception as e:
        print(f"  {code}: ERROR {e}")
