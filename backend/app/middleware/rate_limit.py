from fastapi import Depends, HTTPException, Request

from app.middleware.redis_client import get_redis


def rate_limit(limit: int, window_seconds: int):
    async def dependency(request: Request, redis=Depends(get_redis)):
        ip = request.client.host if request.client else "unknown"
        route = request.scope.get("route")
        route_path = route.path if route else request.url.path
        key = f"rate:{route_path}:{ip}"

        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_seconds)
        if count > limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests, please try again later",
            )

    return dependency
