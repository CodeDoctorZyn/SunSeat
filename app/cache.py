"""
Caching module for SunSeat application.
Provides Redis-based caching for GTFS-RT data and solar calculations.
"""

from typing import Any, Optional, Dict
import json
import logging
import os
from datetime import datetime, timedelta
from functools import wraps

try:
    import redis
    from fastapi_cache2 import FastAPICache
    from fastapi_cache2.backends.redis import RedisBackend
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("Redis not available. Caching will be disabled.")

logger = logging.getLogger(__name__)

# Global cache instance
_cache_client: Optional[Any] = None


def init_cache():
    """Initialize cache backend."""
    global _cache_client
    
    if not REDIS_AVAILABLE:
        logger.info("Redis not available, using in-memory cache")
        _cache_client = InMemoryCache()
        return
    
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        
        # Initialize Redis client
        redis_client = redis.from_url(redis_url)
        
        # Test connection
        redis_client.ping()
        
        # Initialize FastAPI cache
        FastAPICache.init(RedisBackend(redis_client), prefix="sunseat")
        
        _cache_client = RedisCacheClient(redis_client)
        logger.info(f"Redis cache initialized: {redis_url}")
        
    except Exception as e:
        logger.error(f"Failed to initialize Redis cache: {e}")
        logger.info("Falling back to in-memory cache")
        _cache_client = InMemoryCache()


class InMemoryCache:
    """Simple in-memory cache for development/fallback."""
    
    def __init__(self, max_size: int = 1000):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size
    
    def set(self, key: str, value: Any, expire_seconds: int = 300) -> bool:
        """Set cache value with expiration."""
        try:
            # Clean old entries if cache is full
            if len(self.cache) >= self.max_size:
                self._cleanup_expired()
                
                # If still full, remove oldest entries
                if len(self.cache) >= self.max_size:
                    oldest_keys = sorted(self.cache.keys())[:100]
                    for old_key in oldest_keys:
                        del self.cache[old_key]
            
            expire_time = datetime.now() + timedelta(seconds=expire_seconds)
            
            self.cache[key] = {
                'value': value,
                'expire_time': expire_time
            }
            
            return True
            
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get cache value."""
        try:
            if key not in self.cache:
                return None
            
            entry = self.cache[key]
            
            # Check expiration
            if datetime.now() > entry['expire_time']:
                del self.cache[key]
                return None
            
            return entry['value']
            
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete cache entry."""
        try:
            if key in self.cache:
                del self.cache[key]
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    def _cleanup_expired(self):
        """Remove expired entries."""
        now = datetime.now()
        expired_keys = [
            key for key, entry in self.cache.items()
            if now > entry['expire_time']
        ]
        
        for key in expired_keys:
            del self.cache[key]


class RedisCacheClient:
    """Redis cache client wrapper."""
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def set(self, key: str, value: Any, expire_seconds: int = 300) -> bool:
        """Set cache value with expiration."""
        try:
            serialized_value = json.dumps(value, default=str)
            return self.redis.setex(key, expire_seconds, serialized_value)
        except Exception as e:
            logger.error(f"Redis set error: {e}")
            return False
    
    def get(self, key: str) -> Optional[Any]:
        """Get cache value."""
        try:
            value = self.redis.get(key)
            if value is None:
                return None
            return json.loads(value)
        except Exception as e:
            logger.error(f"Redis get error: {e}")
            return None
    
    def delete(self, key: str) -> bool:
        """Delete cache entry."""
        try:
            return bool(self.redis.delete(key))
        except Exception as e:
            logger.error(f"Redis delete error: {e}")
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            return bool(self.redis.exists(key))
        except Exception as e:
            logger.error(f"Redis exists error: {e}")
            return False


def get_cache() -> Optional[Any]:
    """Get global cache client."""
    return _cache_client


def cache_key(*args, **kwargs) -> str:
    """Generate cache key from arguments."""
    key_parts = []
    
    # Add positional arguments
    for arg in args:
        if isinstance(arg, (str, int, float)):
            key_parts.append(str(arg))
        elif isinstance(arg, datetime):
            key_parts.append(arg.isoformat())
        else:
            key_parts.append(str(hash(str(arg))))
    
    # Add keyword arguments
    for k, v in sorted(kwargs.items()):
        if isinstance(v, (str, int, float)):
            key_parts.append(f"{k}:{v}")
        elif isinstance(v, datetime):
            key_parts.append(f"{k}:{v.isoformat()}")
        else:
            key_parts.append(f"{k}:{hash(str(v))}")
    
    return ":".join(key_parts)


def cached(expire_seconds: int = 300, key_prefix: str = ""):
    """
    Decorator for caching function results.
    
    Args:
        expire_seconds: Cache expiration time
        key_prefix: Prefix for cache keys
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_client = get_cache()
            if not cache_client:
                # No cache available, execute function directly
                return func(*args, **kwargs)
            
            # Generate cache key
            func_name = f"{func.__module__}.{func.__name__}"
            key = cache_key(key_prefix, func_name, *args, **kwargs)
            
            # Try to get cached result
            cached_result = cache_client.get(key)
            if cached_result is not None:
                logger.debug(f"Cache hit: {key}")
                return cached_result
            
            # Execute function and cache result
            result = func(*args, **kwargs)
            
            # Cache the result
            cache_client.set(key, result, expire_seconds)
            logger.debug(f"Cache set: {key}")
            
            return result
        
        return wrapper
    return decorator


# Specialized caching functions for common use cases
def cache_solar_calculation(lat: float, lon: float, dt: datetime, 
                          result: tuple, expire_minutes: int = 5):
    """Cache solar calculation results."""
    cache_client = get_cache()
    if not cache_client:
        return
    
    key = cache_key("solar", lat, lon, dt.replace(second=0, microsecond=0))
    cache_client.set(key, result, expire_minutes * 60)


def get_cached_solar_calculation(lat: float, lon: float, dt: datetime) -> Optional[tuple]:
    """Get cached solar calculation."""
    cache_client = get_cache()
    if not cache_client:
        return None
    
    key = cache_key("solar", lat, lon, dt.replace(second=0, microsecond=0))
    return cache_client.get(key)


def cache_gtfs_realtime_data(feed_type: str, data: Any, expire_seconds: int = 30):
    """Cache GTFS-Realtime feed data."""
    cache_client = get_cache()
    if not cache_client:
        return
    
    key = f"gtfs_rt:{feed_type}:latest"
    cache_client.set(key, data, expire_seconds)


def get_cached_gtfs_realtime_data(feed_type: str) -> Optional[Any]:
    """Get cached GTFS-Realtime data."""
    cache_client = get_cache()
    if not cache_client:
        return None
    
    key = f"gtfs_rt:{feed_type}:latest"
    return cache_client.get(key)


def cache_ptv_api_response(endpoint: str, params: dict, response: Any, 
                          expire_seconds: int = 60):
    """Cache PTV API responses."""
    cache_client = get_cache()
    if not cache_client:
        return
    
    key = cache_key("ptv_api", endpoint, **params)
    cache_client.set(key, response, expire_seconds)


def get_cached_ptv_api_response(endpoint: str, params: dict) -> Optional[Any]:
    """Get cached PTV API response."""
    cache_client = get_cache()
    if not cache_client:
        return None
    
    key = cache_key("ptv_api", endpoint, **params)
    return cache_client.get(key)


def invalidate_cache_pattern(pattern: str):
    """Invalidate cache entries matching pattern (Redis only)."""
    cache_client = get_cache()
    if not cache_client or not isinstance(cache_client, RedisCacheClient):
        return
    
    try:
        keys = cache_client.redis.keys(pattern)
        if keys:
            cache_client.redis.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache entries matching {pattern}")
    except Exception as e:
        logger.error(f"Error invalidating cache pattern {pattern}: {e}")


# Cache statistics (for monitoring)
def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    cache_client = get_cache()
    if not cache_client:
        return {"status": "disabled"}
    
    if isinstance(cache_client, InMemoryCache):
        return {
            "backend": "memory",
            "entries": len(cache_client.cache),
            "max_size": cache_client.max_size
        }
    elif isinstance(cache_client, RedisCacheClient):
        try:
            info = cache_client.redis.info()
            return {
                "backend": "redis",
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "keyspace_hits": info.get("keyspace_hits"),
                "keyspace_misses": info.get("keyspace_misses")
            }
        except Exception as e:
            return {"backend": "redis", "error": str(e)}
    
    return {"status": "unknown"}