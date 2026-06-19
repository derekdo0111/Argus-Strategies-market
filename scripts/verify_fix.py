"""验证修复后的数据字段是否正确"""
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

    # Cashflow 新字段
    print("\n--- Cashflow (最近3年) ---")
    for y in af[:3]:
        cf = y.get("cashflow", {})
        print(f"  Year={y['year']}: depr_amort={cf.get('depr_amort', 'MISSING')}, "
              f"fcf={cf.get('fcf', 'MISSING')}, "
              f"interest_expense={cf.get('interest_expense', 'MISSING')}, "
              f"ocf={cf.get('operating_cf', 'MISSING')}")

    # 旧字段检查
    has_depreciation = any("depreciation" in y.get("cashflow", {}) for y in af[:3])
    has_amortization = any("amortization" in y.get("cashflow", {}) for y in af[:3])
    print(f"  [OLD] depreciation字段存在: {has_depreciation}")
    print(f"  [OLD] amortization字段存在: {has_amortization}")

    # Dividend
    print("\n--- Dividend (最近3条) ---")
    print(f"  Total records: {len(dh)}")
    for dd in dh[:3]:
        print(f"  Year={dd['year']}: dps={dd.get('dividend_per_share', 0)}, "
              f"total_div={dd.get('total_dividend', 'MISSING'):.2f}")

    # Basic info
    print(f"\n--- Basic Info ---")
    print(f"  total_share={bi.get('total_share', 'MISSING')}")
    print(f"  total_mv={bi.get('total_mv', 'MISSING')}")

    # 检查是否有遗留的 0.0 硬编码
    all_depr_zero = all(
        y.get("cashflow", {}).get("depr_amort", 1) == 0
        for y in af[:3] if y.get("cashflow")
    )
    all_int_zero = all(
        y.get("cashflow", {}).get("interest_expense", 1) == 0
        for y in af[:3] if y.get("cashflow")
    )
    all_div_zero = all(
        d.get("total_dividend", 1) == 0 for d in dh[:3]
    )
    print(f"\n--- 硬编码检测 ---")
    print(f"  近3年 depr_amort 全为0: {all_depr_zero}")
    print(f"  近3年 interest_expense 全为0: {all_int_zero}")
    print(f"  近3年 total_dividend 全为0: {all_div_zero}")


if __name__ == "__main__":
    # 验证富森美(002818 - 制造业有固定资产) + 东方财富(300059 - 金融服务无存货)
    for code in ["002818.SZ", "300059.SZ"]:
        verify_stock(code)
