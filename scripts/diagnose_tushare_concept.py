"""诊断 Tushare 概念板块接口实际返回"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.tushare_client import TushareClient

client = TushareClient()
print(f"Token: {client.token[:8]}...")
print("=" * 65)

# ═══════════════════════════════════════
# 1. concept API — 概念分类列表
# ═══════════════════════════════════════
print("\n[1] concept() — 概念分类列表")
try:
    concepts = client.call("concept")
    if concepts is not None and not concepts.empty:
        print(f"  ✅ 成功: {len(concepts)} 个概念")
        print(f"  列: {list(concepts.columns)}")
        # 搜"人工智能"
        if "name" in concepts.columns:
            ai = concepts[concepts["name"].str.contains("人工智能", na=False)]
            print(f"  '人工智能' 匹配: {len(ai)} 个")
            for _, row in ai.iterrows():
                print(f"    id={row.get('id')}, name={row['name']}, src={row.get('src')}")
    else:
        print("  ⚠️ 空结果")
except Exception as e:
    print(f"  ❌ 失败: {e}")

time.sleep(0.5)

# ═══════════════════════════════════════
# 2. concept_detail API — 用 id 查成分股
# ═══════════════════════════════════════
print("\n[2] concept_detail() — 用 concept().id 查询")
try:
    # 重新拿 concepts
    concepts = client.call("concept")
    if concepts is not None and not concepts.empty and "name" in concepts.columns:
        ai = concepts[concepts["name"].str.contains("人工智能", na=False)]
        for _, row in ai.iterrows():
            cid = row["id"]
            cname = row["name"]
            time.sleep(0.4)
            
            # 尝试 id 参数
            try:
                detail = client.call("concept_detail", id=cid)
                if detail is not None and not detail.empty:
                    print(f"  ✅ concept_detail(id={cid}) '{cname}': {len(detail)} 只股票")
                    print(f"      列: {list(detail.columns)}")
                    if "ts_code" in detail.columns:
                        print(f"      前10代码: {detail['ts_code'].head(10).tolist()}")
                    if "name" in detail.columns:
                        print(f"      前10名称: {detail['name'].head(10).tolist()}")
                else:
                    print(f"  ⚠️ concept_detail(id={cid}) 空结果")
            except Exception as e:
                print(f"  ❌ concept_detail(id={cid}): {e}")
            
            time.sleep(0.4)
            
            # 也试 ts_code 参数
            try:
                detail2 = client.call("concept_detail", ts_code=row.get("ts_code", ""))
                print(f"  ts_code={row.get('ts_code')}: {len(detail2) if detail2 is not None else 0} 条")
            except:
                pass
    else:
        print("  跳过（concept 无数据）")
except Exception as e:
    print(f"  ❌: {e}")

time.sleep(0.5)

# ═══════════════════════════════════════
# 3. 尝试现有 get_concept_detail 方法
# ═══════════════════════════════════════
print("\n[3] client.get_concept_detail(concept_name='人工智能') — 现有方法")
try:
    result = client.get_concept_detail(concept_name="人工智能")
    if result is not None and not result.empty:
        print(f"  ✅: {len(result)} 条")
        print(f"  列: {list(result.columns)}")
    else:
        print(f"  ⚠️: 空结果")
except Exception as e:
    print(f"  ❌: {e}")

time.sleep(0.5)

# ═══════════════════════════════════════
# 4. 同花顺 ths_index — 概念板块
# ═══════════════════════════════════════
print("\n[4] ths_index(type='N') — 同花顺概念板块列表")
try:
    idx = client.get_ths_index(type="N")
    if idx is not None and not idx.empty:
        print(f"  ✅: {len(idx)} 个概念板块")
        print(f"  列: {list(idx.columns)}")
        if "name" in idx.columns:
            ai = idx[idx["name"].str.contains("人工智能", na=False)]
            print(f"  '人工智能' 匹配: {len(ai)} 个")
            for _, row in ai.iterrows():
                print(f"    {row['ts_code']}  {row['name']}  count={row.get('count','?')}")
    else:
        print("  ⚠️ 空/无权限")
except Exception as e:
    print(f"  ❌: {e}")

time.sleep(0.5)

# ═══════════════════════════════════════
# 5. 同花顺 ths_member — 人工智能板块成分股
# ═══════════════════════════════════════
print("\n[5] ths_member — 人工智能板块成分股详情")
try:
    idx = client.get_ths_index(type="N")
    if idx is not None and not idx.empty:
        ai = idx[idx["name"].str.contains("人工智能", na=False)]
        for _, row in ai.head(5).iterrows():
            ts_code = row["ts_code"]
            name = row["name"]
            time.sleep(0.4)
            try:
                members = client.get_ths_member(ts_code=ts_code)
                if members is not None and not members.empty:
                    print(f"\n  板块: {ts_code} {name}")
                    print(f"  成分股数: {len(members)}")
                    print(f"  列: {list(members.columns)}")
                    # 确定 code/name 列
                    code_col = None
                    name_col = None
                    for col in members.columns:
                        if "code" in col.lower():
                            code_col = col
                        if "name" in col.lower():
                            name_col = col
                    print(f"  code_col={code_col}, name_col={name_col}")
                    if name_col:
                        print(f"  前10: {members[name_col].head(10).tolist()}")
                        print(f"  尾10: {members[name_col].tail(10).tolist()}")
                        # 搜典型 AI 股
                        ai_kw = ["寒武纪", "海康", "科大讯飞", "中科曙光", "浪潮", 
                                 "兆易创新", "韦尔", "紫光", "景嘉微", "中芯国际"]
                        for kw in ai_kw:
                            m = members[members[name_col].str.contains(kw, na=False)]
                            if not m.empty:
                                print(f"    ★ {kw}: {m[name_col].tolist()}")
                else:
                    print(f"\n  板块: {ts_code} {name}: 空")
            except Exception as e:
                print(f"\n  板块: {ts_code} {name}: ❌ {e}")
except Exception as e:
    print(f"  ❌: {e}")

print("\n" + "=" * 65)
print("诊断完成")
