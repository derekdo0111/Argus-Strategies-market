"""临时脚本：运行高景气行业分析（带子板块交互推荐）"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.strategies.prosperity.coordinator import Coordinator


def _interactive_select(coordinator: Coordinator, industry_name: str, force_full: bool) -> str:
    """检查成分股数量，超限时交互式子板块推荐。

    Returns:
        最终选定的行业/子板块名称
    """
    check = coordinator.check_industry_size(industry_name)

    if not check["overflow"]:
        return industry_name

    subs = check["subconcepts"]
    print(f"\n[!] '{check['name']}' — {check['count']} 只成分股，超过阈值 {check['threshold']} 只。")

    if force_full:
        print(f"   --force-full 已启用 -> 全量分析 {check['count']} 只\n")
        return industry_name

    print(f"推荐子板块（更聚焦）：\n")
    for i, s in enumerate(subs):
        print(f"  [{i+1}] {s['name']:<18s}  {s['count']:>3d} 只  (相似度 {s['score']:.0f}%)")

    if check["count"] <= check["threshold"] * 3:
        print(f"  [0] 全量分析（{check['count']} 只，耗时较长）")

    print()

    while True:
        choice = input(f"请输入编号 (0-{len(subs)}) 或子板块名称: ").strip()
        if not choice:
            continue
        if choice == "0":
            print(f"\n[OK] 全量分析 {check['count']} 只\n")
            return industry_name
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(subs):
                selected = subs[idx]["name"]
                print(f"\n[OK] 已选择子板块: {selected}\n")
                return selected
        except ValueError:
            for s in subs:
                if s["name"] == choice:
                    print(f"\n[OK] 已选择子板块: {choice}\n")
                    return choice
        print(f"[!] 无效输入，请重新输入")


def main():
    parser = argparse.ArgumentParser(description="Prosperity Strategy — 高景气行业分析")
    parser.add_argument("industry", nargs="?", default="人工智能",
                        help="行业/概念板块名称（默认: 人工智能）")
    parser.add_argument("--force", action="store_true",
                        help="忽略冷却期，强制执行")
    parser.add_argument("--force-full", action="store_true",
                        help="成分股超限时自动全量分析，不显示交互菜单")
    args = parser.parse_args()

    c = Coordinator()

    # 交互式子板块推荐（超限时）
    final_industry = _interactive_select(c, args.industry, args.force_full)

    print("=" * 60)
    print(f"开始分析：{final_industry}")
    print("=" * 60)

    try:
        result = c.run_full_pipeline(final_industry, force=args.force)
        print("\n" + "=" * 60)
        print("分析完成！")
        print(f"Session ID: {result.get('session_id')}")
        print(f"Status: {result.get('status')}")
        report = result.get('report', {})
        rating = report.get('rating', 'N/A') if isinstance(report, dict) else 'N/A'
        print(f"Rating: {rating}")
        print("=" * 60)
    except Exception as e:
        print(f"\n[FAIL] 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

