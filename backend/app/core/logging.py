"""结构化日志配置 — structlog + trace_id"""

import structlog
import uuid
import logging
from contextvars import ContextVar

# trace_id 上下文变量，贯穿全链路
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def set_trace_id(trace_id: str | None = None) -> str:
    """设置当前请求的 trace_id"""
    tid = trace_id or str(uuid.uuid4())[:8]
    trace_id_var.set(tid)
    return tid


def get_trace_id() -> str:
    return trace_id_var.get()


def setup_logging(log_level: str = "INFO"):
    """初始化结构化日志"""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if log_level == "DEBUG"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # 设置标准库日志级别
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )
