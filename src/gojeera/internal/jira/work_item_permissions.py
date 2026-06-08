from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, cast

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

MISSING_ADD_COMMENT_PERMISSION_ERROR_PREFIX = 'Missing required permission(s) to add comments:'


class WorkItemPermissionCache:
    """Per-widget cache for issue-context Jira permission checks."""

    def __init__(
        self,
        *,
        app_getter: Callable[[], JiraApp],
        run_worker: Callable[[], Callable[..., Any]],
        is_mounted: Callable[[], bool],
        group: str,
        on_loaded: Callable[[str, tuple[str, ...], APIControllerResponse | None], None]
        | None = None,
    ) -> None:
        self._app_getter = app_getter
        self._run_worker = run_worker
        self._is_mounted = is_mounted
        self._group = group
        self._on_loaded = on_loaded
        self._cache: dict[tuple[str, tuple[str, ...]], APIControllerResponse | None] = {}
        self._workers: dict[tuple[str, tuple[str, ...]], Any] = {}

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
        return self._cache.get(self._cache_key(work_item_key, permissions))

    def start_load(
        self,
        work_item_key: str,
        permissions: tuple[str, ...],
        *,
        action_name: str,
        exclusive: bool = False,
    ) -> None:
        cache_key = self._cache_key(work_item_key, permissions)
        if cache_key in self._cache or not self._is_mounted():
            return

        worker = self._workers.get(cache_key)
        if worker is not None and not worker.is_finished:
            return

        self._workers[cache_key] = self._run_worker()(
            self.load(work_item_key, permissions, action_name=action_name),
            exclusive=exclusive,
            group=self._group,
        )

    async def load(
        self, work_item_key: str, permissions: tuple[str, ...], *, action_name: str
    ) -> APIControllerResponse | None:
        cache_key = self._cache_key(work_item_key, permissions)
        return await self._load_uncached(cache_key, work_item_key, permissions, action_name)

    async def get(
        self,
        work_item_key: str,
        permissions: tuple[str, ...],
        *,
        action_name: str,
    ) -> APIControllerResponse | None:
        cache_key = self._cache_key(work_item_key, permissions)
        if cache_key in self._cache:
            return self._cache[cache_key]

        worker = self._workers.get(cache_key)
        if worker is not None and not worker.is_finished:
            return cast(APIControllerResponse | None, await worker.wait())

        return await self.load(work_item_key, permissions, action_name=action_name)

    async def _load_uncached(
        self,
        cache_key: tuple[str, tuple[str, ...]],
        work_item_key: str,
        permissions: tuple[str, ...],
        action_name: str,
    ) -> APIControllerResponse | None:
        if cache_key in self._cache:
            return self._cache[cache_key]

        app = self._app_getter()
        permission_response = await app.api.validate_work_item_permissions(
            work_item_key,
            list(permissions),
            action_name=action_name,
        )
        self._cache[cache_key] = permission_response
        if self._on_loaded is not None:
            self._on_loaded(work_item_key, permissions, permission_response)
        return permission_response
