from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

from gojeera.commands.providers.jql_filters_provider import (
    JQL_FILTERS_PALETTE_ID,
    MAX_DISPLAYED_FILTERS,
    JQLFiltersProvider,
)
from gojeera.widgets.layout.sub_palette import is_command_palette_notice


async def test_jql_filter_provider_reuses_prepared_filters_between_queries() -> None:
    app = SimpleNamespace(active_sub_command_palette_id=JQL_FILTERS_PALETTE_ID)
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
    app = SimpleNamespace(active_sub_command_palette_id=JQL_FILTERS_PALETTE_ID)
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
