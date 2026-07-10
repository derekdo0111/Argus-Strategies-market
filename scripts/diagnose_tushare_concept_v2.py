"""诊断 Tushare 东财概念板块接口 dc_index + dc_member"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.tushare_client import TushareClient

client = TushareClient()
print(f"Token: {client.token[:8]}...")
print("=" * 65)

# ═══════════════════════════════════════
# 1. dc_index — 东财概念板块列表
# ═══════════════════════════════════════
print("\n[1] dc_index() — 东财概念板块列表")
for date in [None, "20260708", "20260707"]:
    try:
        kwargs = {}
        label = "无参数"
        if date:
            kwargs["trade_date"] = date
            label = f"trade_date={date}"
        result = client.call("dc_index", **kwargs)
        if result is not None and not result.empty:
            print(f"  ✅ {label}: {len(result)} 个板块")
            print(f"     列: {list(result.columns)}")
            if "name" in result.columns:
                ai = result[result["name"].str.contains("人工智能", na=False)]
                print(f"     '人工智能' 匹配: {len(ai)} 个")
                for _, row in ai.iterrows():
                    print(f"       ts_code={row.get('ts_code')}, name={row['name']}")
                # 试模糊搜
                if len(ai) == 0:
                    all_names = result["name"].unique()
                    ai_like = [n for n in all_names if "人工" in str(n) or "智能" in str(n)]
                    print(f"     '人工'/'智能' 模糊匹配: {ai_like[:10]}")
            break  # 成功就跳出
        else:
            print(f"  ⚠️ {label}: 空结果")
    except Exception as e:
        print(f"  ❌ {label}: {type(e).__name__}: {e}")
    time.sleep(0.5)

# ═══════════════════════════════════════
# 2. dc_member — 人工智能板块成分股
# ═══════════════════════════════════════
print("\n[2] dc_member() — 东财概念成分股")

# 先拿到概念列表，找"人工智能"的 ts_code
try:
    idx = client.call("dc_index", trade_date="20260708")
    if idx is not None and not idx.empty:
        ai = idx[idx["name"].str.contains("人工智能", na=False)]
        for _, row in ai.iterrows():
            ts_code = row["ts_code"]
            name = row["name"]
            time.sleep(0.4)
            try:
                members = client.call("dc_member", ts_code=ts_code, trade_date="20260708")
                if members is not None and not members.empty:
                    print(f"\n  板块: {ts_code} {name}")
                    print(f"  成分股数: {len(members)}")
                    print(f"  列: {list(members.columns)}")
                    if "name" in members.columns:
                        print(f"  前15: {members['name'].head(15).tolist()}")
                    if "con_code" in members.columns:
                        print(f"  前15代码: {members['con_code'].head(15).tolist()}")
                        # 验证代码格式
                        print(f"  代码样本: {members['con_code'].head(3).tolist()}")
                    # 搜典型 AI 股
                    ai_kw = ["寒武纪", "海康", "科大讯飞", "中科曙光", "浪潮",
                             "兆易创新", "韦尔", "景嘉微", "中芯国际", "澜起",
                             "云从", "商汤", "第四范式", "虹软", "格灵深瞳"]
                    if "name" in members.columns:
                        for kw in ai_kw:
                            m = members[members["name"].str.contains(kw, na=False)]
                            if not m.empty:
                                print(f"    ★ {kw}: {m['name'].tolist()}")
                else:
                    print(f"\n  板块: {ts_code} {name}: 空")
            except Exception as e:
                print(f"\n  板块: {ts_code} {name}: ❌ {type(e).__name__}: {e}")
    else:
        print("  跳过（无板块列表）")
except Exception as e:
    print(f"  ❌: {type(e).__name__}: {e}")

# ═══════════════════════════════════════
# 3. 对比：同花顺 vs 东财 的数据量
# ═══════════════════════════════════════
print("\n[3] 对比：同花顺 ths_member vs 东财 dc_member")
try:
    # 东财
    idx_dc = client.call("dc_index", trade_date="20260708")
    ai_dc = idx_dc[idx_dc["name"].str.contains("人工智能", na=False)]
    dc_count = 0
    for _, row in ai_dc.iterrows():
        time.sleep(0.4)
        m = client.call("dc_member", ts_code=row["ts_code"], trade_date="20260708")
        if m is not None:
            dc_count = len(m)
            break
    
    # 同花顺
    time.sleep(0.4)
    idx_ths = client.get_ths_index(type="N")
    ai_ths = idx_ths[idx_ths["name"].str.contains("人工智能", na=False)]
    ths_count = 0
    for _, row in ai_ths.iterrows():
        time.sleep(0.4)
        m = client.get_ths_member(ts_code=row["ts_code"])
        if m is not None:
            ths_count = len(m)
            break
    
    print(f"  东财 dc_member('人工智能'): {dc_count} 只")
    print(f"  同花顺 ths_member('人工智能'): {ths_count} 只")
except Exception as e:
    print(f"  ❌: {e}")

print("\n" + "=" * 65)
print("诊断完成")
