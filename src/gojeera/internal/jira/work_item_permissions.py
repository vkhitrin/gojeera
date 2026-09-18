from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from time import monotonic
from typing import TYPE_CHECKING

from gojeera.internal.jira.controller import APIControllerResponse

if TYPE_CHECKING:
    from gojeera.app import JiraApp


ADD_COMMENTS_PERMISSION = 'ADD_COMMENTS'
BROWSE_PROJECTS_PERMISSION = 'BROWSE_PROJECTS'
VIEW_VOTERS_AND_WATCHERS_PERMISSION = 'VIEW_VOTERS_AND_WATCHERS'

ADD_COMMENT_PERMISSIONS = (BROWSE_PROJECTS_PERMISSION, ADD_COMMENTS_PERMISSION)
VIEW_WATCHERS_PERMISSIONS = (
    BROWSE_PROJECTS_PERMISSION,
    VIEW_VOTERS_AND_WATCHERS_PERMISSION,
)
PERMISSION_CACHE_TTL_SECONDS = 300.0
PERMISSION_CACHE_MAX_ENTRIES = 256

MISSING_ADD_COMMENT_PERMISSION_ERROR_PREFIX = 'Missing required permission(s) to add comments:'


class WorkItemPermissionCache:
    """Per-widget cache for issue-context Jira permission checks."""

    def __init__(
        self,
        *,
        app_getter: Callable[[], JiraApp],
        on_loaded: Callable[[str, tuple[str, ...], APIControllerResponse | None], None]
        | None = None,
    ) -> None:
        self._app_getter = app_getter
        self._on_loaded = on_loaded
        self._cache: OrderedDict[
            tuple[str, tuple[str, ...]],
            tuple[float, APIControllerResponse | None],
        ] = OrderedDict()
        self._inflight: dict[
            tuple[str, tuple[str, ...]],
            asyncio.Task[APIControllerResponse | None],
        ] = {}

    @staticmethod
    def _cache_key(
        work_item_key: str,
        permissions: tuple[str, ...],
    ) -> tuple[str, tuple[str, ...]]:
        return work_item_key, tuple(permissions)

    def cached_response(
        self,
        work_item_key: str,
        permissions: tuple[str, ...],
    ) -> APIControllerResponse | None:
        found, response = self._cached_entry(self._cache_key(work_item_key, permissions))
        return response if found else None

    def _cached_entry(
        self,
        cache_key: tuple[str, tuple[str, ...]],
    ) -> tuple[bool, APIControllerResponse | None]:
        cached = self._cache.get(cache_key)
        if cached is None:
            return False, None
        expires_at, response = cached
        if expires_at <= monotonic():
            self._cache.pop(cache_key, None)
            return False, None
        self._cache.move_to_end(cache_key)
        return True, response

    def _store(
        self,
        cache_key: tuple[str, tuple[str, ...]],
        response: APIControllerResponse | None,
    ) -> None:
        self._cache[cache_key] = (monotonic() + PERMISSION_CACHE_TTL_SECONDS, response)
        self._cache.move_to_end(cache_key)
        while len(self._cache) > PERMISSION_CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)

    async def load(
        self, work_item_key: str, permissions: tuple[str, ...], *, action_name: str
    ) -> APIControllerResponse | None:
        cache_key = self._cache_key(work_item_key, permissions)
        task = self._inflight.get(cache_key)
        if task is None:
            task = asyncio.create_task(
                self._load_uncached(cache_key, work_item_key, permissions, action_name)
            )
            self._inflight[cache_key] = task
        try:
            return await task
        finally:
            if task.done() and self._inflight.get(cache_key) is task:
                self._inflight.pop(cache_key, None)

    async def get(
        self,
        work_item_key: str,
        permissions: tuple[str, ...],
        *,
        action_name: str,
    ) -> APIControllerResponse | None:
        cache_key = self._cache_key(work_item_key, permissions)
        found, response = self._cached_entry(cache_key)
        if found:
            return response

        return await self.load(work_item_key, permissions, action_name=action_name)

    async def _load_uncached(
        self,
        cache_key: tuple[str, tuple[str, ...]],
        work_item_key: str,
        permissions: tuple[str, ...],
        action_name: str,
    ) -> APIControllerResponse | None:
        found, cached_response = self._cached_entry(cache_key)
        if found:
            return cached_response

        app = self._app_getter()
        permission_response = await app.api.validate_work_item_permissions(
            work_item_key,
            list(permissions),
            action_name=action_name,
        )
        self._store(cache_key, permission_response)
        if self._on_loaded is not None:
            self._on_loaded(work_item_key, permissions, permission_response)
        return permission_response
