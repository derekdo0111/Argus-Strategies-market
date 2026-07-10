"""Verify matched_l3 logic - check if H3 mappings are consistent"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

# Load the hypothesis file to check L3 definitions
import yaml
from pathlib import Path

hyp_path = Path("d:/project/Investment Strategy/data/prosperity/wiki/hypotheses")
for yf in sorted(hyp_path.glob("*.yaml")):
    with open(yf, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, dict) and "l3" in data:
        print(f"\n=== {yf.name} ===")
        l3 = data["l3"]
        for k, v in l3.items():
            print(f"  {k}: {v.get('name', '?')}")
            print(f"    direction: {v.get('direction', '?')}")
            print(f"    investment_implication: {str(v.get('investment_implication', ''))[:120]}")

print("\n--- Checking stock_pool.yaml matched_l3 ---")
pool = Path("d:/project/Investment Strategy/data/prosperity/raw/可控核聚变/stock_pool.yaml")
with open(pool, encoding="utf-8") as f:
    stocks = yaml.safe_load(f)

h3_counts = {}
for s in stocks:
    h3 = s.get("matched_l3", "?")
    h3_counts[h3] = h3_counts.get(h3, 0) + 1

print(f"L3 distribution: {h3_counts}")

# Spot check direction_score vs matched_l3 consistency
print("\nSpot checks (direction_score parity):")
for s in stocks[:10]:
    name = s["name"]
    ds = s["direction_score"]
    h3 = s["matched_l3"]
    purity = s["purity_score"]
    print(f"  {name:<8} dir={ds:.2f}  L3={h3}  purity={purity:.4f}")
