"""龟龟策略全量刷新脚本

用法:
    cd backend
    python -m scripts.run_turtle_refresh                  # 完整刷新（选股+拉取+计算+门控）
    python -m scripts.run_turtle_refresh --dry-run        # 只跑选股器，不拉取数据
    python -m scripts.run_turtle_refresh --skip-fetch     # 跳过数据拉取，用已有缓存
    python -m scripts.run_turtle_refresh --compute-only   # 使用所有缓存，只跑计算 (~30s)
    python -m scripts.run_turtle_refresh --force          # 强制重拉，忽略所有缓存
    python -m scripts.run_turtle_refresh --stock 000001.SZ  # 只拉取单只股票
"""

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

# 添加 backend 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# Windows GBK 终端兼容: 重定向 stdout 为 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from app.core.config import settings
from app.core.logging import setup_logging, set_trace_id
from app.services.tushare_client import TushareClient
from app.services.data_fetcher import DataFetcher


async def run_full_refresh(dry_run: bool = False, skip_fetch: bool = False,
                          compute_only: bool = False, force: bool = False):
    """执行全量刷新"""
    from app.strategies.turtle.coordinator import TurtleCoordinator

    coordinator = TurtleCoordinator(
        cache_dir=settings.TURTLE_CACHE_DIR,
        rule_version=settings.TURTLE_RULE_VERSION,
        risk_free_rate=settings.TURTLE_RISK_FREE_RATE,
    )

    # Step 0 + Step 1: 拉取全A股 + 选股
    fetcher = DataFetcher()
    print("📡 拉取全A股基础信息...")
    stocks_df = fetcher.fetch_stock_basic(force=force)
    if stocks_df.empty:
        print("❌ stock_basic 拉取失败，请检查 TUSHARE_TOKEN")
        return

    stocks = stocks_df.to_dict("records")
    print(f"✅ 全A股: {len(stocks)} 只")

    if dry_run:
        from app.strategies.turtle.screener import TurtleScreener
        screener = TurtleScreener()
        candidates, stats = screener.screen(stocks)
        print(screener.get_fail_summary(stats))
        return

    # 完整流程
    fetch_data = not skip_fetch
    if compute_only:
        fetch_data = False
        print(f"\n🚀 计算模式: 使用所有缓存，只跑计算 (~30s)...", flush=True)

    print(f"\n🚀 开始全量刷新流程...", flush=True)
    print(f"📊 候选池由 coordinator 自动生成，数据将拉取至 {settings.TURTLE_CACHE_DIR}", flush=True)
    pool = await coordinator.run_full_refresh(
        stocks=stocks,
        fetch_data=fetch_data,
        force=force,
    )

    print(f"\n🏆 股池: {len(pool)} 只（按穿透回报率降序）")
    if pool:
        print(f"\n{'排名':<4} {'代码':<12} {'名称':<10} {'PR':>8} {'PE':>8} {'市值':>8}")
        print("-" * 55)
        for i, s in enumerate(pool[:30], 1):
            print(
                f"{i:<4} {s['ts_code']:<12} {s['name']:<10} "
                f"{s['pr']:>7.2f}% {s['pe']:>7.1f} {s['market_cap']:>7.0f}亿"
            )

    # 输出 JSON 供后续使用
    output_path = settings.TURTLE_CACHE_DIR / "pool.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)
    print(f"\n📁 股池已保存: {output_path}")


async def fetch_single_stock(ts_code: str):
    """拉取单只股票数据"""
    print(f"📡 拉取 {ts_code} 全量数据...")
    fetcher = DataFetcher()
    # 尝试从缓存读取中文名
    name = ""
    stock_basic_path = settings.TURTLE_CACHE_DIR / "_stock_basic_cache.parquet"
    if stock_basic_path.exists():
        import pandas as pd
        try:
            df = pd.read_parquet(stock_basic_path)
            row = df[df["ts_code"] == ts_code]
            if not row.empty:
                name = str(row.iloc[0].get("name", ""))
        except Exception:
            pass
    completeness = fetcher.fetch_single_stock(ts_code, name=name)
    print(f"✅ {ts_code}: {completeness}")

    # 查看缓存文件（兼容新旧命名）
    safe_name = name.replace("/", "-").replace("\\", "-") if name else ""
    raw_path = settings.TURTLE_CACHE_DIR / f"{safe_name}_{ts_code}" / "raw_data.yaml"
    if not raw_path.exists():
        raw_path = settings.TURTLE_CACHE_DIR / ts_code / "raw_data.yaml"
    if raw_path.exists():
        import yaml
        with open(raw_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        years = len(data.get("annual_financials", []))
        div_count = len(data.get("dividend_history", []))
        rep_count = len(data.get("repurchase_history", []))
        print(f"  财务年份: {years}, 分红记录: {div_count}, 回购记录: {rep_count}")
        print(f"  市值: {data['basic_info'].get('total_mv', 0)}亿")
        print(f"  PE: {data['basic_info'].get('pe', 0)}, PB: {data['basic_info'].get('pb', 0)}")


async def main():
    parser = argparse.ArgumentParser(description="龟龟策略全量刷新")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只跑选股器，不拉取数据"
    )
    parser.add_argument(
        "--skip-fetch", action="store_true",
        help="跳过数据拉取，使用已有缓存计算"
    )
    parser.add_argument(
        "--compute-only", action="store_true",
        help="使用所有缓存，只跑计算 (含L0+L1+L2缓存)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="强制重拉，忽略所有缓存"
    )
    parser.add_argument(
        "--stock", type=str, default="",
        help="只拉取单只股票，如 000001.SZ"
    )
    args = parser.parse_args()

    setup_logging()
    set_trace_id()

    if args.stock:
        await fetch_single_stock(args.stock)
    else:
        await run_full_refresh(
            dry_run=args.dry_run,
            skip_fetch=args.skip_fetch,
            compute_only=args.compute_only,
            force=args.force,
        )


if __name__ == "__main__":
    asyncio.run(main())
