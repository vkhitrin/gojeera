"""Non-snapshot checks for the HTTP fixtures and visual-test setup."""

import pytest
from textual.widgets import TabPane

from gojeera.widgets.layout.extended_table import ExtendedTable

from .for_you_test_helpers import (
    FOR_YOU_ROW_COUNTS,
    prepare_for_you_tab,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('for_you_app', ['textual-dark', 'textual-light'], indirect=True)
@pytest.mark.parametrize('section', ['due', 'updated', 'mentions'])
@pytest.mark.parametrize('mock_jira_api_for_you', ['populated', 'empty', 'loading'], indirect=True)
async def test_for_you_fixture_driven_tab_state(for_you_app, mock_jira_api_for_you, section):
    state = mock_jira_api_for_you
    async with for_you_app.run_test(size=(120, 40)) as pilot:
        screen = await prepare_for_you_tab(pilot, section, state)
        pane = screen.query_one(f'#for-you-{section}', TabPane)
        table = screen.query_one(f'#{section}-table', ExtendedTable)
        assert sorted(state.searches) == ['due', 'mentions', 'updated']
        assert list(pane.children) == [table]
        assert screen.tabs.get_tab(pane).tooltip is None

        if state.mode == 'loading':
            assert pane.loading
            assert pane._cover_widget is not None
            assert (
                pane._cover_widget.styles.background
                == screen.query_one('#modal_outer').styles.background
            )
            assert state.comment_keys == []
        else:
            assert not pane.loading
            assert table.region.height > 0
            assert table.row_count == (
                FOR_YOU_ROW_COUNTS[section] if state.mode == 'populated' else 0
            )
            if state.mode == 'empty':
                assert state.comment_keys == []
            else:
                assert sorted(state.comment_keys) == ['ENG-104', 'ENG-105', 'SUP-22']
                due = screen.query_one('#due-table', ExtendedTable)
                assert due.get_row_at(1)[1].plain == 'Review [release] readiness checklist'
                assert due.get_row_at(0)[3].plain == '2026-06-29'
                mentions = screen.query_one('#mentions-table', ExtendedTable)
                assert [
                    mentions.get_row_at(index)[0].plain for index in range(mentions.row_count)
                ] == ['ENG-104', 'SUP-22']
                assert mentions.get_row_at(0)[3].plain == '2026-07-01 05:00'
                assert mentions.get_row_at(1)[3].plain == '2026-06-30 19:30'
        await pilot.press('escape')
