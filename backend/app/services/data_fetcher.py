"""数据拉取编排服务

协调 Tushare API 调用，按批次拉取全量数据，
写入 stock_cache/{ts_code}/raw_data.yaml。
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import numpy as np
import yaml

from app.services.tushare_client import TushareClient
from app.core.config import settings
from app.core.logging import get_trace_id

logger = logging.getLogger(__name__)

# 单次批量查询最大股票数（Tushare 限制）
BATCH_SIZE = 50
# 拉取财务数据的起始年份
FINANCIAL_START_YEAR = 2014


@dataclass
class FetchStats:
    """拉取统计"""
    total: int = 0
    success: int = 0
    failed: int = 0
    partial: int = 0
    failed_codes: list[str] = field(default_factory=list)
    partial_codes: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    @property
    def success_rate(self) -> float:
        return self.success / max(self.total, 1) * 100

    def summary(self) -> str:
        return (
            f"拉取完成: {self.success}/{self.total} 成功 ({self.success_rate:.1f}%), "
            f"{self.partial} 不完整, {self.failed} 失败"
        )


class DataFetcher:
    """全量数据拉取器

    对候选池中的每只股票:
    1. 拉取财务三表 (income, balance_sheet, cashflow)
    2. 拉取财务指标 (fina_indicator)
    3. 拉取分红数据 (dividend)
    4. 拉取回购数据 (repurchase)
    5. 拉取日线行情 (daily + daily_basic)
    6. 写入 raw_data.yaml
    """

    @staticmethod
    def _safe_float(val, default: float = 0.0, field_name: str = "") -> float:
        """NaN-safe float 转换：NaN/None → default

        None 时输出 WARNING 日志，防止字段缺失被静默兜底为 0。
        """
        if val is None:
            if field_name:
                logger.warning(f"_safe_float: {field_name} is None → default={default}")
            return default
        try:
            v = float(val)
            return v if pd.notna(v) else default
        except (ValueError, TypeError):
            return default

    # 必拉字段 — 缺失任一项视为 partial
    REQUIRED_TABLES = [
        "income",
        "balance_sheet",
        "cashflow",
        "fina_indicator",
        "daily_basic",
    ]

    def __init__(
        self,
        client: Optional[TushareClient] = None,
        cache_dir: Optional[Path] = None,
    ):
        self.client = client or TushareClient()
        self.cache_dir = cache_dir or settings.STOCK_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.trace_id = get_trace_id()

    def fetch_stock_basic(self, force: bool = False) -> pd.DataFrame:
        """拉取全A股基础信息 + 最新指标，用于选股器输入

        L0 缓存: 同日拉取过则从 _stock_basic_cache.parquet 直接加载，
        避免每次测试都走 ~3min API 调用。

        Args:
            force: 强制忽略缓存，重新拉取

        Returns:
            DataFrame with columns needed by screener
        """
        cache_path = self.cache_dir / "_stock_basic_cache.parquet"
        today_str = datetime.now().strftime("%Y%m%d")

        # 检查 L0 缓存
        if not force and cache_path.exists():
            try:
                cached = pd.read_parquet(cache_path)
                cache_date = cached.attrs.get("cache_date", "")
                if cache_date == today_str:
                    logger.info(f"L0缓存命中: {len(cached)} 只 (date={cache_date})")
                    print(f"[L0 Cache] Hit: {len(cached)} stocks", flush=True)
                    return cached
                else:
                    logger.info(f"L0缓存过期 (cache={cache_date}, today={today_str})，重新拉取")
            except Exception as e:
                logger.warning(f"L0缓存加载失败: {e}，重新拉取")

        logger.info("拉取全A股基础信息...")
        basic = self.client.get_stock_basic(list_status="L")
        if basic.empty:
            logger.error("stock_basic 拉取失败")
            return pd.DataFrame()

        logger.info(f"全A股上市: {len(basic)} 只")

        # Step 1: 一次性拉取全市场 daily_basic（市值、PE、PB、股息率）
        daily_df = self._fetch_all_daily_basic()
        if not daily_df.empty:
            # total_mv 原始单位是万元，转为亿元与 screener 阈值对齐
            daily_df["total_mv"] = daily_df["total_mv"] / 10000
            if "circ_mv" in daily_df.columns:
                daily_df["circ_mv"] = daily_df["circ_mv"] / 10000

        # Step 2: 批量拉取 fina_indicator（ROE、毛利率、负债率等）
        fina_df = self._fetch_all_fina_indicator(basic["ts_code"].tolist())

        # Merge
        result = basic
        if not daily_df.empty:
            result = result.merge(
                daily_df[["ts_code", "total_mv", "circ_mv", "pe", "pb", "dv_ratio"]],
                on="ts_code", how="left",
            )
            # dv_ratio → dividend_yield (Tushare dv_ratio 是百分比值)
            result["dividend_yield"] = result["dv_ratio"].fillna(0)

        if not fina_df.empty:
            result = result.merge(
                fina_df[["ts_code", "roe", "gross_margin", "debt_ratio"]],
                on="ts_code", how="left",
            )

        # 填充缺失值为 0
        for col in ["total_mv", "pe", "pb", "roe", "dividend_yield",
                     "gross_margin", "debt_ratio"]:
            if col in result.columns:
                result[col] = result[col].fillna(0)

        logger.info(f"基础信息+指标: {len(result)} 只")

        # 写入 L0 缓存
        try:
            result.attrs["cache_date"] = today_str
            result.to_parquet(cache_path, index=False)
            logger.info(f"L0缓存已写入: {cache_path}")
        except Exception as e:
            logger.warning(f"L0缓存写入失败: {e}")

        return result

    def _fetch_all_daily_basic(self) -> pd.DataFrame:
        """一次性拉取全市场最新 daily_basic（指定最新交易日）"""
        import datetime
        # 尝试最近几个交易日（Tushare 数据有 T+1 延迟）
        today = datetime.date.today()
        for offset in range(5):
            test_date = (today - datetime.timedelta(days=offset)).strftime("%Y%m%d")
            try:
                print(f"  Trying daily_basic (trade_date={test_date})...", flush=True)
                df = self.client.call(
                    "daily_basic",
                    trade_date=test_date,
                    fields="ts_code,total_mv,circ_mv,pe,pb,dv_ratio,total_share",
                )
                if not df.empty:
                    logger.info(f"daily_basic 拉取成功 (trade_date={test_date}): {len(df)} 只")
                    return df
            except Exception as e:
                logger.debug(f"daily_basic trade_date={test_date} 失败: {e}")
        logger.warning("daily_basic 拉取失败（尝试了最近5个交易日）")
        return pd.DataFrame()

    def _fetch_all_fina_indicator(self, ts_codes: list[str], batch_size: int = 60) -> pd.DataFrame:
        """批量拉取全市场最新 fina_indicator（ROE、毛利率、负债率等）

        Tushare fina_indicator 单次调用最多处理约 100 只股票，超出部分会被静默截断。
        因此 batch_size 不能超过 100，推荐 50-80。

        Args:
            ts_codes: 全量股票代码列表
            batch_size: 每批查询股票数（不能超过 100，默认 60）
        """
        total_batches = (len(ts_codes) + batch_size - 1) // batch_size
        print(f"  Fetching fina_indicator ({total_batches} batches x {batch_size})...", flush=True)
        all_results = []
        batch_start = time.time()
        for i in range(0, len(ts_codes), batch_size):
            batch = ts_codes[i:i + batch_size]
            batch_no = i // batch_size + 1
            codes_str = ",".join(batch)
            try:
                df = self.client.call(
                    "fina_indicator",
                    ts_code=codes_str,
                    fields="ts_code,end_date,roe,roe_yearly,grossprofit_margin,debt_to_assets,ocf_to_or",
                )
                if not df.empty:
                    # 每只股票取最新一期
                    df = df.sort_values("end_date", ascending=False).drop_duplicates(
                        subset=["ts_code"], keep="first"
                    )
                    all_results.append(df)
                    n_returned = df["ts_code"].nunique()
                    if len(batch) > 80 and n_returned < len(batch) * 0.8:
                        logger.warning(
                            f"fina_indicator batch {i}: 请求 {len(batch)} 只, "
                            f"只返回 {n_returned} 只 ({n_returned/len(batch)*100:.0f}%), "
                            f"可能存在 API 截断"
                        )
            except Exception as e:
                logger.warning(f"fina_indicator batch {i} 失败: {e}")

            # 每10批输出进度
            if batch_no % 10 == 0 or batch_no == total_batches:
                elapsed = time.time() - batch_start
                rate = batch_no / elapsed if elapsed > 0 else 0
                eta = (total_batches - batch_no) / rate if rate > 0 else 0
                print(f"    fina_indicator progress: {batch_no}/{total_batches} batches "
                      f"({batch_no/total_batches*100:.0f}%) | 预计剩余 {eta:.0f}s", flush=True)

        if not all_results:
            logger.warning("fina_indicator 拉取全部失败")
            return pd.DataFrame()

        result = pd.concat(all_results, ignore_index=True)

        # 记录整体覆盖率
        n_total = len(ts_codes)
        n_got = len(result)
        logger.info(f"fina_indicator 拉取完成: {n_got}/{n_total} 只 ({n_got/n_total*100:.1f}%)")

        # 字段映射 + 单位转换
        # roe: 直接用 roe_yearly（年化ROE）, fallback to roe（季报单季ROE）
        result["roe"] = result.get("roe_yearly", result.get("roe", 0))
        if "roe" in result.columns and result["roe"].isna().all():
            result["roe"] = result.get("roe_yearly", 0)

        # grossprofit_margin → gross_margin (已是百分比 e.g. 89.76)
        result["gross_margin"] = result.get("grossprofit_margin", 0)

        # debt_to_assets → debt_ratio (已是百分比 e.g. 12.12)
        result["debt_ratio"] = result.get("debt_to_assets", 0)

        return result

    def _fetch_latest_indicators(self, ts_codes_str: str) -> pd.DataFrame:
        """拉取最近一期日常指标（已废弃，改用 _fetch_all_daily_basic）"""
        df = self.client.call(
            "daily_basic",
            ts_code=ts_codes_str,
            trade_date="",
            fields="ts_code,total_mv,circ_mv,pe,pe_ttm,pb,dv_ratio,turnover_rate",
        )
        if df.empty:
            return df
        df = df.sort_values("trade_date", ascending=False).drop_duplicates(
            subset=["ts_code"], keep="first"
        )
        return df

    def _stock_raw_path(self, ts_code: str, name: str = "") -> Path:
        """返回 raw_data.yaml 路径，兼容 {name}_{ts_code} 和纯 {ts_code} 两种目录名"""
        if not name:
            return self.cache_dir / ts_code / "raw_data.yaml"
        safe_name = name.replace("/", "-").replace("\\", "-")
        named = self.cache_dir / f"{safe_name}_{ts_code}" / "raw_data.yaml"
        if named.exists():
            return named
        return self.cache_dir / ts_code / "raw_data.yaml"

    def fetch_candidate_data(self, ts_codes: list[str], force: bool = False,
                             name_map: dict[str, str] | None = None) -> FetchStats:
        """批量拉取候选池股票的全量数据

        如果 raw_data.yaml 已存在且数据完整(data_completeness="full")，默认跳过拉取。

        Args:
            ts_codes: 候选池股票代码列表
            force: 强制重新拉取所有股票数据
            name_map: {ts_code: name} 映射，用于中文目录命名

        Returns:
            FetchStats
        """
        name_map = name_map or {}
        stats = FetchStats(
            total=len(ts_codes),
            started_at=datetime.now().isoformat(),
        )

        # 检查哪些已有缓存（兼容新旧命名）
        skipped_codes = set()
        if not force:
            for ts_code in ts_codes:
                name = name_map.get(ts_code, "")
                raw_path = self._stock_raw_path(ts_code, name)
                if raw_path.exists():
                    try:
                        with open(raw_path, "r", encoding="utf-8") as f:
                            existing = yaml.safe_load(f)
                        completeness = existing.get("meta", {}).get("data_completeness", "")
                        if completeness == "full":
                            skipped_codes.add(ts_code)
                    except Exception:
                        logger.warning(f"{ts_code}: raw_data.yaml 缓存新鲜度检查失败，将重新拉取", exc_info=True)

            if skipped_codes:
                stats.success += len(skipped_codes)
                print(f"[L2 Cache] {len(skipped_codes)} stocks already cached, skipping", flush=True)
                logger.info(f"L2缓存命中: {len(skipped_codes)}/{len(ts_codes)} 只跳过")

        # 找出需要拉取的
        to_fetch = [c for c in ts_codes if c not in skipped_codes]

        print(f"[Fetch] Starting full data fetch for {len(to_fetch)} stocks...", flush=True)
        logger.info(
            f"[{self.trace_id}] 开始拉取 {len(to_fetch)} 只股票数据"
        )

        loop_start = time.time()

        for idx, ts_code in enumerate(to_fetch):
            try:
                name = name_map.get(ts_code, "")
                completeness = self.fetch_single_stock(ts_code, name=name)
                if completeness == "full":
                    stats.success += 1
                elif completeness == "partial":
                    stats.partial += 1
                    stats.partial_codes.append(ts_code)
                else:
                    stats.failed += 1
                    stats.failed_codes.append(ts_code)
            except Exception as e:
                logger.error(f"[{self.trace_id}] {ts_code} 拉取异常: {e}")
                stats.failed += 1
                stats.failed_codes.append(ts_code)

            # 实时进度：每10只或最后一只输出
            total_to_fetch = len(to_fetch)
            if (idx + 1) % 10 == 0 or idx == total_to_fetch - 1:
                elapsed = time.time() - loop_start
                done = idx + 1
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total_to_fetch - done) / rate if rate > 0 else 0
                print(
                    f"  [Progress] {done}/{total_to_fetch} "
                    f"({done/total_to_fetch*100:.0f}%) "
                    f"success={stats.success} partial={stats.partial} failed={stats.failed} "
                    f"| rate={rate:.1f}/s | ETA={eta:.0f}s",
                    flush=True,
                )

        stats.finished_at = datetime.now().isoformat()
        logger.info(f"[{self.trace_id}] {stats.summary()}")

        # 成功率检查
        if stats.success_rate < 90:
            logger.error(
                f"拉取成功率 {stats.success_rate:.1f}% < 90%，请检查！"
            )

        return stats

    def fetch_single_stock(self, ts_code: str, name: str = "") -> str:
        """拉取单只股票全量数据并写入缓存

        Args:
            ts_code: 股票代码
            name: 股票中文名（可选），有则用 {name}_{ts_code} 命名目录

        Returns:
            'full' | 'partial' | 'failed'
        """
        # 目录命名: {name}_{ts_code} 或纯 ts_code
        safe_name = name.replace("/", "-").replace("\\", "-") if name else ""
        dir_name = f"{safe_name}_{ts_code}" if safe_name else ts_code
        stock_dir = self.cache_dir / dir_name
        stock_dir.mkdir(parents=True, exist_ok=True)

        raw_data = {
            "meta": {
                "ts_code": ts_code,
                "name": name or "",
                "industry": "",
                "data_date": datetime.now().strftime("%Y-%m-%d"),
                "data_completeness": "full",
                "missing_fields": [],
            },
            "basic_info": {},
            "annual_financials": [],
            "dividend_history": [],
            "repurchase_history": [],
            "price_summary": {},
            "valuation_history": [],
        }

        missing = []

        # === 1. 基本信息 + 行业 ===
        try:
            basic = self.client.call(
                "stock_basic",
                ts_code=ts_code,
                fields="ts_code,name,industry,list_date",
            )
            if not basic.empty:
                row = basic.iloc[0]
                raw_data["meta"]["name"] = row.get("name", "")
                raw_data["meta"]["industry"] = row.get("industry", "")
                raw_data["basic_info"]["list_date"] = str(row.get("list_date", ""))
        except Exception as e:
            logger.warning(f"{ts_code} 基本信息拉取失败: {e}")

        # === 2. 财务指标 (fina_indicator) — 含 ROE、毛利率、负债率 ===
        fina = pd.DataFrame()
        try:
            fina = self.client.get_fina_indicator(ts_code)
            if not fina.empty and "debt_to_assets" in fina.columns:
                latest = fina.sort_values("end_date", ascending=False).iloc[0]
                raw_data["basic_info"]["total_mv"] = 0.0  # 后续从 daily_basic 获取
                raw_data["basic_info"]["pe"] = 0.0
                raw_data["basic_info"]["pb"] = 0.0
                raw_data["basic_info"]["dividend_yield"] = 0.0
        except Exception as e:
            missing.append("fina_indicator")
            logger.warning(f"{ts_code} 财务指标拉取失败: {e}")

        # === 3. 日线指标 (daily_basic) — 含市值、PE、PB、股息率 ===
        daily_basic = pd.DataFrame()
        try:
            daily_basic = self.client.get_daily_basic(ts_code, start_date="20180101")
            if not daily_basic.empty:
                latest_db = daily_basic.sort_values(
                    "trade_date", ascending=False
                ).iloc[0]
                # Tushare daily_basic: total_mv/circ_mv 单位万元 → 转为亿元
                raw_data["basic_info"]["total_mv"] = self._safe_float(
                    latest_db.get("total_mv")
                ) / 10000
                raw_data["basic_info"]["circ_mv"] = self._safe_float(
                    latest_db.get("circ_mv")
                ) / 10000
                raw_data["basic_info"]["pe"] = self._safe_float(
                    latest_db.get("pe_ttm", latest_db.get("pe"))
                )
                raw_data["basic_info"]["pb"] = self._safe_float(
                    latest_db.get("pb")
                )
                raw_data["basic_info"]["dividend_yield"] = self._safe_float(
                    latest_db.get("dv_ratio")
                )
                # total_share 单位万股，用于计算总分红金额
                raw_data["basic_info"]["total_share"] = self._safe_float(
                    latest_db.get("total_share")
                )
                # 估值历史
                raw_data["valuation_history"] = (
                    daily_basic.sort_values("trade_date", ascending=False)
                    .head(2000)  # 最多保留2000条
                    .apply(
                        lambda r: {
                            "date": str(r["trade_date"]),
                            "pe": DataFetcher._safe_float(
                                r.get("pe_ttm", r.get("pe"))
                            ),
                            "pb": DataFetcher._safe_float(r.get("pb")),
                            "dv_ratio": DataFetcher._safe_float(r.get("dv_ratio")),
                        },
                        axis=1,
                    )
                    .tolist()
                )
        except Exception as e:
            missing.append("daily_basic")
            logger.warning(f"{ts_code} 日线指标拉取失败: {e}")

        # === 4. 行情摘要 ===
        try:
            daily = self.client.get_daily(ts_code, start_date="20180101")
            if not daily.empty:
                latest_d = daily.sort_values("trade_date", ascending=False).iloc[0]
                # 年线和均线
                recent_250 = daily.sort_values("trade_date", ascending=False).head(250)
                ma_60 = recent_250.head(60)["close"].mean()
                ma_250 = recent_250["close"].mean()
                year_high = recent_250["high"].max()
                year_low = recent_250["low"].min()
                # v0.6.1: 计算年化波动率
                # 从近 250 个交易日的收盘价计算对数收益率，年化
                volatility = 0.0
                if len(recent_250) >= 60:
                    closes = recent_250.sort_values("trade_date", ascending=True)["close"].values
                    log_returns = np.log(closes[1:] / closes[:-1])
                    daily_std = float(np.std(log_returns, ddof=1))
                    volatility = round(float(daily_std * np.sqrt(252) * 100), 1)  # 转为百分比
                raw_data["price_summary"] = {
                    "latest_price": self._safe_float(latest_d["close"]),
                    "ma_60": self._safe_float(ma_60),
                    "ma_250": self._safe_float(ma_250),
                    "year_high": self._safe_float(year_high),
                    "year_low": self._safe_float(year_low),
                    "volatility_1y": volatility,
                }
        except Exception as e:
            logger.warning(f"{ts_code} 行情拉取失败: {e}")

        # === 5. 财务三表 (income, balance_sheet, cashflow) ===
        income = self.client.get_income(ts_code, start_date=f"{FINANCIAL_START_YEAR}0101")
        balance = self.client.get_balance_sheet(ts_code, start_date=f"{FINANCIAL_START_YEAR}0101")
        cashflow = self.client.get_cashflow(ts_code, start_date=f"{FINANCIAL_START_YEAR}0101")

        has_income = not income.empty
        has_balance = not balance.empty
        has_cashflow = not cashflow.empty

        if not has_income:
            missing.append("income")
        if not has_balance:
            missing.append("balance_sheet")
        if not has_cashflow:
            missing.append("cashflow")

        # 获取所有年份 — 只取年度报告（end_date 以 "1231" 结尾）
        # 季报/半年报不完整（缺少折旧摊销、财务费用等），用于长期分析会失真
        all_dates = set()
        for df in [income, balance, cashflow, fina]:
            if not df.empty and "end_date" in df.columns:
                all_dates.update(df["end_date"].unique())

        # 过滤：只保留年报日期（1231）和最新一期（可能是季报）
        annual_dates = {d for d in all_dates if str(d)[4:8] == "1231"}
        if not annual_dates:
            # fallback: 没有任何年报，使用所有日期
            annual_dates = all_dates

        # 按年份合并财务数据（仅年报）
        years_data = {}
        for end_date in sorted(annual_dates, reverse=True):
            year = end_date[:4]
            if year not in years_data:
                years_data[year] = {"year": int(year)}

            y = years_data[year]

            # Income — v0.5.2: 全量存储 + 费用端 + 净利率
            if has_income:
                inc = income[income["end_date"] == end_date]
                if not inc.empty:
                    row = inc.iloc[0]
                    revenue = self._safe_float(row.get("revenue"))
                    net_profit = self._safe_float(
                        row.get("n_income_attr_p", row.get("n_income"))
                    )
                    operate_cost = self._safe_float(row.get("oper_cost"), field_name="income.oper_cost")
                    y["income"] = {
                        "revenue": revenue,
                        "revenue_yoy": 0.0,
                        "gross_profit": revenue - operate_cost,
                        "gross_margin": 0.0,
                        "operating_profit": self._safe_float(row.get("operate_profit")),
                        "net_profit": net_profit,
                        "net_profit_yoy": 0.0,
                        # v0.5.2: 净利率 — 优先从 fina_indicator 取，兜底自算
                        "net_margin": 0.0,
                        "roe": 0.0,
                        "eps": self._safe_float(row.get("basic_eps")),
                        "fin_exp": self._safe_float(row.get("fin_exp"), field_name="income.fin_exp"),
                        # v0.5.2: 新增费用端字段 (Tushare 原始字段名)
                        # 注意: Tushare income 全量返回的字段名是 sell_exp/admin_exp/oper_cost/rd_exp
                        "total_profit": self._safe_float(row.get("total_profit"), field_name="income.total_profit"),
                        "sell_exp": self._safe_float(row.get("sell_exp"), field_name="income.sell_exp"),
                        "admin_exp": self._safe_float(row.get("admin_exp"), field_name="income.admin_exp"),
                        "operate_cost": self._safe_float(row.get("oper_cost"), field_name="income.oper_cost"),
                        "rd_exp": self._safe_float(row.get("rd_exp"), field_name="income.rd_exp"),
                        "int_income": self._safe_float(row.get("int_income"), field_name="income.int_income"),
                    }
                    # 毛利率 + ROE + 净利率 从 fina_indicator 获取
                    if not fina.empty:
                        f_row = fina[fina["end_date"] == end_date]
                        if not f_row.empty:
                            fr = f_row.iloc[0]
                            y["income"]["gross_margin"] = self._safe_float(
                                fr.get("grossprofit_margin")
                            )
                            y["income"]["roe"] = self._safe_float(fr.get("roe"))
                            # v0.5.2: netprofit_margin 从 fina 获取 (兜底)
                            net_margin_fina = self._safe_float(
                                fr.get("netprofit_margin"), field_name="fina.netprofit_margin"
                            )
                            if net_margin_fina > 0:
                                y["income"]["net_margin"] = net_margin_fina
                    # v0.5.2: fina 无净利率 → 自算
                    if y["income"]["net_margin"] == 0.0 and revenue > 0 and net_profit > 0:
                        y["income"]["net_margin"] = round(net_profit / abs(revenue) * 100, 2)

            # Balance Sheet — v0.5.2: 新增 total_cur_assets/liab
            if has_balance:
                bal = balance[balance["end_date"] == end_date]
                if not bal.empty:
                    row = bal.iloc[0]
                    total_assets = self._safe_float(row.get("total_assets"))
                    total_liab = self._safe_float(row.get("total_liab"))
                    y["balance_sheet"] = {
                        "total_assets": total_assets,
                        "total_liabilities": total_liab,
                        "debt_ratio": (
                            total_liab / total_assets * 100 if total_assets > 0 else 0
                        ),
                        "current_ratio": 0.0,
                        "quick_ratio": 0.0,
                        "receivables": self._safe_float(row.get("accounts_receiv")),
                        "inventory": self._safe_float(row.get("inventories")),
                        "goodwill": self._safe_float(row.get("goodwill")),
                        "fixed_assets": self._safe_float(row.get("fix_assets")),
                        "intangible_assets": self._safe_float(row.get("intan_assets")),
                        "lt_eqt_invest": self._safe_float(row.get("lt_eqt_invest"), field_name="balance.lt_eqt_invest"),
                        "total_equity": self._safe_float(
                            row.get("total_hldr_eqy_exc_min_int",
                                    row.get("total_hldr_eqy_inc_min_int"))
                        ),
                        # v0.5.2: 流动资产/流动负债 (Tushare 原始字段)
                        "total_cur_assets": self._safe_float(row.get("total_cur_assets"),
                            field_name="balance.total_cur_assets"),
                        "total_cur_liab": self._safe_float(row.get("total_cur_liab"),
                            field_name="balance.total_cur_liab"),
                    }
                    # 流动/速动比率
                    if not fina.empty:
                        f_row = fina[fina["end_date"] == end_date]
                        if not f_row.empty:
                            fr = f_row.iloc[0]
                            y["balance_sheet"]["current_ratio"] = self._safe_float(
                                fr.get("current_ratio")
                            )
                            y["balance_sheet"]["quick_ratio"] = self._safe_float(
                                fr.get("quick_ratio")
                            )

            # Cashflow — v0.5.2: 新增股利支付现金字段
            if has_cashflow:
                cf = cashflow[cashflow["end_date"] == end_date]
                if not cf.empty:
                    row = cf.iloc[0]
                    op_cf = self._safe_float(row.get("n_cashflow_act"))
                    capex = self._safe_float(row.get("c_pay_acq_const_fiolta"), field_name="cashflow.c_pay_acq_const_fiolta")
                    # FCF: 优先用 Tushare free_cashflow，NaN 时 fallback 到 op_cf + capex
                    fcf_raw = row.get("free_cashflow")
                    if pd.notna(fcf_raw):
                        fcf = self._safe_float(fcf_raw)
                        if fcf == 0:
                            fcf = op_cf + capex
                    else:
                        fcf = op_cf + capex
                    # 折旧摊销合计: Tushare cashflow 分段字段
                    #   depr_fa_coga_dpba (固定资产折旧)
                    #   + amort_intang_assets (无形资产摊销)
                    #   + lt_amort_deferred_exp (长期待摊费用摊销)
                    #   + use_right_asset_dep (使用权资产折旧)
                    depr_amort = (
                        self._safe_float(row.get("depr_fa_coga_dpba"))
                        + self._safe_float(row.get("amort_intang_assets"))
                        + self._safe_float(row.get("lt_amort_deferred_exp"))
                        + self._safe_float(row.get("use_right_asset_dep"))
                    )
                    y["cashflow"] = {
                        "operating_cf": op_cf,
                        "investing_cf": self._safe_float(row.get("n_cashflow_inv_act")),
                        "financing_cf": self._safe_float(row.get("n_cash_flows_fnc_act")),
                        "capex": capex,                                   # 购建固定资产
                        "acq_subsidiary": self._safe_float(row.get("n_disp_subs_oth_biz"), field_name="cashflow.n_disp_subs_oth_biz"),  # 并购子公司
                        "depr_amort": depr_amort,
                        "fcf": fcf,
                        "finan_exp": self._safe_float(row.get("finan_exp")),  # 财务费用(cashflow表)
                        # v0.5.2: 分配股利支付现金 (Tushare 原始字段: c_pay_dist_dpcp_int_exp)
                        "dividend_paid_cf": self._safe_float(row.get("c_pay_dist_dpcp_int_exp"),
                            field_name="cashflow.c_pay_dist_dpcp_int_exp"),
                    }

        raw_data["annual_financials"] = list(years_data.values())

        # 计算营收/净利同比增长
        self._compute_yoy(raw_data["annual_financials"])

        # === 6. 分红数据 ===
        try:
            div = self.client.get_dividend(ts_code)
            if not div.empty:
                div = div.sort_values("end_date", ascending=False)
                total_share = raw_data["basic_info"].get("total_share", 0)
                for _, row in div.iterrows():
                    cash_div = self._safe_float(row.get("cash_div"))
                    # 跳过零分红记录（中期预披露、预案等）
                    if cash_div <= 0:
                        continue
                    raw_data["dividend_history"].append({
                        # Tushare end_date 是除权日，通常比财年晚1年（FY2024 → 2025除权）
                        # 因此 year = end_date_year - 1
                        "year": int(str(row["end_date"])[:4]) - 1,
                        "dividend_per_share": cash_div,
                        # total_dividend = 每股分红(元) × 总股本(万股)
                        # → 单位: 万元 (与 Tushare 财务数据万元单位对齐)
                        "total_dividend": cash_div * total_share if total_share > 0 else 0.0,
                        "payout_ratio": 0.0,  # 后续 _compute_payout_ratio 计算
                    })
        except Exception as e:
            missing.append("dividend")
            logger.warning(f"{ts_code} 分红数据拉取失败: {e}")

        # === 6.5 计算分红率 (payout_ratio = 每股分红 / EPS) ===
        self._compute_payout_ratio(raw_data)

        # === 7. 回购数据 ===
        try:
            rep = self.client.get_repurchase(ts_code)
            if not rep.empty:
                rep = rep.sort_values("ann_date", ascending=False)
                for _, row in rep.iterrows():
                    rep_type = str(row.get("rep_type", ""))
                    # 安全获取日期（处理 NaN）
                    ann_date = row.get("ann_date", "2000")
                    year_str = str(int(ann_date))[:4] if pd.notna(ann_date) else "2000"
                    # 安全获取金额（处理 NaN）
                    amount = row.get("amount", 0)
                    if pd.isna(amount):
                        amount = 0
                    vol = row.get("vol", 0)
                    if pd.isna(vol):
                        vol = 0
                    raw_data["repurchase_history"].append({
                        "year": int(year_str),
                        "repurchase_amount": self._safe_float(amount),
                        "repurchase_shares": int(float(vol)) if pd.notna(vol) else 0,
                        "is_cancellation": rep_type == "2",
                    })
        except Exception as e:
            missing.append("repurchase")
            logger.warning(f"{ts_code} 回购数据拉取失败: {e}")

        # === 归一化：所有金额统一为亿元 (v0.5.3) ===
        self._normalize_to_yi(raw_data)

        # === 写入缓存 ===
        raw_data["meta"]["missing_fields"] = missing
        if missing:
            raw_data["meta"]["data_completeness"] = "partial"

        raw_path = stock_dir / "raw_data.yaml"
        with open(raw_path, "w", encoding="utf-8") as f:
            yaml.dump(raw_data, f, allow_unicode=True, default_flow_style=False)

        completeness = raw_data["meta"]["data_completeness"]
        return completeness

    @staticmethod
    def _normalize_to_yi(raw_data: dict) -> None:
        """v0.6.1: 将所有金额字段归一化为亿元，百分比/比率/EPS 不动。

        归一化规则见 docs/TUSHARE_UNITS.md：
        - 财务三表金额: 元 → 亿元 (÷ 1e8)
        - 百分比值 (gross_margin/roe/net_margin/debt_ratio/current_ratio/quick_ratio): 不动
        - EPS / YoY: 不动
        - total_share: 万股 → 亿股 (÷ 1e4)
        - total_dividend: 万元 → 亿元 (÷ 1e4)
        - repurchase_amount: 万元 → 亿元 (÷ 1e4)
        - total_mv/circ_mv: 已在 fetch_single_stock 中转为亿元, 不动
        """
        # 非金额字段 — 不能 ÷1e8
        NON_MONETARY = {
            "gross_margin", "net_margin", "roe", "eps",
            "revenue_yoy", "net_profit_yoy",
            "debt_ratio", "current_ratio", "quick_ratio",
        }

        # 1. 财务三表: 元 → 亿元（跳过非金额字段）
        for f in raw_data.get("annual_financials", []):
            for section in ("income", "balance_sheet", "cashflow"):
                if section not in f:
                    continue
                for k, v in list(f[section].items()):
                    if isinstance(v, (int, float)) and v != 0.0 and k not in NON_MONETARY:
                        f[section][k] = v / 1e8

        # 2. total_share: 万股 → 亿股
        ts = raw_data.get("basic_info", {}).get("total_share", 0)
        if ts > 0:
            raw_data["basic_info"]["total_share"] = ts / 1e4

        # 3. dividend total_dividend: 万元 → 亿元
        for d in raw_data.get("dividend_history", []):
            if "total_dividend" in d:
                d["total_dividend"] = d["total_dividend"] / 1e4

        # 4. repurchase repurchase_amount: 万元 → 亿元
        for r in raw_data.get("repurchase_history", []):
            if "repurchase_amount" in r:
                r["repurchase_amount"] = r["repurchase_amount"] / 1e4

    def _compute_yoy(self, financials: list[dict]):
        """计算营收和净利润的同比增长率"""
        for i, f in enumerate(financials):
            inc = f.get("income", {})
            if i < len(financials) - 1:
                prev_inc = financials[i + 1].get("income", {})
                rev = inc.get("revenue", 0)
                prev_rev = prev_inc.get("revenue", 0)
                if prev_rev and prev_rev != 0:
                    inc["revenue_yoy"] = round((rev - prev_rev) / abs(prev_rev) * 100, 2)

                np_val = inc.get("net_profit", 0)
                prev_np = prev_inc.get("net_profit", 0)
                if prev_np and prev_np != 0:
                    inc["net_profit_yoy"] = round(
                        (np_val - prev_np) / abs(prev_np) * 100, 2
                    )

    @staticmethod
    def _compute_payout_ratio(raw_data: dict) -> None:
        """v0.6.1: 计算分红率 = 每股分红 / EPS × 100

        Tushare dividend API 不返回 payout_ratio 字段，需自行计算。
        将分红记录的 fiscal year 与 annual_financials EPS 匹配。
        """
        # 构建 fiscal_year → eps 映射
        eps_map = {}
        for f in raw_data.get("annual_financials", []):
            fy = f.get("year")
            eps = f.get("income", {}).get("eps", 0)
            if fy and eps:
                eps_map[fy] = eps

        for d in raw_data.get("dividend_history", []):
            fy = d.get("year")  # 已是财年（end_date_year - 1）
            eps = eps_map.get(fy)
            if eps and eps > 0:
                d["payout_ratio"] = round(d.get("dividend_per_share", 0) / eps * 100, 1)
