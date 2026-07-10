"""应用配置"""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用
    APP_NAME: str = "Investment Strategy"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # 路径
    PROJECT_ROOT: Path = Path(__file__).parent.parent.parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    STOCK_CACHE_DIR: Path = DATA_DIR / "stock_cache"  # 向后兼容，指向 turtle
    TURTLE_CACHE_DIR: Path = DATA_DIR / "stock_cache" / "turtle"
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

    # WebSearch — Bocha (v0.23: 主搜索引擎，中文覆盖更优)
    BOCHA_API_KEY: str = ""
    # WebSearch — Tavily (v0.23: 降级为备用)
    TAVILY_API_KEY: str = ""

    # 高景气策略
    PROSPERITY_DIR: Path = Path(__file__).parent.parent / "strategies" / "prosperity"
    PROSPERITY_DATA_DIR: Path = PROJECT_ROOT / "data" / "prosperity"
    PROSPERITY_RULES_DIR: Path = Path(__file__).parent.parent.parent / "rules" / "prosperity"
    PROSPERITY_VERIFY_ROUNDS: int = 3  # v0.20: VerifyAgent LLM 多轮投票轮数（设 1 回退单轮）
    PROSPERITY_HYPOTHESIZE_ROUNDS: int = 3         # v0.21: HypothesizeAgent Phase 1 投票轮数（设 1 降级单轮）
    PROSPERITY_HYPOTHESIZE_PHASE1_TIMEOUT: int = 25  # v0.21: Phase 1 单轮超时秒数
    PROSPERITY_HYPOTHESIZE_PHASE2_TIMEOUT: int = 120 # v0.23: Phase 2 填充超时秒数（v4 pro 需更长时间）
    PROSPERITY_COUNTER_TIMEOUT: int = 120           # v0.23.1: CounterAgent LLM 级联裁决超时秒数
    PROSPERITY_SCREENING_THRESHOLD: int = 50        # v0.23.6: 成分股超此数触发子板块交互推荐
    PROSPERITY_SCREENING_LLM_TIMEOUT: int = 180     # v1.1.0: ScreeningAgent LLM 分类+标记超时秒数
    PROSPERITY_SCREENING_TOP_PER_SEGMENT: int = 6   # v1.2.0: LLM 精选每段挑几只（上游/中游/下游各 K 只）

    # 调度
    FULL_REFRESH_CRON: str = "0 6 * * 1-5"  # 工作日早6点

    class Config:
        env_file = str(Path(__file__).parent.parent.parent / ".env")
        env_file_encoding = "utf-8"


settings = Settings()
