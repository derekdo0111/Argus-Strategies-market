"""高景气策略 — SQLAlchemy ORM 模型

SQLite 单文件 zero-config，上线换 PostgreSQL 仅需改 DATABASE_URL。
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, JSON,
    ForeignKey, create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()


class Industry(Base):
    """行业元数据"""
    __tablename__ = "industries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    first_study = Column(DateTime, nullable=True)
    last_study = Column(DateTime, nullable=True)

    sessions = relationship("ResearchSession", back_populates="industry")


class ResearchSession(Base):
    """研究会话 — 一次行业研究的完整记录"""
    __tablename__ = "research_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_id = Column(Integer, ForeignKey("industries.id"), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # running | completed | failed
    current_step = Column(String(30), nullable=True)  # search | hypothesize | verify | counter | report | done

    industry = relationship("Industry", back_populates="sessions")
    hypotheses = relationship("Hypothesis", back_populates="session")
    stock_pools = relationship("StockPool", back_populates="session")


class Hypothesis(Base):
    """假设追踪 — 每条假设的状态和置信度（v3：LLM验证+方向性+因果强度）"""
    __tablename__ = "hypotheses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("research_sessions.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    tier = Column(String(10), nullable=False, default="core")  # core | sub | data（向后兼容）
    chain_level = Column(Integer, nullable=True)  # v2: 0=现状诊断 1=一阶推演 2=二阶推演 3=投资落点
    derives_from = Column(String(500), nullable=True)  # v2: 上游假设 id，逗号分隔如 "H0-1,H0-2"
    time_horizon = Column(String(50), nullable=True)  # v2: 时间窗口如 "当前" / "6个月" / "2027Q1"
    status = Column(String(20), nullable=False, default="pending")
    # pending | confirmed | partial | disputed | unverified | overturned | unreachable
    confidence = Column(String(10), nullable=True)  # high | medium | low
    sentiment = Column(String(10), nullable=True)  # v3: positive | negative | neutral
    causality_strength = Column(String(10), nullable=True)  # v3: strong | moderate | weak | broken
    causality_note = Column(String(500), nullable=True)  # v3: 因果强度简短说明
    wiki_path = Column(String(500), nullable=False)  # 假设页文件路径
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = relationship("ResearchSession", back_populates="hypotheses")


class IndustryMetrics(Base):
    """行业指标快照 — industry_metrics.py 的计算结果"""
    __tablename__ = "industry_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_id = Column(Integer, ForeignKey("industries.id"), nullable=False, index=True)
    period = Column(String(10), nullable=False)  # e.g. "2026Q1"
    metrics = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class StockPool(Base):
    """股池快照 — stock_screener.py + screening_agent.py 的排名结果（v3）"""
    __tablename__ = "stock_pools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("research_sessions.id"), nullable=False, index=True)
    industry_id = Column(Integer, ForeignKey("industries.id"), nullable=False)
    ts_code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    score_total = Column(Float, nullable=False)
    score_detail = Column(JSON, nullable=False)  # 各维度分
    direction_score = Column(Float, nullable=True)  # v3: LLM 方向契合度 0~1
    finance_score = Column(Float, nullable=True)  # v3: 代码财务打分 0~1
    matched_l3 = Column(String(20), nullable=True)  # v3: 匹配的 L3 假设 ID
    matched_reason = Column(String(500), nullable=True)  # v3: 匹配理由
    rank = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("ResearchSession", back_populates="stock_pools")


class TrackingItem(Base):
    """跟踪项（v4: +indicator_name/frequency/last_value 等 7 列）"""
    __tablename__ = "tracking_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    industry_id = Column(Integer, ForeignKey("industries.id"), nullable=False, index=True)
    item = Column(String(300), nullable=False)
    trigger_condition = Column(String(300), nullable=True)
    check_date = Column(DateTime, nullable=True)
    status = Column(String(20), default="pending")  # pending | checked | triggered | resolved
    source_session_id = Column(Integer, nullable=True)
    # v4 新增：indicator 结构化字段
    indicator_name = Column(String(200), nullable=True)        # 指标名称
    frequency = Column(String(20), nullable=True)               # daily/weekly/monthly/quarterly
    last_value = Column(Float, nullable=True)                   # 上次数值
    last_value_text = Column(String(300), nullable=True)        # 上次文本值
    search_query = Column(String(500), nullable=True)           # WebSearch 检索词
    expected_direction = Column(String(20), nullable=True)      # rising/falling/stable/unknown
    history_json = Column(Text, nullable=True)                  # 历史记录 JSON 数组
    created_at = Column(DateTime, default=datetime.utcnow)


def get_engine(db_path: str = None):
    """创建 SQLite 引擎"""
    import os
    if db_path is None:
        from app.core.config import settings
        db_path = str(settings.PROSPERITY_DATA_DIR / "prosperity.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_db(engine=None):
    """初始化数据库表"""
    if engine is None:
        engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def migrate_v2(engine=None):
    """v2 迁移：为 hypotheses 表添加 chain_level/derives_from/time_horizon 列"""
    from sqlalchemy import text, inspect
    if engine is None:
        engine = get_engine()
    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_cols = {c["name"] for c in inspector.get_columns("hypotheses")}
        # 注意：SQLite 不支持 IF NOT EXISTS，用 try/except
        for col_name, col_type in [
            ("chain_level", "INTEGER"),
            ("derives_from", "VARCHAR(500)"),
            ("time_horizon", "VARCHAR(50)"),
        ]:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE hypotheses ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger = __import__("logging").getLogger(__name__)
                logger.info(f"migrate_v2: added column {col_name} to hypotheses")


def migrate_v4(engine=None):
    """v4 迁移：tracking_items +indicator_name/frequency/last_value 等 7 列"""
    from sqlalchemy import text, inspect
    if engine is None:
        engine = get_engine()
    logger = __import__("logging").getLogger(__name__)
    with engine.connect() as conn:
        inspector = inspect(engine)
        existing_cols = {c["name"] for c in inspector.get_columns("tracking_items")}
        for col_name, col_type in [
            ("indicator_name", "VARCHAR(200)"),
            ("frequency", "VARCHAR(20)"),
            ("last_value", "FLOAT"),
            ("last_value_text", "VARCHAR(300)"),
            ("search_query", "VARCHAR(500)"),
            ("expected_direction", "VARCHAR(20)"),
            ("history_json", "TEXT"),
        ]:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE tracking_items ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"migrate_v4: added column {col_name} to tracking_items")


def migrate_v3(engine=None):
    """v3 迁移：hyptheses +sentiment/causality_strength/causality_note；stock_pools +direction/finance/matched"""
    from sqlalchemy import text, inspect
    if engine is None:
        engine = get_engine()
    logger = __import__("logging").getLogger(__name__)
    with engine.connect() as conn:
        inspector = inspect(engine)

        # hypotheses 新增字段
        hyp_cols = {c["name"] for c in inspector.get_columns("hypotheses")}
        for col_name, col_type in [
            ("sentiment", "VARCHAR(10)"),
            ("causality_strength", "VARCHAR(10)"),
            ("causality_note", "VARCHAR(500)"),
        ]:
            if col_name not in hyp_cols:
                conn.execute(text(f"ALTER TABLE hypotheses ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"migrate_v3: added column {col_name} to hypotheses")

        # stock_pools 新增字段
        pool_cols = {c["name"] for c in inspector.get_columns("stock_pools")}
        for col_name, col_type in [
            ("direction_score", "FLOAT"),
            ("finance_score", "FLOAT"),
            ("matched_l3", "VARCHAR(20)"),
            ("matched_reason", "VARCHAR(500)"),
        ]:
            if col_name not in pool_cols:
                conn.execute(text(f"ALTER TABLE stock_pools ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"migrate_v3: added column {col_name} to stock_pools")


def get_session(engine=None):
    """获取数据库会话"""
    if engine is None:
        engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()
