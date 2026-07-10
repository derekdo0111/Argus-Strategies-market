"""
清理繁荣策略所有历史数据，用于纯冷启动全链路验证。

删除内容：
- SQLite 数据库
- wiki/industries/*.md
- wiki/hypotheses/*.md
- wiki/synthesis/*.md
- tracking/watchlist/*.yaml
- raw/*/（搜索缓存）
- concept_boards/*.yaml
- log.md（重置为空）
- index.md（重置为模板）

保留内容：
- 空目录结构
- SCHEMA.md
"""

import os
import shutil
from pathlib import Path

BASE = Path(r"d:\project\Investment Strategy\data\prosperity")

def safe_delete(path: Path) -> str:
    """删除文件或目录，返回操作描述"""
    if path.is_file():
        path.unlink()
        return f"  ✓ 删文件: {path.relative_to(BASE)}"
    elif path.is_dir():
        shutil.rmtree(path)
        return f"  ✓ 删目录: {path.relative_to(BASE)}"
    else:
        return f"  → 不存在，跳过: {path.relative_to(BASE)}"

def main():
    print("=" * 60)
    print("清理繁荣策略历史数据 (方案B: 纯冷启动)")
    print("=" * 60)

    results = []

    # 1. SQLite 数据库
    results.append(safe_delete(BASE / "prosperity.db"))

    # 2. wiki/industries/
    for f in (BASE / "wiki" / "industries").glob("*.md"):
        results.append(safe_delete(f))

    # 3. wiki/hypotheses/
    for f in (BASE / "wiki" / "hypotheses").glob("*.md"):
        results.append(safe_delete(f))

    # 4. wiki/synthesis/
    for f in (BASE / "wiki" / "synthesis").glob("*.md"):
        results.append(safe_delete(f))

    # 5. tracking/watchlist/
    for f in (BASE / "tracking" / "watchlist").glob("*.yaml"):
        results.append(safe_delete(f))

    # 6. raw/*/ 搜索缓存
    for d in (BASE / "raw").iterdir():
        if d.is_dir():
            results.append(safe_delete(d))

    # 7. concept_boards/
    for f in (BASE / "concept_boards").glob("*.yaml"):
        results.append(safe_delete(f))

    # 8. log.md 重置
    log_path = BASE / "log.md"
    log_path.write_text(
        "# 繁荣策略 · 运行日志\n\n"
        f"## {__import__('datetime').datetime.now().strftime('%Y-%m-%d')} - 清空重来\n\n"
        "_方案B：全量清理，纯冷启动验证。_\n\n"
    )

    # 9. index.md 重置
    index_path = BASE / "index.md"
    index_path.write_text(
        "# 繁荣策略 · 研究档案\n\n"
        "## 行业覆盖\n\n"
        "（暂无研究记录 — 已清空重来）\n\n"
    )

    print(f"\n清理完成！共 {len(results)} 项操作。\n")

    # 验证
    remaining = []
    for p in [BASE / "prosperity.db"]:
        if p.exists():
            remaining.append(str(p.relative_to(BASE)))
    for d in ["wiki/industries", "wiki/hypotheses", "wiki/synthesis", "tracking/watchlist"]:
        for f in (BASE / d).glob("*"):
            remaining.append(str(f.relative_to(BASE)))
    for d in (BASE / "raw").iterdir():
        if d.is_dir():
            remaining.append(str(d.relative_to(BASE)))

    if remaining:
        print(f"[WARN] 仍有残留 ({len(remaining)} 项):")
        for r in remaining:
            print(f"  - {r}")
    else:
        print("[OK] 所有历史数据已清空，可进行纯冷启动验证。")

if __name__ == "__main__":
    main()
