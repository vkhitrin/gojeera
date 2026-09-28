import asyncio
import threading
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from textual.app import App

from gojeera.commands.providers.jql_filters_provider import JQLFiltersProvider
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.internal.store.cache import CACHE_STALE_REMOTE_FILTERS
from tests.test_helpers import wait_until
from tests.test_unified_search_filters import NEW_FILTER, OLD_FILTER


def filter_provider(bar):
    app = SimpleNamespace(
        unified_search_bar=bar,
        atlassian_context=SimpleNamespace(user_info=SimpleNamespace(account_id='user-1')),
    )
    return JQLFiltersProvider(cast(Any, SimpleNamespace(app=app)))


@pytest.fixture
async def filter_app(monkeypatch, mock_configuration):
    mock_configuration.fetch_remote_filters.enabled = True
    bar = UnifiedSearchBar(
        Mock(client=Mock(fetch_user_filters=AsyncMock(return_value=[NEW_FILTER])))
    )
    monkeypatch.setattr(bar, '_sync_results_controls_state', Mock())
    async with App().run_test() as pilot:
        await pilot.app.mount(bar)
        yield bar, pilot


async def test_switching_account_cancels_previous_network_worker(filter_app, monkeypatch):
    bar, _ = filter_app
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fetch(account_id, **_kwargs):
        if account_id == 'old':
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        return [NEW_FILTER]

    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=fetch))
    bar._handle_account_id_ready(bar.ProfileIsReady('old'))
    await asyncio.wait_for(started.wait(), timeout=2)
    bar._handle_account_id_ready(bar.ProfileIsReady('new'))
    await asyncio.wait_for(cancelled.wait(), timeout=2)
    await wait_until(lambda: bar._remote_filters == [NEW_FILTER])

    assert bar._remote_filters == [NEW_FILTER]
    assert not bar._remote_filters_fetch_requested
    assert bar._cache.get_remote_filters('old') is None


@pytest.mark.parametrize('operation', ['get_remote_filters', 'set_remote_filters'])
async def test_cancelled_worker_with_delayed_cache_io_cannot_replace_current_filters(
    filter_app, monkeypatch, operation
):
    bar, pilot = filter_app
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original = getattr(bar._cache, operation)
    event_loop_thread = threading.get_ident()

    def delayed(account_id, *args, **kwargs):
        assert threading.get_ident() != event_loop_thread
        if account_id != 'old':
            return original(account_id, *args, **kwargs)
        started.set()
        try:
            if not release.wait(timeout=5):
                raise TimeoutError('cache operation was not released')
            return original(account_id, *args, **kwargs)
        finally:
            finished.set()

    async def fetch(account_id, **_kwargs):
        return [OLD_FILTER] if account_id == 'old' else [NEW_FILTER]

    monkeypatch.setattr(bar._cache, operation, delayed)
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=fetch))
    bar._handle_account_id_ready(bar.ProfileIsReady('old'))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        old_worker = next(
            worker for worker in pilot.app.workers if worker.group == 'remote-filters'
        )
        bar._handle_account_id_ready(bar.ProfileIsReady('new'))
        await wait_until(lambda: bar._remote_filters == [NEW_FILTER])
        assert old_worker.is_cancelled
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()

        assert bar._remote_filters == [NEW_FILTER]
        assert not bar._remote_filters_fetch_requested
        # Read through the unpatched API, since direct test assertions run on the event loop.
        monkeypatch.setattr(bar._cache, operation, original)
        cached = bar._cache.get_remote_filters('new')
        assert cached is not None
        assert [item.as_filter_dict() for item in cached] == [NEW_FILTER]
    finally:
        release.set()
        await asyncio.to_thread(finished.wait, 2)


async def test_reopening_jql_mode_refreshes_expired_filters(filter_app, monkeypatch):
    bar, pilot = filter_app
    fetch = AsyncMock(side_effect=[[OLD_FILTER], [NEW_FILTER]])
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', fetch)
    bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
    await pilot.app.workers.wait_for_complete()
    assert bar._remote_filters == [OLD_FILTER]

    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=-1)
    bar.action_switch_search_mode('jql')
    await wait_until(lambda: bar._remote_filters == [NEW_FILTER])
    assert fetch.await_count == 2
    assert bar._jql_autocomplete is not None
    assert bar._jql_autocomplete.has_filter_expression(NEW_FILTER['expression'])


@pytest.mark.parametrize('change', ['account', 'options'])
async def test_obsolete_threaded_write_cannot_overwrite_newer_same_scope(
    filter_app, monkeypatch, mock_configuration, change
):
    bar, pilot = filter_app
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    original_set = bar._cache.set_remote_filters
    fetch = AsyncMock(side_effect=[[OLD_FILTER], [NEW_FILTER]])
    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', fetch)

    def delayed_set(account_id, filters, **kwargs):
        if filters != [OLD_FILTER]:
            return original_set(account_id, filters, **kwargs)
        started.set()
        try:
            if not release.wait(timeout=5):
                raise TimeoutError('cache write was not released')
            return original_set(account_id, filters, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(bar._cache, 'set_remote_filters', delayed_set)
    bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if change == 'account':
            bar._handle_account_id_ready(bar.ProfileIsReady('user-2'))
            bar._handle_account_id_ready(bar.ProfileIsReady('user-1'))
        else:
            mock_configuration.fetch_remote_filters.starred_only = True
            bar._ensure_remote_filters_loaded()
            mock_configuration.fetch_remote_filters.starred_only = False
            bar._ensure_remote_filters_loaded()
        await wait_until(
            lambda: bar._remote_filters == [NEW_FILTER] and not bar._remote_filters_fetch_requested
        )
        release.set()
        assert await asyncio.to_thread(finished.wait, 2)
        cached = bar._cache.get_remote_filters('user-1')
        assert [item.as_filter_dict() for item in cached] == [NEW_FILTER]

        bar._ensure_remote_filters_loaded()
        await wait_until(lambda: not bar._remote_filters_fetch_requested)
        assert bar._remote_filters == [NEW_FILTER]
        assert fetch.await_count == 2
        await pilot.pause()
    finally:
        release.set()
        await asyncio.to_thread(finished.wait, 2)


async def test_palette_only_session_refreshes_hard_expired_filters(filter_app):
    bar, pilot = filter_app
    bar._cache.set_remote_filters(
        'user-1', [OLD_FILTER], ttl_seconds=-CACHE_STALE_REMOTE_FILTERS - 1
    )
    provider = filter_provider(bar)
    filters = await provider._get_jql_filters()
    assert NEW_FILTER in filters
    assert OLD_FILTER not in filters
    assert bar.search_mode == 'basic'
    await pilot.app.workers.wait_for_complete()
    bar.api.client.fetch_user_filters.assert_awaited_once()


async def test_palette_serves_stale_filters_then_invalidates_prepared_results(
    filter_app, monkeypatch
):
    bar, pilot = filter_app
    bar._cache.set_remote_filters('user-1', [OLD_FILTER], ttl_seconds=-1)
    release = asyncio.Event()

    async def fetch(**_kwargs):
        await release.wait()
        return [NEW_FILTER]

    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=fetch))
    provider = filter_provider(bar)
    try:
        initial = await asyncio.wait_for(provider._iter_filters(), timeout=1)
        assert any(item.expression == OLD_FILTER['expression'] for item in initial)
        release.set()
        await wait_until(lambda: bar._remote_filters == [NEW_FILTER])
        updated = await provider._iter_filters()
        assert any(item.expression == NEW_FILTER['expression'] for item in updated)
        assert not any(item.expression == OLD_FILTER['expression'] for item in updated)
        await pilot.app.workers.wait_for_complete()
        bar.api.client.fetch_user_filters.assert_awaited_once()
    finally:
        release.set()


async def test_palette_uses_live_results_when_cache_write_fails(filter_app, monkeypatch):
    bar, _ = filter_app
    monkeypatch.setattr(
        bar._cache, 'set_remote_filters', Mock(side_effect=RuntimeError('disk full'))
    )
    assert NEW_FILTER in await filter_provider(bar)._get_jql_filters()
    assert bar._cache.get_remote_filters('user-1') is None


async def test_cancelled_palette_query_does_not_cancel_shared_refresh(filter_app, monkeypatch):
    bar, pilot = filter_app
    started = asyncio.Event()
    release = asyncio.Event()

    async def fetch(**_kwargs):
        started.set()
        await release.wait()
        return [NEW_FILTER]

    monkeypatch.setattr(bar.api.client, 'fetch_user_filters', AsyncMock(side_effect=fetch))
    query = asyncio.create_task(filter_provider(bar)._get_jql_filters())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        await pilot.pause()
        query.cancel()
        await asyncio.gather(query, return_exceptions=True)
        assert bar._remote_filters_worker is not None
        assert not bar._remote_filters_worker.is_cancelled
        release.set()
        await wait_until(lambda: not bar._remote_filters_fetch_requested)
        assert bar._remote_filters == [NEW_FILTER]
    finally:
        release.set()
        query.cancel()
        await asyncio.gather(query, return_exceptions=True)
