"""pytest 全局 fixtures"""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_cache_dir():
    """临时缓存目录"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)
