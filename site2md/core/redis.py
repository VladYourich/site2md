import redis.asyncio as redis

from site2md.config import settings
from site2md.core.logging import get_logger

logger = get_logger(__name__)

_pool: redis.ConnectionPool | None = None


async def init_redis() -> redis.Redis:
    global _pool
    _pool = redis.ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
    )
    r = redis.Redis(connection_pool=_pool)
    try:
        await r.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error("Redis connection failed", extra={"error": str(e)})
        raise
    return r


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.disconnect()
        _pool = None
        logger.info("Redis connection closed")


async def get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=settings.redis_max_connections,
        )
    return redis.Redis(connection_pool=_pool)


async def check_redis_health() -> dict[str, str]:
    try:
        r = await get_redis()
        await r.ping()
        return {"status": "ok", "redis": "connected"}
    except Exception as e:
        return {"status": "error", "redis": str(e)}
