"""查东财概念板块中 AI 相关的所有子板块"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.tushare_client import TushareClient

client = TushareClient()
print("=" * 70)

# 1. 拿全量 dc_index，搜所有 AI 相关的
idx = client.call("dc_index")
print(f"dc_index 总板块数: {len(idx)}")
print(f"列: {list(idx.columns)}")

# 搜索关键词
for kw in ["人工", "智能", "AI", "算力", "大模型", "芯片", "算法", "机器人", "自动驾驶", "机器学习"]:
    matches = idx[idx["name"].str.contains(kw, na=False)]
    if not matches.empty:
        print(f"\n[{kw}] 匹配 {len(matches)} 个:")
        for _, row in matches.iterrows():
            print(f"  {row['ts_code']}  {row['name']}  "
                  f"idx_type={row.get('idx_type')}  level={row.get('level')}  "
                  f"total_mv={row.get('total_mv')}  leading={row.get('leading')}")

time.sleep(0.4)

# 2. 看看"人工智能 BK0800"的 level/idx_type 详情
print("\n" + "=" * 70)
print("[2] 人工智能 BK0800.DC 详细信息")
ai = idx[idx["ts_code"] == "BK0800.DC"]
for _, row in ai.iterrows():
    for col in idx.columns:
        print(f"  {col:20s}: {row[col]}")

# 3. 查有没有parent/父子关系概念
# 东财概念板块的代码规律：BK开头4位数字
# 看有没有 BK08xx 其他子板块
print("\n" + "=" * 70)
print("[3] BK08xx 系列子板块")
bk08 = idx[idx["ts_code"].str.startswith("BK08", na=False)]
print(f"BK08xx 共 {len(bk08)} 个板块:")
for _, row in bk08.iterrows():
    print(f"  {row['ts_code']}  {row['name']}  idx_type={row.get('idx_type')}  level={row.get('level')}")

# 4. 看看不同 idx_type 和 level 的分布
print("\n" + "=" * 70)
print("[4] idx_type / level 分布")
if "idx_type" in idx.columns:
    print(f"idx_type 分布: {idx['idx_type'].value_counts().to_dict()}")
if "level" in idx.columns:
    print(f"level 分布: {idx['level'].value_counts().to_dict()}")

# 5. 看看是否有"概念"vs"行业"的分类，同一板块名在不同 type 下
print("\n" + "=" * 70)
print("[5] '人工智能' 在所有 idx_type 下的出现")
ai_all = idx[idx["name"] == "人工智能"]
for _, row in ai_all.iterrows():
    print(f"  {row['ts_code']}  name={row['name']}  idx_type={row.get('idx_type')}  level={row.get('level')}")

print("\n完成")
