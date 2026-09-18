import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.jira.work_item_permissions import (
    ADD_COMMENT_PERMISSIONS,
    PERMISSION_CACHE_MAX_ENTRIES,
    WorkItemPermissionCache,
)


async def test_permission_cache_coalesces_matching_inflight_requests() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def validate_permissions(*args: Any, **kwargs: Any) -> APIControllerResponse:
        del args, kwargs
        started.set()
        await release.wait()
        return APIControllerResponse(result=True)

    request = AsyncMock(side_effect=validate_permissions)
    app = SimpleNamespace(api=SimpleNamespace(validate_work_item_permissions=request))
    cache = WorkItemPermissionCache(app_getter=lambda: cast(Any, app))

    first = asyncio.create_task(
        cache.get('ENG-1', ADD_COMMENT_PERMISSIONS, action_name='add comments')
    )
    await started.wait()
    second = asyncio.create_task(
        cache.get('ENG-1', ADD_COMMENT_PERMISSIONS, action_name='add comments')
    )
    await asyncio.sleep(0)
    release.set()

    first_response, second_response = await asyncio.gather(first, second)

    assert first_response is second_response
    request.assert_awaited_once()


def test_permission_cache_entries_expire(monkeypatch) -> None:
    import gojeera.internal.jira.work_item_permissions as permission_module

    current_time = 1000.0
    monkeypatch.setattr(permission_module, 'monotonic', lambda: current_time)
    cache = WorkItemPermissionCache(app_getter=lambda: cast(Any, None))
    cache_key = cache._cache_key('ENG-1', ADD_COMMENT_PERMISSIONS)
    response = APIControllerResponse(result=True)

    cache._store(cache_key, response)
    assert cache.cached_response('ENG-1', ADD_COMMENT_PERMISSIONS) is response

    current_time += permission_module.PERMISSION_CACHE_TTL_SECONDS + 1
    assert cache.cached_response('ENG-1', ADD_COMMENT_PERMISSIONS) is None
    assert cache_key not in cache._cache


def test_permission_cache_is_bounded() -> None:
    cache = WorkItemPermissionCache(app_getter=lambda: cast(Any, None))

    for index in range(PERMISSION_CACHE_MAX_ENTRIES + 1):
        cache._store(
            cache._cache_key(f'ENG-{index}', ADD_COMMENT_PERMISSIONS),
            APIControllerResponse(result=True),
        )

    assert len(cache._cache) == PERMISSION_CACHE_MAX_ENTRIES
    assert cache._cache_key('ENG-0', ADD_COMMENT_PERMISSIONS) not in cache._cache
