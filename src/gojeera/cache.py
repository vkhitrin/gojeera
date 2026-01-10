"""Cache service for storing frequently accessed Jira data."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Generic, TypeVar

from gojeera.constants import (
    CACHE_TTL_PROJECT_STATUSES,
    CACHE_TTL_PROJECT_TYPES,
    CACHE_TTL_PROJECT_USERS,
    CACHE_TTL_PROJECTS,
    CACHE_TTL_REMOTE_FILTERS,
    CACHE_TTL_STATUSES,
    CACHE_TTL_TYPES,
    CACHE_TTL_USERS,
)

T = TypeVar('T')


class CacheEntry(Generic[T]):
    """Represents a single cache entry with data and metadata."""

    def __init__(self, data: T, ttl_seconds: int | None = None):
        self.data = data
        self.created_at = datetime.now()
        self.ttl_seconds = ttl_seconds

    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return datetime.now() > self.created_at + timedelta(seconds=self.ttl_seconds)


class ApplicationCache:
    """Application-level cache for Jira data."""

    def __init__(self):
        self._cache: dict[str, CacheEntry[Any]] = {}

        self._default_ttls = {
            'projects': CACHE_TTL_PROJECTS,
            'users': CACHE_TTL_USERS,
            'types': CACHE_TTL_TYPES,
            'statuses': CACHE_TTL_STATUSES,
            'project_users': CACHE_TTL_PROJECT_USERS,
            'project_types': CACHE_TTL_PROJECT_TYPES,
            'project_statuses': CACHE_TTL_PROJECT_STATUSES,
            'remote_filters': CACHE_TTL_REMOTE_FILTERS,
        }

    def _make_key(self, cache_type: str, identifier: str | None = None) -> str:
        if identifier:
            return f'{cache_type}:{identifier}'
        return cache_type

    def get(self, cache_type: str, identifier: str | None = None) -> Any | None:
        key = self._make_key(cache_type, identifier)
        entry = self._cache.get(key)

        if entry is None:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        return entry.data

    def set(
        self,
        cache_type: str,
        data: Any,
        identifier: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        key = self._make_key(cache_type, identifier)

        if ttl_seconds is None:
            ttl_seconds = self._default_ttls.get(cache_type)

        self._cache[key] = CacheEntry(data, ttl_seconds)

    def clear(self) -> None:
        self._cache.clear()

    def get_stats(self) -> dict[str, Any]:
        total_entries = len(self._cache)
        expired_entries = sum(1 for entry in self._cache.values() if entry.is_expired())

        return {
            'total_entries': total_entries,
            'expired_entries': expired_entries,
            'active_entries': total_entries - expired_entries,
            'cache_types': list({key.split(':')[0] for key in self._cache.keys()}),
        }


_global_cache: ApplicationCache | None = None


def get_cache() -> ApplicationCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = ApplicationCache()
    return _global_cache
