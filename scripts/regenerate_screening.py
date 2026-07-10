"""单独重跑 Screening → Report 两阶段（不跑全流程）

用法：
    python scripts/regenerate_screening.py [行业名] [--force]

    默认行业：可控核聚变
    --force：跳过 cooldown 检查

    流程：
    1. 加载 raw/{行业}/01_search_*.yaml → search_result
    2. 从 DB 查询最新 session 的已验证 hypotheses → verification dict
    3. 运行 ScreeningAgent.screen() → 重写 stock_pool.yaml
    4. 运行 ReportAgent.generate() → 重写 wiki/synthesis/*.md
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 确保 backend 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.core.config import settings
from app.strategies.prosperity.models import (
    get_session as get_db_session,
    ResearchSession,
    Industry,
    Hypothesis,
    init_db,
    migrate_v2,
    migrate_v3,
    migrate_v4,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def load_search_result(data_dir: Path, industry_name: str) -> dict:
    """从 raw/{industry}/01_search_*.yaml 加载搜索缓存"""
    raw_dir = data_dir / "raw" / industry_name
    if not raw_dir.exists():
        print(f"[ERROR] raw dir not found: {raw_dir}")
        sys.exit(1)

    search_files = sorted(raw_dir.glob("01_search_*.yaml"))
    if not search_files:
        print(f"[ERROR] no search cache found in {raw_dir}")
        sys.exit(1)

    import yaml

    latest = search_files[-1]
    print(f"   -> 加载搜索缓存: {latest.name}")
    with open(latest, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_verified_hypotheses(engine, industry_name: str) -> list[dict]:
    """从 DB 查询最新 session 的已验证假设，并从 wiki .md 补充陈述/推理链/上游"""
    import re

    db = get_db_session(engine)
    try:
        # 找该行业最新 session
        industry = db.query(Industry).filter_by(name=industry_name).first()
        if not industry:
            print(f"[WARN] Industry '{industry_name}' not found in DB, no hypotheses loaded")
            return []

        latest_session = (
            db.query(ResearchSession)
            .filter_by(industry_id=industry.id, status="completed")
            .order_by(ResearchSession.id.desc())
            .first()
        )

        if not latest_session:
            print(f"[WARN] No completed session for {industry_name}, trying any session...")
            latest_session = (
                db.query(ResearchSession)
                .filter_by(industry_id=industry.id)
                .order_by(ResearchSession.id.desc())
                .first()
            )

        if not latest_session:
            print(f"[WARN] No session found for {industry_name}")
            return []

        hypotheses = (
            db.query(Hypothesis)
            .filter_by(session_id=latest_session.id)
            .all()
        )

        # ── 步骤 1: 从 DB 构建基础数据 (keyed by title) ──
        db_data: dict[str, dict] = {}
        for h in hypotheses:
            db_data[h.title] = {
                "db_id": h.id,
                "status": h.status,
                "sentiment": h.sentiment or "neutral",
                "chain_level": h.chain_level or 0,
                "time_horizon": h.time_horizon or "",
                "causality_strength": h.causality_strength or "moderate",
                "causality_note": h.causality_note or "",
                "confidence": h.confidence or "medium",
                "investment_implication": h.wiki_path or "",
            }

        # ── 步骤 2: 解析 wiki/hypotheses/{行业}-*.md 获取陈述/推理链/上游/ID ──
        data_dir = settings.PROSPERITY_DATA_DIR
        wiki_hyp_dir = data_dir / "wiki" / "hypotheses"
        wiki_data: dict[str, dict] = {}  # title → {id, statement, reasoning, derives_from, ...}

        if wiki_hyp_dir.exists():
            for md_file in sorted(wiki_hyp_dir.glob(f"{industry_name}-*.md")):
                content = md_file.read_text(encoding="utf-8")

                # 从 h1 标题提取假设名: # 📊 [现状诊断] 项目投招标高峰启动
                title_match = re.search(r"^# .*?\]\s*(.+)$", content, re.MULTILINE)
                # 从元信息行提取 ID: > 行业: XX | ID: `H0-1` | 层级: L0
                id_match = re.search(r"ID:\s*`([^`]+)`", content)
                # 陈述 / 推理链
                stmt_match = re.search(r"\*\*陈述\*\*:\s*(.+)$", content, re.MULTILINE)
                reason_match = re.search(r"\*\*推理链\*\*:\s*(.+)$", content, re.MULTILINE)
                # 上游假设（L1+ 才有）: **上游假设**: `H2-1`
                upstream_match = re.search(r"\*\*上游假设\*\*:\s*(.+)$", content, re.MULTILINE)
                # 时间窗口: **时间窗口**: ⏱️ 2026-2028
                time_match = re.search(r"\*\*时间窗口\*\*:\s*⏱️\s*(.+)$", content, re.MULTILINE)

                # 关键跟踪指标
                key_indicators = []
                ki_block = re.search(
                    r"\*\*关键跟踪指标\*\*:\s*\n((?:\s*-.*(?:\n|$))*)", content
                )
                if ki_block:
                    for ki_line in ki_block.group(1).strip().split("\n"):
                        ki_name = re.match(r"\s*-\s*(.+?)\s*\(巡检:", ki_line)
                        ki_freq = re.search(r"巡检:\s*(\w+)", ki_line)
                        if ki_name:
                            key_indicators.append({
                                "name": ki_name.group(1).strip(),
                                "frequency": ki_freq.group(1) if ki_freq else "monthly",
                            })

                # 投资含义（仅 L3）
                imp_block = re.search(
                    r"## 投资含义\s*\n+(.+?)(?:\n##|\n---|\Z)", content, re.DOTALL
                )
                investment_implication = imp_block.group(1).strip() if imp_block else ""

                title = title_match.group(1).strip() if title_match else md_file.stem
                wiki_data[title] = {
                    "id": id_match.group(1).strip() if id_match else "",
                    "statement": stmt_match.group(1).strip() if stmt_match else "",
                    "reasoning": reason_match.group(1).strip() if reason_match else "",
                    "derives_from": (
                        [x.strip().strip("`") for x in upstream_match.group(1).split(",")]
                        if upstream_match
                        else []
                    ),
                    "time_window": time_match.group(1).strip() if time_match else "",
                    "key_indicators": key_indicators,
                    "investment_implication": investment_implication,
                }

        # ── 步骤 3: 合并 DB + wiki 数据 ──
        result = []
        for title, d in db_data.items():
            w = wiki_data.get(title, {})
            result.append({
                # 使用 wiki ID（与 mermaid 箭头上游 ID 匹配），fallback 为 DB 自增 ID
                "id": w.get("id", f"H{d['chain_level']}-{d['db_id']}"),
                "title": title,
                "statement": w.get("statement", ""),
                "reasoning": w.get("reasoning", ""),
                "status": d["status"],
                "sentiment": d["sentiment"],
                "chain_level": d["chain_level"],
                "derives_from": w.get("derives_from", []),
                "time_horizon": w.get("time_window", d["time_horizon"]),
                "investment_implication": w.get("investment_implication", d["investment_implication"]),
                "key_indicators": w.get("key_indicators", []),
                "causality_strength": d["causality_strength"],
                "causality_note": d["causality_note"],
                "confidence": d["confidence"],
            })

        n_with_stmt = sum(1 for r in result if r["statement"])
        print(f"   -> 加载 {len(result)} 条已验证假设 (session {latest_session.id})")
        print(f"   -> 其中 {n_with_stmt}/{len(result)} 条有陈述/推理链 (来自 wiki .md)")
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="单独重跑 Screening + Report")
    parser.add_argument(
        "industry",
        nargs="?",
        default="可控核聚变",
        help="行业名称（默认：可控核聚变）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="不检查 cooldown",
    )
    args = parser.parse_args()

    industry_name = args.industry
    data_dir = settings.PROSPERITY_DATA_DIR

    t_start = datetime.now()
    print(f"\n{'=' * 60}")
    print(f"  Regenerate Screening + Report: {industry_name}")
    print(f"  {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  预计耗时: 2~5 分钟（LLM 调用 × 2）")
    print(f"{'=' * 60}\n", flush=True)

    # 1. 初始化 DB
    print("[1/5] 初始化数据库...", flush=True)
    t1 = datetime.now()
    engine = init_db()
    try:
        migrate_v2(engine)
        migrate_v3(engine)
        migrate_v4(engine)
    except Exception as e:
        logger.info(f"Migration skipped (already applied): {e}")
    print(f"   -> 数据库就绪 ({(datetime.now() - t1).total_seconds():.1f}s)", flush=True)

    # 2. 加载 search_result
    print(f"\n[2/5] 加载搜索数据...", flush=True)
    t2 = datetime.now()
    search_result = load_search_result(data_dir, industry_name)
    n_results = len(search_result.get("results", []))
    print(f"   -> {n_results} 条搜索结果 ({(datetime.now() - t2).total_seconds():.1f}s)", flush=True)

    # 3. 加载 verified hypotheses
    print(f"\n[3/5] 加载已验证假设...", flush=True)
    t3 = datetime.now()
    verified_hypotheses = load_verified_hypotheses(engine, industry_name)
    verification = {
        "industry": industry_name,
        "session_id": 0,  # dummy
        "verified_count": len(verified_hypotheses),
        "statuses": {},
        "hypotheses": verified_hypotheses,
        "chain_results": [],
    }

    # 如果没有假设，尝试从 wiki hypotheses yaml 加载
    if not verified_hypotheses:
        wiki_hyp_dir = data_dir / "wiki" / "hypotheses"
        hy_file = wiki_hyp_dir / f"{industry_name}.yaml"
        if hy_file.exists():
            import yaml
            with open(hy_file, "r", encoding="utf-8") as f:
                wiki_hy = yaml.safe_load(f)
            if isinstance(wiki_hy, list):
                verified_hypotheses = wiki_hy
                verification["hypotheses"] = verified_hypotheses
                verification["verified_count"] = len(verified_hypotheses)
                print(f"   -> 从 wiki 加载 {len(verified_hypotheses)} 条假设")
        else:
            print("   -> [WARN] 无假设数据，方向匹配将使用默认值")
    print(f"   -> {(datetime.now() - t3).total_seconds():.1f}s", flush=True)

    # 4. Screening
    print(f"\n[4/5] 运行 ScreeningAgent（最慢，含 2 次 LLM 调用 + Tushare 数据拉取）...", flush=True)
    t4 = datetime.now()
    from app.strategies.prosperity.agents.screening_agent import ScreeningAgent

    screen_agent = ScreeningAgent(data_dir)
    screening_result = screen_agent.screen(
        industry_name=industry_name,
        session_id=0,
        verification=verification,
        search_result=search_result,
    )
    n_stocks = len(screening_result.get("stock_pool", []))
    elapsed4 = (datetime.now() - t4).total_seconds()
    print(f"   -> 股池: {n_stocks} 只 ({elapsed4:.0f}s)", flush=True)

    # 5. Report
    print(f"\n[5/5] 运行 ReportAgent（LLM 生成报告）...", flush=True)
    t5 = datetime.now()
    from app.strategies.prosperity.agents.report_agent import ReportAgent

    report_agent = ReportAgent(data_dir)
    # 检查上次研究日期计算 study_count
    wiki_ind_dir = data_dir / "wiki" / "industries"
    ind_page = wiki_ind_dir / f"{industry_name}.md"
    study_count = 0
    if ind_page.exists():
        content = ind_page.read_text(encoding="utf-8")
        import re
        study_count = len(re.findall(r"- \[\d{4}-\d{2}-\d{2}\]", content))

    report_result = report_agent.generate(
        industry_name=industry_name,
        session_id=0,
        verification=verification,
        screening_result=screening_result,
        study_count=max(study_count, 1),
    )
    elapsed5 = (datetime.now() - t5).total_seconds()

    rating = report_result.get("rating", "?")
    report_path = report_result.get("report_path", "")
    print(f"   -> 评级: {rating} ({elapsed5:.0f}s)", flush=True)
    print(f"   -> 报告: {report_path}", flush=True)

    total_elapsed = (datetime.now() - t_start).total_seconds()
    print(f"\n{'=' * 60}", flush=True)
    print(f"  [OK] 完成！股池 {n_stocks} 只 → 评级 {rating}")
    print(f"  总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f}min)")
    print(f"{'=' * 60}\n", flush=True)


if __name__ == "__main__":
    main()
