from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

from gojeera.internal.models.jira import JiraUser
from gojeera.internal.store.cache import ApplicationCache
from gojeera.utils.ui import mention_helpers


async def test_cached_mention_users_are_loaded_through_async_cache_io(monkeypatch) -> None:
    user = JiraUser(account_id='account-1', active=True, display_name='Ada')
    cache = Mock(spec=ApplicationCache, **{'get_project_users.return_value': [user]})

    async def run_cache_io(operation: Callable[[], Any]) -> Any:
        return operation()

    cache_io = AsyncMock(side_effect=run_cache_io)
    monkeypatch.setattr(mention_helpers, 'run_cache_io', cache_io)

    textarea = SimpleNamespace(cursor_location=(0, 0))
    target_widget = Mock(**{'query_one.return_value': textarea})
    app = SimpleNamespace(
        api=SimpleNamespace(client=SimpleNamespace(base_url='https://jira.example.com')),
        push_screen_wait=AsyncMock(return_value=None),
        notify=Mock(),
    )

    await mention_helpers.insert_user_mention(
        app,
        target_widget,
        project_key='ENG',
        cache=cache,
    )

    cache_io.assert_awaited_once()
    cache.get_project_users.assert_called_once_with('ENG')
    app.push_screen_wait.assert_awaited_once()
    app.notify.assert_not_called()
