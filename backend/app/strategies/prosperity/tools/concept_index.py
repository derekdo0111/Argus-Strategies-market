"""概念板块本地索引 — Tushare ths_index 全量拉取 + rapidfuzz 模糊搜索

定位：基础设施组件，不是 Wiki 研究内容。
缓存：data/concept_index.yaml，24h TTL。
消费者：
- industry_metrics.py get_industry_ts_codes() — 信源0 快速查找
- verify_agent.py 反例搜索 — 概念名→板块代码

相比现有 get_industry_ts_codes() 信源4（逐次查 ths_index + ths_member）：
- 预建全量索引（~500 个概念板块）→ 一次 API 调用
- rapidfuzz 模糊匹配 → 远优于 str.contains()
- 24h 缓存 → 后续查询零 API 调用
"""

import logging
import math
import time
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz, process  # type: ignore

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# 缓存路径 & TTL
# ═══════════════════════════════════════════════

CACHE_FILE = Path(__file__).parent.parent.parent.parent.parent.parent / "data" / "concept_index.yaml"
CACHE_TTL_SECONDS = 24 * 3600  # 24 小时


# ═══════════════════════════════════════════════
# 内存缓存（全局）
# ═══════════════════════════════════════════════

_index_cache: Optional[list[dict]] = None       # [{name, ts_code, count, exchange, type}, ...]
_index_cache_time: float = 0                     # epoch 时间戳
_name_list: Optional[list[str]] = None           # 仅名字列表，rapidfuzz 快速查询用


def _is_cache_valid() -> bool:
    """YAML 文件在有效期内"""
    if not CACHE_FILE.exists():
        return False
    mtime = CACHE_FILE.stat().st_mtime
    return (time.time() - mtime) < CACHE_TTL_SECONDS


def _load_from_yaml() -> list[dict]:
    """从 YAML 加载索引"""
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    concepts = data.get("concepts", [])
    return concepts


def _save_to_yaml(concepts: list[dict]):
    """保存索引到 YAML"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "meta": {
            "source": "Tushare ths_index(type=N)",
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total": len(concepts),
            "ttl_hours": CACHE_TTL_SECONDS // 3600,
        },
        "concepts": concepts,
    }
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info(f"concept_index: 写入 {len(concepts)} 个概念板块 → {CACHE_FILE}")


def build(force: bool = False) -> int:
    """从 Tushare ths_index 全量拉取概念板块列表 → 写入 YAML

    Args:
        force: 是否强制重建（忽略 TTL）

    Returns:
        概念板块数量
    """
    if not force and _is_cache_valid():
        concepts = _load_from_yaml()
        logger.info(f"concept_index: 缓存有效，{len(concepts)} 个概念板块，跳过重建")
        return len(concepts)

    from app.services.tushare_client import TushareClient

    client = TushareClient()
    logger.info("concept_index: 从 Tushare ths_index(type=N) 全量拉取概念板块...")
    df = client.get_ths_index(type="N")

    if df is None or df.empty:
        logger.warning("concept_index: ths_index 返回空，保留旧索引")
        if CACHE_FILE.exists():
            old = _load_from_yaml()
            return len(old)
        return 0

    # 提取关键字段
    concepts = []
    for _, row in df.iterrows():
        raw_count = row.get("count", 0)
        if raw_count is None or (isinstance(raw_count, float) and math.isnan(raw_count)):
            count = 0
        else:
            count = int(raw_count)
        concepts.append({
            "ts_code": str(row.get("ts_code", "")),
            "name": str(row.get("name", "")),
            "count": count,
            "exchange": str(row.get("exchange", "")),
        })

    # 去重（按 name）
    seen: set[str] = set()
    unique = []
    for c in concepts:
        if c["name"] not in seen:
            seen.add(c["name"])
            unique.append(c)

    _save_to_yaml(unique)

    # 更新内存缓存
    global _index_cache, _index_cache_time, _name_list
    _index_cache = unique
    _index_cache_time = time.time()
    _name_list = [c["name"] for c in unique]

    logger.info(f"concept_index: 构建完成，{len(unique)} 个概念板块")
    return len(unique)


def load(force_refresh: bool = False) -> list[dict]:
    """加载概念板块索引（优先内存 → YAML → API）

    Args:
        force_refresh: 强制刷新

    Returns:
        [{name, ts_code, count, exchange}, ...]
    """
    global _index_cache, _index_cache_time, _name_list

    # 内存缓存命中
    if _index_cache is not None and not force_refresh:
        if time.time() - _index_cache_time < CACHE_TTL_SECONDS:
            return _index_cache

    # YAML 缓存命中
    if CACHE_FILE.exists() and not force_refresh:
        if _is_cache_valid():
            concepts = _load_from_yaml()
            _index_cache = concepts
            _index_cache_time = time.time()
            _name_list = [c["name"] for c in concepts]
            return concepts

    # 全量重建
    build(force=True)
    return _index_cache or []


def search(name: str, threshold: int = 70, limit: int = 5) -> list[tuple[str, str, float]]:
    """按概念名模糊搜索 — rapidfuzz 中文友好

    Args:
        name: 搜索关键词，如 "人工智能"、"新能源"、"低空经济"
        threshold: 相似度阈值 (0-100)，默认 70
        limit: 最多返回条数

    Returns:
        [(概念名, ts_code, 相似度), ...] 按相似度降序
        例: [("人工智能", "885728.TI", 100.0), ("AI智能体", "886068.TI", 76.5)]
    """
    concepts = load()
    if not concepts:
        return []

    name_list = [c["name"] for c in concepts]

    # rapidfuzz 批量匹配
    results = process.extract(
        name,
        name_list,
        scorer=fuzz.WRatio,
        score_cutoff=threshold,
        limit=limit,
    )

    # 还原 ts_code
    output = []
    for match_name, score, _ in results:
        for c in concepts:
            if c["name"] == match_name:
                output.append((match_name, c["ts_code"], score))
                break

    if output:
        logger.debug(
            f"concept_index.search('{name}'): "
            f"{output[0][0]} ({output[0][1]}, {output[0][2]:.0f}%)"
        )
    return output


def resolve(name: str, threshold: int = 70) -> list[str]:
    """一键搜索 + 获取概念板块成分股

    v0.23.7: 不再对多个匹配概念求并集。精确命中（score=100）只用那一个概念，
    模糊匹配只用最佳匹配。避免"人工智能"→AI智能体+AIGC概念并集导致 1074 只。

    Args:
        name: 概念名称
        threshold: 模糊搜索阈值

    Returns:
        [ts_code, ...] 成分股代码列表
    """
    matches = search(name, threshold=threshold, limit=3)
    if not matches:
        return []

    # ── 精确命中 / 最佳匹配 ──
    exact = [m for m in matches if m[2] == 100.0]
    best = exact[0] if exact else matches[0]
    concept_name, concept_code, score = best

    from app.services.tushare_client import TushareClient

    client = TushareClient()

    try:
        members = client.get_ths_member(ts_code=concept_code)
        if members is not None and not members.empty:
            col = "con_code" if "con_code" in members.columns else "ts_code"
            stocks = sorted(members[col].tolist())
            logger.info(
                f"concept_index.resolve('{name}'): "
                f"'{concept_name}' ({concept_code}, {score:.0f}%) → {len(stocks)} 只股票"
            )
            return stocks
    except Exception as e:
        logger.warning(f"concept_index.resolve: ths_member({concept_code}) 失败: {e}")

    return []


def suggest_subconcepts(main_name: str, max_suggestions: int = 6,
                         min_members: int = 15) -> list[dict]:
    """为超限概念板块推荐子板块（用于交互式选择）

    策略：rapidfuzz 名称相似度搜索 → 过滤自身 + 成分股数必须 < 主概念 + ≥ min_members
    按成分股数降序排列（保留最聚焦的子概念在前）。

    Args:
        main_name: 主概念名称，如 "人工智能"
        max_suggestions: 最多推荐个数
        min_members: 子板块最少成分股数（过低无分析价值）

    Returns:
        [{name, ts_code, count, score}, ...] 按成分股数降序
    """
    concepts = load()
    if not concepts:
        return []

    # 找到主概念的成分股数和 ts_code
    main_count = 0
    main_ts_code = ""
    for c in concepts:
        if c["name"] == main_name:
            main_count = c["count"]
            main_ts_code = c["ts_code"]
            break

    if main_count == 0:
        logger.warning(f"suggest_subconcepts: '{main_name}' not found in index")
        return []

    # rapidfuzz 搜索相关概念（阈值较低，保证召回）
    name_list = [c["name"] for c in concepts]
    results = process.extract(
        main_name,
        name_list,
        scorer=fuzz.WRatio,
        score_cutoff=50,
        limit=min(max_suggestions * 5, 50),
    )

    seen: set[str] = {main_name}
    suggestions: list[dict] = []
    for match_name, score, _ in results:
        if match_name in seen:
            continue
        seen.add(match_name)

        for c in concepts:
            if c["name"] == match_name:
                # 必须是子板块：成分股少于主概念
                if c["count"] >= main_count:
                    continue
                # 至少有一定数量的成分股才有分析价值
                if c["count"] < min_members:
                    continue
                # 排除代码相同的主概念别名
                if c["ts_code"] == main_ts_code:
                    continue
                suggestions.append({
                    "name": c["name"],
                    "ts_code": c["ts_code"],
                    "count": c["count"],
                    "score": round(score, 1),
                })
                break

        if len(suggestions) >= max_suggestions:
            break

    # 按成分股数降序排列
    suggestions.sort(key=lambda x: x["count"], reverse=True)

    if suggestions:
        logger.debug(
            f"suggest_subconcepts('{main_name}'): "
            f"{len(suggestions)} candidates, top={suggestions[0]['name']}"
        )
    return suggestions


def get_name_list() -> list[str]:
    """获取全部概念名称列表（用于 UI 自动补全等）"""
    concepts = load()
    return [c["name"] for c in concepts]


def index_stats() -> dict:
    """返回索引统计信息"""
    concepts = load()
    return {
        "total": len(concepts),
        "source": "Tushare ths_index(type=N)",
        "cache_file": str(CACHE_FILE),
        "cache_ttl_hours": CACHE_TTL_SECONDS // 3600,
    }
