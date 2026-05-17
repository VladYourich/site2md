from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from site2md.api.routes import router as api_router
from site2md.config import settings
from site2md.core.health import router as health_router
from site2md.core.logging import get_logger, setup_logging
from site2md.core.redis import check_redis_health, close_redis, init_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    logger.info("Starting site2md API v0.2.0")
    try:
        await init_redis()
    except Exception as e:
        logger.error("Failed to init Redis, API will start but be unhealthy", extra={"error": str(e)})
    yield
    with suppress(Exception):
        await close_redis()
    logger.info("site2md API shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="site2md",
        version="0.2.0",
        description="Turn websites into clean, structured Markdown for RAG/LLM. REST API + MCP Server.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

    app.include_router(health_router, tags=["Health"])

    # readiness probe
    @app.get("/ready", tags=["Health"])
    async def readiness():
        health = await check_redis_health()
        if health["status"] == "error":
            return JSONResponse(health, status_code=503)
        return health

    app.include_router(api_router, prefix="/api/v1")

    return app


app = create_app()
