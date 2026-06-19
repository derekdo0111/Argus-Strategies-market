"""验证修复后的数据字段是否正确 - 制造型企业"""
import yaml
from pathlib import Path

CACHE_DIR = Path(__file__).parent.parent / "data" / "stock_cache"

def verify_stock(ts_code: str):
    raw_path = CACHE_DIR / ts_code / "raw_data.yaml"
    if not raw_path.exists():
        print(f"[SKIP] {ts_code}: no cache")
        return

    with open(raw_path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)

    af = d.get("annual_financials", [])
    dh = d.get("dividend_history", [])
    bi = d.get("basic_info", {})

    print(f"\n{'='*60}")
    print(f"  {ts_code} ({d['meta']['name']}) - {d['meta']['industry']}")
    print(f"{'='*60}")

    # Cashflow 最近3年
    print("\n--- Cashflow (最近3年) ---")
    for y in af[:3]:
        cf = y.get("cashflow", {})
        inc = y.get("income", {})
        bs = y.get("balance_sheet", {})
        depr = cf.get("depr_amort", 0)
        ie = cf.get("interest_expense", 0)
        ocf = cf.get("operating_cf", 0)
        fcf = cf.get("fcf", 0)
        np_ = inc.get("net_profit", 0)
        rev = inc.get("revenue", 0)
        fa = bs.get("fixed_assets", 0)
        print(f"  Year={y['year']}: rev={rev:.0f}, np={np_:.0f}, fa={fa:.0f}")
        print(f"    depr_amort={depr:.0f}, fcf={fcf:.0f}, interest={ie:.0f}, ocf={ocf:.0f}")

    # Dividend
    print("\n--- Dividend (最近3条) ---")
    for dd in dh[:3]:
        print(f"  Year={dd['year']}: dps={dd.get('dividend_per_share', 0)}, "
              f"total_div={dd.get('total_dividend', 0):.0f}")

    print(f"\n  total_share={bi.get('total_share', 0):.0f}, total_mv={bi.get('total_mv', 0):.0f}")

    # 是否有真实折旧/利息
    has_real_depr = any(
        y.get("cashflow", {}).get("depr_amort", 0) > 0
        for y in af[:3]
    )
    has_real_interest = any(
        y.get("cashflow", {}).get("interest_expense", 0) > 0
        for y in af[:3]
    )
    print(f"\n  有真实折旧: {has_real_depr}")
    print(f"  有真实利息: {has_real_interest}")


if __name__ == "__main__":
    verify_stock("000568.SZ")
