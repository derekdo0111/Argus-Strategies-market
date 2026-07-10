"""Wiki 索引维护 — 确定性脚本，零 LLM 调用

扫描 wiki/ 目录下的所有 Markdown 页面，提取元数据，更新 index.md。
不做页面内容修改——只是索引。
"""

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

WIKI_CATEGORIES = ["industries", "hypotheses", "concepts", "comparisons", "synthesis"]


def scan_pages(wiki_dir: Path) -> list[dict]:
    """扫描 wiki/ 下所有 .md 文件，提取元数据。

    Returns:
        [{path, category, title, last_modified, status, excerpt}, ...]
    """
    pages = []
    for category in WIKI_CATEGORIES:
        cat_dir = wiki_dir / category
        if not cat_dir.exists():
            continue
        for md_file in cat_dir.glob("*.md"):
            meta = _extract_meta(md_file, category)
            pages.append(meta)

    # 按修改时间倒序
    pages.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
    return pages


def update_index(wiki_dir: Path) -> None:
    """重建 index.md — 扫描所有页面写入索引

    v0.15: 先按 category 分组，再组内按修改时间倒序。消除重复分组标题。
    """
    pages = scan_pages(wiki_dir)
    index_path = wiki_dir.parent / "index.md"

    lines = [
        "# Prosperity 知识库索引",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> 共 {len(pages)} 页",
        "",
    ]

    # 先按 category 分组，再组内按修改时间倒序（消除重复分组标题）
    pages_by_cat: dict[str, list[dict]] = {}
    for page in pages:
        cat = page["category"]
        pages_by_cat.setdefault(cat, []).append(page)

    cat_names = {
        "industries": "行业",
        "hypotheses": "假设",
        "concepts": "概念",
        "comparisons": "横向对比",
        "synthesis": "综合报告",
    }

    for cat in ["industries", "hypotheses", "concepts", "comparisons", "synthesis"]:
        cat_pages = pages_by_cat.get(cat, [])
        if not cat_pages:
            continue
        # 组内按修改时间倒序
        cat_pages.sort(key=lambda x: x.get("last_modified", ""), reverse=True)

        name = cat_names.get(cat, cat)
        lines.extend(["", f"## {name} ({len(cat_pages)})", ""])

        for page in cat_pages:
            status_mark = {
                "confirmed": "✅", "partial": "⚠️", "disputed": "❌",
                "unverified": "🔍", "overturned": "⚰️", "": ""
            }.get(page.get("status", ""), "")

            lines.append(
                f"- {status_mark} [{page['title']}]({page['path']}) "
                f"— {page.get('excerpt', '')} "
                f"({page['last_modified'][:10]})"
            )

    lines.extend(["", f"*最后更新: {datetime.now().isoformat()}*", ""])

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"Index updated: {len(pages)} pages indexed")


def find_orphans(wiki_dir: Path) -> list[str]:
    """查找孤页：没有被任何其他页面引用的页面"""
    pages = scan_pages(wiki_dir)
    all_paths = {p["path"] for p in pages}

    # 收集所有被引用的路径
    referenced = set()
    for category in WIKI_CATEGORIES:
        cat_dir = wiki_dir / category
        if not cat_dir.exists():
            continue
        for md_file in cat_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            # 匹配 [[page_name]] wiki 链接
            for match in re.finditer(r"\[\[([^\]]+)\]\]", content):
                ref = match.group(1)
                referenced.add(ref)

    orphans = all_paths - referenced
    return sorted(orphans)


def append_log(wiki_dir: Path, entry: str) -> None:
    """追加一行操作日志到 log.md"""
    log_path = wiki_dir.parent / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {entry}\n")


def _extract_meta(file_path: Path, category: str) -> dict:
    """从 Markdown 文件提取元数据"""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return {
            "path": str(file_path.relative_to(file_path.parent.parent.parent)),
            "category": category,
            "title": file_path.stem,
            "last_modified": "",
            "status": "",
            "excerpt": "",
        }

    # 提取标题（第一个 # 行）
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_path.stem

    # 提取状态
    status = ""
    if "✅ CONFIRMED" in content:
        status = "confirmed"
    elif "⚠️ OVERTURNED" in content:
        status = "overturned"
    elif "❌ DISPUTED" in content:
        status = "disputed"
    elif "⚠️ PARTIAL" in content:
        status = "partial"
    elif "🔍 UNVERIFIED" in content:
        status = "unverified"

    # 提取摘要（第一个非标题非空段落前 100 字）
    excerpt = ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            excerpt = stripped[:100]
            break

    stat = file_path.stat()
    return {
        "path": str(file_path.relative_to(file_path.parent.parent.parent)),
        "category": category,
        "title": title,
        "last_modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "status": status,
        "excerpt": excerpt,
    }


def _count(pages: list[dict], category: str) -> int:
    return sum(1 for p in pages if p["category"] == category)
