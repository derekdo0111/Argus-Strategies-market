"""应用配置"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "Investment Strategy"
    APP_VERSION: str = "0.8.0"
    DEBUG: bool = False

    # 路径
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    STOCK_CACHE_DIR: Path = DATA_DIR / "stock_cache"  # 向后兼容，指向 turtle
    TURTLE_CACHE_DIR: Path = DATA_DIR / "stock_cache" / "turtle"
    PROSPERITY_CACHE_DIR: Path = DATA_DIR / "stock_cache" / "prosperity"
    TEMPLATES_DIR: Path = DATA_DIR / "templates"
    RULES_DIR: Path = Path(__file__).parent.parent.parent / "rules"

    # 数据库
    DATABASE_URL: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'backend' / 'investment.db'}"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Tushare
    TUSHARE_TOKEN: str = ""

    # LLM — DeepSeek (OpenAI 兼容协议)
    LLM_API_KEY: str = ""
    LLM_API_BASE: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_MAX_TOKENS: int = 32768  # v0.5.2: 8192→32768, QRV报告完整输出不再截断
    LLM_TEMPERATURE: float = 0.1  # 分析类任务用低温

    # 龟龟策略
    TURTLE_RISK_FREE_RATE: float = 1.7  # 10年期国债收益率 (2026年约1.7%)
    TURTLE_RULE_VERSION: str = "v2"
    TURTLE_SPREAD: float = 1.0  # PR 门槛利差 (相对国债的溢价)

    # 选股器阈值（可通过 .env 覆盖）
    TURTLE_MIN_LIST_YEARS: int = 8
    TURTLE_MIN_MARKET_CAP: float = 200.0  # 亿
    TURTLE_MIN_ROE: float = 12.0  # %
    TURTLE_MIN_PE: float = 5.0
    TURTLE_MAX_PE: float = 25.0
    TURTLE_MIN_DIVIDEND_YIELD: float = 2.5  # %
    TURTLE_MIN_GROSS_MARGIN: float = 25.0  # %
    TURTLE_MAX_DEBT_RATIO: float = 60.0  # %

    # WebSearch — Tavily (v0.3.0: Brave 已移除)
    TAVILY_API_KEY: str = ""

    # 调度
    FULL_REFRESH_CRON: str = "0 6 * * 1-5"  # 工作日早6点

    class Config:
        env_file = str(Path(__file__).parent.parent.parent / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
