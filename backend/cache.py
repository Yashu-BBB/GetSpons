"""
cache.py — Thread-safe in-memory TTL cache for GetSpons.

No third-party libraries required — uses only Python builtins
(threading, time, fnmatch).

Usage
-----
    from cache import cache

    cache.set("brands_list_None_None", data, ttl_seconds=600)
    value = cache.get("brands_list_None_None")   # None if expired / missing
    cache.delete("brand_detail_abc123")
    cache.clear_pattern("brands_")               # wipe all brand keys
    cache.clear_all()
"""

import fnmatch
import threading
import time
from typing import Any, Optional

from logger import get_logger

log = get_logger(__name__)


class _TTLCache:
    """Simple in-memory key-value store with per-entry TTL expiry.

    All public methods are thread-safe via a single reentrant lock.
    """

    def __init__(self) -> None:
        # { key: (value, expires_at_unix_float) }
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock  = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for *key*, or ``None`` if missing/expired.

        Parameters
        ----------
        key:
            Cache key string.

        Returns
        -------
        Any | None
        """
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                log.debug("Cache MISS | key=%s", key)
                return None

            value, expires_at = entry
            if time.time() > expires_at:
                # Lazy eviction — remove stale entry on first access
                del self._store[key]
                log.debug("Cache EXPIRED | key=%s", key)
                return None

            log.debug("Cache HIT | key=%s", key)
            return value

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store *value* under *key* with a TTL of *ttl_seconds*.

        Parameters
        ----------
        key:
            Cache key string.
        value:
            Any picklable Python object.
        ttl_seconds:
            Seconds until the entry expires.  Default 300 (5 min).
        """
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = (value, expires_at)
        log.debug("Cache SET | key=%s | ttl=%ds", key, ttl_seconds)

    def delete(self, key: str) -> bool:
        """Remove a specific key from the cache.

        Parameters
        ----------
        key:
            Cache key to remove.

        Returns
        -------
        bool
            ``True`` if the key existed and was removed, ``False`` otherwise.
        """
        with self._lock:
            existed = key in self._store
            self._store.pop(key, None)
        if existed:
            log.debug("Cache DELETE | key=%s", key)
        return existed

    def clear_pattern(self, pattern: str) -> int:
        """Remove all keys whose name contains *pattern* (substring match).

        Parameters
        ----------
        pattern:
            Substring to match against cache keys.
            Also supports shell-style wildcards via ``fnmatch``
            (e.g. ``"brand_*"``).

        Returns
        -------
        int
            Number of keys removed.
        """
        with self._lock:
            if any(c in pattern for c in ("*", "?", "[", "]")):
                # Wildcard pattern — use fnmatch
                to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
            else:
                # Plain substring match
                to_delete = [k for k in self._store if pattern in k]

            for key in to_delete:
                del self._store[key]

        count = len(to_delete)
        log.debug("Cache CLEAR_PATTERN | pattern=%s | removed=%d", pattern, count)
        return count

    def clear_all(self) -> int:
        """Clear every entry from the cache.

        Returns
        -------
        int
            Number of entries removed.
        """
        with self._lock:
            count = len(self._store)
            self._store.clear()
        log.info("Cache CLEAR_ALL | removed=%d entries", count)
        return count

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return basic cache statistics (useful for health checks)."""
        now = time.time()
        with self._lock:
            total   = len(self._store)
            expired = sum(1 for _, (_, exp) in self._store.items() if now > exp)
        return {"total_keys": total, "expired_keys": expired, "live_keys": total - expired}


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere
# ---------------------------------------------------------------------------

cache = _TTLCache()