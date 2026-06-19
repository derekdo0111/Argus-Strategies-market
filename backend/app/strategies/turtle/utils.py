"""龟龟策略公共工具函数"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def find_stock_dir(cache_dir: Path, ts_code: str) -> Optional[Path]:
    """查找股票缓存目录

    v0.5.2: 优先匹配 {name}_{ts_code}（通常含 computed.yaml），再 fallback 纯 {ts_code}。
    修复双文件夹 Bug: raw_data 在 {ts_code}/, computed 在 {name}_{ts_code}/。
    """
    # 优先匹配 {name}_{ts_code} 格式（通常含 computed.yaml）
    for d in cache_dir.iterdir():
        if d.is_dir() and d.name.endswith(f"_{ts_code}"):
            return d
    # fallback: 纯 ts_code
    direct = cache_dir / ts_code
    if direct.exists():
        return direct
    return None
