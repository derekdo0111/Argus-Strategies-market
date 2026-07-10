"""Test concept builder - controlled nuclear fusion"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.strategies.prosperity.tools.concept_builder import search_concept_stocks

theme = "可控核聚变"
print("=" * 60)
print(f"Building concept board: {theme}")
print("=" * 60)

stocks = search_concept_stocks(theme)

if not stocks:
    print("FAILED: No stocks found")
else:
    print(f"\nOK: {len(stocks)} stocks found:\n")
    for i, s in enumerate(stocks, 1):
        chain = s.get("chain", "")
        chain_str = f" [{chain}]" if chain else ""
        verified = "OK" if s.get("verified", False) else "Unverified"
        print(f"  {i:2d}. {s['ts_code']:12s} {s['name']:8s} {chain_str} {verified}")

    print("\n" + "=" * 60)
    print("Cache: data/prosperity/concept_boards/可控核聚变.yaml")
    print("=" * 60)
