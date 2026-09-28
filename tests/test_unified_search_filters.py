import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from textual.widgets import Input

from gojeera.components.search import unified_search
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.internal.models.jira import JiraFilterDict
from tests.jira_api_test_utils import build_api_with_mocked_client

OLD_FILTER: JiraFilterDict = {
    'label': 'Old filter',
    'expression': 'project = OLD',
    'source': 'remote',
    'starred': False,
}
NEW_FILTER: JiraFilterDict = {
    'label': 'New filter',
    'expression': 'project = NEW',
    'source': 'remote',
    'starred': True,
}


@pytest.fixture
def filter_bar(monkeypatch, mock_configuration):
    mock_configuration.fetch_remote_filters.enabled = True
    api = Mock(client=Mock(fetch_user_filters=AsyncMock(return_value=[NEW_FILTER])))
    bar = UnifiedSearchBar(api)
    request = Mock()
    monkeypatch.setattr(bar, '_fetch_remote_filters', request)
    monkeypatch.setattr(bar, '_update_jql_placeholder', Mock())

    async def run_inline(callback):
        return callback()

    monkeypatch.setattr(unified_search, 'run_cache_io', run_inline)
    bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
    return bar, request


async def run_filter_fetch(bar, request):
    await cast(Any, UnifiedSearchBar._fetch_remote_filters).__wrapped__(bar, **request.kwargs)


def test_repeated_profile_ready_only_schedules_one_fetch(filter_bar):
    bar, request = filter_bar
    bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
    bar._ensure_remote_filters_loaded()

    request.assert_called_once()
    assert bar._remote_filters_fetch_requested


@pytest.mark.parametrize('filters', [[], [NEW_FILTER]])
async def test_fresh_cache_avoids_api_request(filter_bar, filters):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', filters)

    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == filters
    assert bar._remote_filters_fetched
    assert not bar._remote_filters_fetch_requested
    bar.api.client.fetch_user_filters.assert_not_awaited()
    bar._ensure_remote_filters_loaded()
    assert request.call_count == 2
    await run_filter_fetch(bar, request.call_args)
    bar.api.client.fetch_user_filters.assert_not_awaited()


async def test_failed_refresh_preserves_complete_cache_and_allows_retry(filter_bar, monkeypatch):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=-1)
    api, _ = build_api_with_mocked_client(
        [
            {
                'values': [{'id': '1', 'name': 'Partial', 'jql': 'project = NEW'}],
                'isLast': False,
            },
            RuntimeError('next page failed'),
        ]
    )
    monkeypatch.setattr(bar.api, 'client', api)

    await run_filter_fetch(bar, request.call_args)

    cached = bar._cache.get_remote_filters('user-1', allow_stale=True)
    assert [item.as_filter_dict() for item in cached] == [OLD_FILTER]
    assert bar._remote_filters == [OLD_FILTER]
    assert not bar._remote_filters_fetched
    assert not bar._remote_filters_fetch_requested
    bar._ensure_remote_filters_loaded()
    assert request.call_count == 2


async def test_successful_empty_refresh_clears_stale_filters(filter_bar, monkeypatch):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=-1)
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(return_value=[]))
    autocomplete = Mock()
    monkeypatch.setattr(bar, '_jql_autocomplete', autocomplete)

    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == []
    assert bar._cache.get_remote_filters('user-1') == []
    assert bar._remote_filters_fetched
    autocomplete.update_filters.assert_called_with(
        unified_search.CONFIGURATION.get().jql_filters or []
    )


@pytest.mark.parametrize('stale_read', [False, True])
async def test_cache_read_failure_falls_back_to_jira(filter_bar, monkeypatch, stale_read):
    bar, request = filter_bar
    responses = (
        [None, RuntimeError('cache failed')] if stale_read else [RuntimeError('cache failed')]
    )
    original_get = bar._cache.get_remote_filters
    monkeypatch.setattr(bar._cache, 'get_remote_filters', Mock(side_effect=responses))

    await run_filter_fetch(bar, request.call_args)

    assert not bar._remote_filters_fetch_requested
    assert bar._remote_filters_fetched
    assert bar._remote_filters == [NEW_FILTER]
    bar.api.client.fetch_user_filters.assert_awaited_once()
    assert [item.as_filter_dict() for item in original_get('user-1')] == [NEW_FILTER]


@pytest.mark.parametrize('result', [[], [NEW_FILTER]])
async def test_cache_write_failure_keeps_successful_jira_results(filter_bar, monkeypatch, result):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=-1)
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(return_value=result))
    monkeypatch.setattr(
        bar._cache, 'set_remote_filters', Mock(side_effect=RuntimeError('disk full'))
    )

    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == result
    assert bar._remote_filters_fetched
    assert not bar._remote_filters_fetch_requested
    cached = bar._cache.get_remote_filters('user-1', allow_stale=True)
    assert [item.as_filter_dict() for item in cached] == [OLD_FILTER]


async def test_cache_and_network_failure_keeps_in_memory_filters(filter_bar, monkeypatch):
    bar, request = filter_bar
    bar._merge_remote_filters([OLD_FILTER])
    monkeypatch.setattr(
        bar._cache, 'get_remote_filters', Mock(side_effect=RuntimeError('cache failed'))
    )
    monkeypatch.setattr(
        bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=RuntimeError('offline'))
    )

    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == [OLD_FILTER]
    assert not bar._remote_filters_fetch_requested
    bar._ensure_remote_filters_loaded()
    assert request.call_count == 2


def test_account_change_removes_old_autocomplete_filters(filter_bar, monkeypatch):
    bar, request = filter_bar
    autocomplete = Mock()
    monkeypatch.setattr(bar, '_jql_autocomplete', autocomplete)
    bar._merge_remote_filters([OLD_FILTER])

    bar._handle_account_id_ready(bar.ProfileIsReady('user-2'))

    assert bar._remote_filters is None
    autocomplete.update_filters.assert_called_with(
        unified_search.CONFIGURATION.get().jql_filters or []
    )
    assert request.call_count == 2


@pytest.mark.parametrize('old_finishes_first', [False, True])
@pytest.mark.parametrize('old_fails', [False, True])
async def test_account_generation_rejects_late_results(
    filter_bar, monkeypatch, old_finishes_first, old_fails
):
    bar, request = filter_bar
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(**_kwargs):
        if not started.is_set():
            started.set()
            await release.wait()
            if old_fails:
                raise RuntimeError('old request failed')
            return [OLD_FILTER]
        return [NEW_FILTER]

    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=fetch))
    old_task = asyncio.create_task(run_filter_fetch(bar, request.call_args))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        bar._handle_account_id_ready(bar.ProfileIsReady('user-2'))
        bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
        latest_request = request.call_args
        if old_finishes_first:
            release.set()
            await old_task
            assert bar._remote_filters is None
            assert bar._remote_filters_fetch_requested
            assert bar._cache.get_remote_filters('user-1') is None

        await run_filter_fetch(bar, latest_request)
        release.set()
        await old_task

        assert bar._remote_filters == [NEW_FILTER]
        assert bar._remote_filters_fetched
        assert not bar._remote_filters_fetch_requested
        cached = bar._cache.get_remote_filters('user-1')
        assert [item.as_filter_dict() for item in cached] == [NEW_FILTER]
    finally:
        old_task.cancel()
        await asyncio.gather(old_task, return_exceptions=True)


async def test_filters_fetched_before_autocomplete_initialization_are_retained(
    filter_bar, monkeypatch
):
    bar, request = filter_bar
    await run_filter_fetch(bar, request.call_args)
    assert bar._jql_autocomplete is None

    autocomplete = Mock()
    app = Mock()
    monkeypatch.setattr(UnifiedSearchBar, 'app', property(lambda self: app))
    monkeypatch.setattr(UnifiedSearchBar, 'unified_input', property(lambda self: Input()))
    monkeypatch.setattr(
        'gojeera.widgets.search.search_autocomplete.SearchAutoComplete', autocomplete
    )

    bar._init_jql_autocomplete()

    local_filters = unified_search.CONFIGURATION.get().jql_filters or []
    assert autocomplete.call_args.kwargs['jql_filters'] == local_filters + [NEW_FILTER]
    app.mount.assert_called_once_with(autocomplete.return_value)


@pytest.mark.parametrize('option', ['starred_only', 'include_shared'])
async def test_changed_options_do_not_reuse_previous_results(
    filter_bar, mock_configuration, option
):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', [OLD_FILTER])
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == [OLD_FILTER]

    setattr(mock_configuration.fetch_remote_filters, option, True)
    bar._ensure_remote_filters_loaded()
    assert bar._remote_filters is None
    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == [NEW_FILTER]
    assert bar.api.client.fetch_user_filters.await_args.kwargs[option] is True
    cached = bar._cache.get_remote_filters('user-1', **{option: True})
    assert [item.as_filter_dict() for item in cached] == [NEW_FILTER]
    assert bar._cache.get_remote_filters('user-1')[0].as_filter_dict() == OLD_FILTER


async def test_cached_result_expires_during_same_session(filter_bar, monkeypatch):
    from gojeera.internal.store import cache as cache_module

    bar, request = filter_bar
    now = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: now)
    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=10)
    now += 9
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == [OLD_FILTER]
    bar.api.client.fetch_user_filters.assert_not_awaited()

    now += 2
    bar._ensure_remote_filters_loaded()
    await run_filter_fetch(bar, request.call_args)

    assert bar._remote_filters == [NEW_FILTER]
    bar.api.client.fetch_user_filters.assert_awaited_once()


async def test_empty_api_result_uses_short_ttl_and_refreshes_in_session(filter_bar, monkeypatch):
    from gojeera.internal.store import cache as cache_module

    bar, request = filter_bar
    now = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: now)
    fetch = AsyncMock(side_effect=[[], [NEW_FILTER]])
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', fetch)
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == []

    now += unified_search.EMPTY_REMOTE_FILTER_CACHE_TTL_SECONDS - 1
    bar._ensure_remote_filters_loaded()
    await run_filter_fetch(bar, request.call_args)
    fetch.assert_awaited_once()

    now += 2
    bar._ensure_remote_filters_loaded()
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == [NEW_FILTER]
    assert fetch.await_count == 2


@pytest.mark.parametrize('result', [[], [NEW_FILTER]])
async def test_failed_persistence_never_restores_older_disk_results(
    filter_bar, monkeypatch, result
):
    bar, request = filter_bar
    bar._cache.set_remote_filters('user-1', [OLD_FILTER])
    original_get = bar._cache.get_remote_filters
    read = Mock(side_effect=RuntimeError('temporary read failure'))
    monkeypatch.setattr(bar._cache, 'get_remote_filters', read)
    write = Mock(side_effect=RuntimeError('disk full'))
    monkeypatch.setattr(bar._cache, 'set_remote_filters', write)
    fetch = AsyncMock(side_effect=[result, RuntimeError('offline')])
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', fetch)
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == result

    monkeypatch.setattr(bar._cache, 'get_remote_filters', original_get)
    bar._ensure_remote_filters_loaded()
    await run_filter_fetch(bar, request.call_args)
    assert bar._remote_filters == result
    assert fetch.await_count == 2
