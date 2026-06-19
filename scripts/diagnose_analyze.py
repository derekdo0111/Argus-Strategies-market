"""
自动诊断脚本：逐步测试分析全流程，定位卡住的环节。
用法: python scripts/diagnose_analyze.py [ts_code]
默认测试: 海澜之家 600398.SH
"""
import sys, os, time, traceback, asyncio

# 确保 backend 在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("diagnose")
logger.setLevel(logging.DEBUG)

TS_CODE = sys.argv[1] if len(sys.argv) > 1 else "600398.SH"
CACHE_DIR = Path(os.path.dirname(__file__)) / ".." / "data" / "stock_cache"
CACHE_DIR = CACHE_DIR.resolve()

PASS = "✅"
FAIL = "❌"
SKIP = "⏭️"

# ============================================================
# Step 1: TushareClient 连接测试
# ============================================================
def step1_tushare_connect():
    logger.info("=" * 60)
    logger.info(f"Step 1: TushareClient 连接测试 → {TS_CODE}")
    logger.info("=" * 60)
    try:
        from app.services.tushare_client import TushareClient
        tc = TushareClient()
        logger.info("  TushareClient 实例化成功")
        
        start = time.time()
        basic = tc.call("stock_basic", ts_code=TS_CODE, fields="ts_code,name")
        elapsed = time.time() - start
        logger.info(f"  stock_basic 调用耗时: {elapsed:.2f}s")
        
        if not basic.empty:
            name = str(basic.iloc[0].get("name", TS_CODE))
            logger.info(f"{PASS} Step 1 通过: {name} ({TS_CODE})")
            return True, name
        else:
            logger.warning(f"{FAIL} Step 1: stock_basic 返回空")
            return False, TS_CODE
    except Exception as e:
        logger.error(f"{FAIL} Step 1 失败: {e}")
        traceback.print_exc()
        return False, TS_CODE


# ============================================================
# Step 2: DataFetcher 数据拉取测试
# ============================================================
def step2_fetch_data(name: str):
    logger.info("=" * 60)
    logger.info(f"Step 2: DataFetcher 数据拉取 → {name} ({TS_CODE})")
    logger.info("=" * 60)
    try:
        from app.services.data_fetcher import DataFetcher
        fetcher = DataFetcher(cache_dir=CACHE_DIR)
        logger.info("  DataFetcher 实例化成功")
        
        start = time.time()
        stats = fetcher.fetch_candidate_data(
            [TS_CODE], force=False,
            name_map={TS_CODE: name},
        )
        elapsed = time.time() - start
        logger.info(f"  拉取耗时: {elapsed:.2f}s")
        logger.info(f"  结果: success={stats.success}, failed={stats.failed}, partial={stats.partial}")
        
        if stats.failed > 0:
            logger.error(f"{FAIL} Step 2 失败: {stats.failed_codes}")
            return False
        
        # 确认 raw_data.yaml 存在
        stock_dir = None
        for entry in CACHE_DIR.iterdir():
            if entry.is_dir() and TS_CODE in entry.name:
                stock_dir = entry
                break
        
        if stock_dir is None:
            logger.error(f"{FAIL} Step 2: 找不到 {TS_CODE} 缓存目录")
            return False
        
        raw_path = stock_dir / "raw_data.yaml"
        if not raw_path.exists():
            logger.error(f"{FAIL} Step 2: raw_data.yaml 不存在")
            return False
        
        logger.info(f"{PASS} Step 2 通过: raw_data.yaml → {raw_path}")
        return True
    except Exception as e:
        logger.error(f"{FAIL} Step 2 失败: {e}")
        traceback.print_exc()
        return False


# ============================================================
# Step 3: CQ + PR 计算测试
# ============================================================
def step3_compute():
    logger.info("=" * 60)
    logger.info(f"Step 3: CQ 现金质量 + PR 穿透回报率计算")
    logger.info("=" * 60)
    try:
        from app.strategies.turtle.cash_quality import CashQualityGate
        from app.strategies.turtle.penetration_return import PenetrationReturnCalculator
        
        import yaml
        
        # 找 raw_data.yaml
        stock_dir = None
        for entry in CACHE_DIR.iterdir():
            if TS_CODE in entry.name:
                stock_dir = entry
                break
        
        raw_path = stock_dir / "raw_data.yaml"
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
        
        logger.info(f"  raw_data 加载成功，keys: {list(raw_data.keys()) if raw_data else 'None'}")
        
        # CQ 计算
        start = time.time()
        try:
            cq = CashQualityGate(raw_data)
            result = cq.evaluate()
            elapsed = time.time() - start
            logger.info(f"  CQ 计算耗时: {elapsed:.2f}s")
            logger.info(f"  CQ 结果: pass={result.get('pass')}, score={result.get('score')}")
            logger.info(f"  CQ 维度明细: {result.get('dimensions', {})}")
        except Exception as e:
            logger.warning(f"  CQ 计算异常: {e}")
        
        # PR 计算
        start = time.time()
        try:
            pr = PenetrationReturnCalculator(raw_data)
            result = pr.evaluate()
            elapsed = time.time() - start
            logger.info(f"  PR 计算耗时: {elapsed:.2f}s")
            logger.info(f"  PR 结果: pass={result.get('pass')}, score={result.get('score')}")
        except Exception as e:
            logger.warning(f"  PR 计算异常: {e}")
        
        logger.info(f"{PASS} Step 3 通过")
        return True
    except Exception as e:
        logger.error(f"{FAIL} Step 3 失败: {e}")
        traceback.print_exc()
        return False


# ============================================================
# Step 4: Coordinator 全流程测试
# ============================================================
async def step4_coordinator_full():
    logger.info("=" * 60)
    logger.info(f"Step 4: Coordinator 全流程测试 → {TS_CODE}")
    logger.info("=" * 60)
    try:
        from app.strategies.turtle.coordinator import TurtleCoordinator
        
        coordinator = TurtleCoordinator(cache_dir=CACHE_DIR)
        logger.info("  TurtleCoordinator 实例化成功")
        
        def status_cb(status, message, progress):
            ts = time.strftime("%H:%M:%S")
            logger.info(f"  [{ts}] [{progress}%] {status}: {message}")
        
        start = time.time()
        await coordinator.run_single_stock_full(
            ts_code=TS_CODE,
            force=False,
            status_callback=status_cb,
        )
        elapsed = time.time() - start
        logger.info(f"{PASS} Step 4 通过: 全流程耗时 {elapsed:.2f}s")
        return True
    except Exception as e:
        logger.error(f"{FAIL} Step 4 失败: {e}")
        traceback.print_exc()
        return False


# ============================================================
# Main
# ============================================================
async def main():
    logger.info("🔍 开始自动诊断...")
    logger.info(f"  目标股票: {TS_CODE}")
    logger.info(f"  缓存目录: {CACHE_DIR}")
    logger.info("")
    
    results = {}
    
    # Step 1
    ok, name = step1_tushare_connect()
    results["TushareClient"] = ok
    if not ok:
        logger.error("⛔ Tushare 连接失败，终止诊断")
        return
    
    # Step 2
    ok = step2_fetch_data(name)
    results["DataFetcher"] = ok
    if not ok:
        logger.error("⛔ 数据拉取失败，终止诊断")
        return
    
    # Step 3
    ok = step3_compute()
    results["CQ+PR"] = ok
    
    # Step 4
    ok = await step4_coordinator_full()
    results["Coordinator"] = ok
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 诊断结果汇总")
    logger.info("=" * 60)
    for step_name, passed in results.items():
        icon = PASS if passed else FAIL
        logger.info(f"  {icon} {step_name}")
    
    all_pass = all(results.values())
    if all_pass:
        logger.info(f"\n{PASS} 全部通过！问题可能在前端或网络层面。")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.info(f"\n{FAIL} 失败环节: {', '.join(failed)}")


if __name__ == "__main__":
    asyncio.run(main())
