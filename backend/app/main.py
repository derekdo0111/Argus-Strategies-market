"""FastAPI 应用工厂 — 遍历 registry 自动挂载策略路由"""

import importlib
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.logging import setup_logging, set_trace_id
from .core.registry import active_strategies
from .api import strategies


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title="Investment Strategy API",
        version=settings.APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # trace_id middleware — 每个 HTTP 请求自动注入 trace_id
    @app.middleware("http")
    async def trace_id_middleware(request, call_next):
        set_trace_id(str(uuid.uuid4())[:8])
        response = await call_next(request)
        return response

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册通用路由
    app.include_router(strategies.router, prefix="/api/strategies", tags=["strategies"])

    # 遍历 registry 自动挂载各策略 API 路由
    for strategy_id, meta in active_strategies().items():
        try:
            api_module = importlib.import_module(
                f"app.strategies.{strategy_id}.api"
            )
            app.include_router(api_module.router, prefix=meta.api_prefix, tags=[strategy_id])
        except (ModuleNotFoundError, AttributeError) as e:
            # 策略骨架未实现，跳过不阻塞启动
            import logging
            logging.getLogger(__name__).warning(
                f"策略 {strategy_id} 的 api.py 未就绪: {e}"
            )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": settings.APP_VERSION}

    return app


app = create_app()
