"""Token revocation blacklist backed by Redis, with in-memory fallback for dev.

Tokens are identified by their `jti` (JWT ID) claim.  On logout the jti is added
with a TTL equal to the token's remaining lifetime.  Every authenticated request
checks the blacklist; revoked tokens are rejected with 401.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis

log = logging.getLogger(__name__)

# Module-level Redis client — set in app lifespan, None in dev without Redis.
_redis: redis.Redis | None = None  # type: ignore[name-defined]

# In-memory fallback (single-process dev only).
_mem: dict[str, float] = {}  # jti → expiry unix timestamp


def init(url: str | None = None) -> None:
    """Connect to Redis.  Called from app lifespan; safe to call multiple times."""
    global _redis
    url = url or os.environ.get("ARROW_REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis as _redislib

        client = _redislib.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2
        )
        client.ping()
        _redis = client
        log.info("Token blacklist: connected to Redis at %s", url)
    except Exception as exc:
        log.warning(
            "Token blacklist: Redis unavailable (%s) — using in-memory fallback", exc
        )
        _redis = None


def revoke(jti: str, exp: int) -> None:
    """Add jti to the blacklist until its expiry timestamp."""
    ttl = max(int(exp - datetime.now(timezone.utc).timestamp()), 1)
    if _redis is not None:
        _redis.setex(f"bl:{jti}", ttl, "1")
    else:
        _mem[jti] = float(exp)
        _purge_mem()


def is_revoked(jti: str) -> bool:
    """Return True if the token has been revoked."""
    if _redis is not None:
        return bool(_redis.exists(f"bl:{jti}"))
    _purge_mem()
    exp = _mem.get(jti)
    if exp is None:
        return False
    return datetime.now(timezone.utc).timestamp() < exp


def _purge_mem() -> None:
    now = datetime.now(timezone.utc).timestamp()
    expired = [k for k, v in _mem.items() if v <= now]
    for k in expired:
        del _mem[k]
