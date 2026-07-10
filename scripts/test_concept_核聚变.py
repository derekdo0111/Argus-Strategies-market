"""测试搜索引擎自建概念板块 — 可控核聚变"""
import sys
sys.path.insert(0, "backend")

from app.strategies.prosperity.tools.concept_builder import search_concept_stocks

theme = "可控核聚变"
print(f"\n{'='*60}")
print(f"🔬 构建概念板块: {theme}")
print(f"{'='*60}\n")

stocks = search_concept_stocks(theme)

if not stocks:
    print("❌ 未找到相关股票")
else:
    print(f"\n✅ 共找到 {len(stocks)} 只股票:\n")
    for i, s in enumerate(stocks, 1):
        chain = s.get("chain", "")
        chain_str = f" [{chain}]" if chain else ""
        verified = "✅" if s.get("verified", False) else "⚠️未验证"
        print(f"  {i:2d}. {s['ts_code']:12s} {s['name']:8s} {chain_str} {verified}")
    
    print(f"\n{'='*60}")
    print("缓存文件: data/prosperity/concept_boards/可控核聚变.yaml")
    print(f"{'='*60}")
