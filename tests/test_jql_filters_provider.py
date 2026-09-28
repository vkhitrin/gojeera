from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from gojeera.commands.providers.jql_filters_provider import (
    JQL_FILTERS_PALETTE_ID,
    MAX_DISPLAYED_FILTERS,
    JQLFiltersProvider,
)
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.widgets.layout.sub_palette import is_command_palette_notice


def provider_app():
    return SimpleNamespace(
        active_sub_command_palette_id=JQL_FILTERS_PALETTE_ID,
        atlassian_context=SimpleNamespace(user_info=SimpleNamespace(account_id='user-1')),
        unified_search_bar=SimpleNamespace(remote_filter_revision=0),
    )


async def test_jql_filter_provider_reuses_prepared_filters_between_queries() -> None:
    app = provider_app()
    provider = JQLFiltersProvider(cast(Any, SimpleNamespace(app=app)))
    provider._get_jql_filters = AsyncMock(
        return_value=[
            {
                'label': 'Open engineering work',
                'expression': 'project = ENG AND status != Done',
                'source': 'remote',
                'starred': True,
            }
        ]
    )

    first_result = [hit async for hit in provider.search('open')]
    second_result = [hit async for hit in provider.search('engineering')]

    assert [hit.text for hit in first_result] == ['[Remote ★] Open engineering work']
    assert [hit.text for hit in second_result] == ['[Remote ★] Open engineering work']
    provider._get_jql_filters.assert_awaited_once()

    provider._sorted_jql_filters_expires_at = 0.0
    [hit async for hit in provider.search('done')]

    assert provider._get_jql_filters.await_count == 2


async def test_jql_filter_provider_starts_large_result_sets_with_notice() -> None:
    app = provider_app()
    provider = JQLFiltersProvider(cast(Any, SimpleNamespace(app=app)))
    provider._get_jql_filters = AsyncMock(
        return_value=[
            {
                'label': f'Open work filter {index}',
                'expression': f'project = ENG AND status != Done AND key != ENG-{index}',
                'source': 'remote',
            }
            for index in range(MAX_DISPLAYED_FILTERS + 25)
        ]
    )

    discovered_results = [hit async for hit in provider.discover()]
    search_results = [hit async for hit in provider.search('open')]

    for results in (discovered_results, search_results):
        assert len(results) == MAX_DISPLAYED_FILTERS + 1
        assert is_command_palette_notice(results[0])
        assert results[0].text == (
            f'{MAX_DISPLAYED_FILTERS}-result limit: showing '
            f'{MAX_DISPLAYED_FILTERS} of {MAX_DISPLAYED_FILTERS + 25} matches.'
        )


@pytest.mark.parametrize(
    'starred_only,include_shared', [(True, False), (False, True), (True, True)]
)
async def test_provider_reads_only_matching_filter_scope(
    application_cache, mock_configuration, monkeypatch, starred_only, include_shared
):
    config = mock_configuration.fetch_remote_filters
    config.enabled = True
    config.starred_only = starred_only
    config.include_shared = include_shared
    matching = {
        'label': 'Matching',
        'expression': 'project = ENG',
        'source': 'remote',
        'starred': True,
    }
    application_cache.set_remote_filters(
        'user-1', [{'label': 'Other scope', 'expression': 'project = OTHER'}]
    )
    application_cache.set_remote_filters(
        'user-1', [matching], starred_only=starred_only, include_shared=include_shared
    )
    app = provider_app()
    app.unified_search_bar = UnifiedSearchBar(Mock())
    monkeypatch.setattr(app.unified_search_bar, '_fetch_remote_filters', Mock())
    provider = JQLFiltersProvider(cast(Any, SimpleNamespace(app=app)))

    assert await provider._get_jql_filters() == (mock_configuration.jql_filters or []) + [matching]
    config.enabled = False
    assert await provider._get_jql_filters() == (mock_configuration.jql_filters or [])
