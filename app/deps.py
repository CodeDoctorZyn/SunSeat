import os
from functools import lru_cache
from zoneinfo import ZoneInfo
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
import redis


@lru_cache()
def get_timezone() -> ZoneInfo:
    """Get the configured timezone (default: Australia/Melbourne)."""
    tz_name = os.getenv("TIMEZONE", "Australia/Melbourne")
    return ZoneInfo(tz_name)


def init_cache():
    """Initialize Redis cache for FastAPI."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        redis_client = redis.from_url(redis_url)
        FastAPICache.init(RedisBackend(redis_client), prefix="sundirect:")
    except Exception:
        # Fallback to in-memory cache if Redis unavailable
        from fastapi_cache.backends.inmemory import InMemoryBackend
        FastAPICache.init(InMemoryBackend(), prefix="sundirect:")