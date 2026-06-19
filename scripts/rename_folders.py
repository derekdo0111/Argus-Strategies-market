"""文件夹改名: {ts_code} -> {name}_{ts_code}

读取 candidate_pool.yaml，将 stock_cache 下的文件夹从纯代码改为 名称_代码。
用法: python scripts/rename_folders.py
"""
import sys, io, yaml, shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

cache_dir = Path("d:/project/Investment Strategy/data/stock_cache")
pool_path = cache_dir / "candidate_pool.yaml"

if not pool_path.exists():
    print("candidate_pool.yaml 不存在，请先运行全量刷新")
    sys.exit(1)

with open(pool_path, "r", encoding="utf-8") as f:
    pool = yaml.safe_load(f)

print(f"候选池: {len(pool)} 只\n")

renamed = 0
skipped = 0

# 构建 ts_code -> name 映射
name_map = {}
for c in pool:
    ts = c["ts_code"]
    name = c["name"]
    # 清理名称中的非法字符
    safe_name = name.replace("/", "").replace("\\", "").replace(":", "").replace("*", "").replace("?", "").replace("\"", "").replace("<", "").replace(">", "").replace("|", "")
    name_map[ts] = safe_name

for ts, safe_name in name_map.items():
    old_path = cache_dir / ts
    new_path = cache_dir / f"{safe_name}_{ts}"
    
    if not old_path.exists():
        print(f"  跳过 {ts} ({safe_name}): 文件夹不存在")
        skipped += 1
        continue
    
    if new_path.exists():
        print(f"  跳过 {ts} ({safe_name}): 目标已存在")
        skipped += 1
        continue
    
    try:
        shutil.move(str(old_path), str(new_path))
        print(f"  {ts} -> {safe_name}_{ts}")
        renamed += 1
    except Exception as e:
        print(f"  FAIL {ts}: {e}")

print(f"\n完成: 改名 {renamed} 个, 跳过 {skipped} 个")
