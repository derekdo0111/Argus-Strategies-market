"""查所有AI子概念的成分股数量"""
import sys, os, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.tushare_client import TushareClient

client = TushareClient()

# 拿到概念板块
idx = client.call("dc_index", trade_date="20260708")

# 所有与 AI 相关的概念板块
ai_keywords = [
    "人工智能", "AI智能体", "算力", "大模型", "AI", "芯片",
    "算法", "机器人", "自动驾驶", "机器学习", "深度学习",
    "自然语言", "计算机视觉", "语音识别", "神经网络",
    "无人驾驶", "增强现实", "虚拟现实", "智能穿戴",
    "智能家居", "智能电网", "智能电视",
]

found = {}
for kw in ai_keywords:
    matches = idx[idx["name"].str.contains(kw, na=False)]
    matches = matches[matches["idx_type"] == "概念板块"]
    for _, row in matches.iterrows():
        code = row["ts_code"]
        if code not in found:
            found[code] = row["name"]

print(f"AI 相关概念板块: {len(found)} 个\n")
print(f"{'代码':20s} {'名称':16s} {'成分股数':>8s}  {'总市值(亿)':>10s}")
print("-" * 62)

for code, name in sorted(found.items()):
    time.sleep(0.35)
    try:
        members = client.call("dc_member", ts_code=code, trade_date="20260708")
        count = len(members) if members is not None else 0
        row_data = idx[idx["ts_code"] == code].iloc[0]
        mv = row_data.get("total_mv", 0)
        mv_str = f"{mv/1e8:,.0f}" if mv else "N/A"
        print(f"{code:20s} {name:16s} {count:>8d}  {mv_str:>10s}")
    except Exception as e:
        print(f"{code:20s} {name:16s} {'ERROR':>8s}  {str(e)[:20]:>10s}")
