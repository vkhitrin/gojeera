import asyncio
from collections import Counter
from unittest.mock import Mock

import pytest
from textual.widgets import TabPane

from gojeera.internal.jira.for_you import ForYouEntry, ForYouResult, ForYouService
from gojeera.internal.models.jira import WorkItemStatus
from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.widgets.layout.extended_table import ExtendedTable

from .for_you_test_helpers import FOR_YOU_SECTIONS
from .test_helpers import wait_until


@pytest.mark.asyncio
async def test_refresh_cancels_inflight_sections_without_stale_rows_or_notifications(
    for_you_app, monkeypatch
):
    attempts = Counter()
    cancelled = Counter()
    release = asyncio.Event()

    async def load(_service, section, _account_id):
        attempts[section] += 1
        generation = attempts[section]
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled[section] += 1
            raise
        if generation < 3:
            return ForYouResult(error='Stale request failed')
        item = JiraWorkItem(
            id=section,
            key=f'FRESH-{section}',
            summary='Latest refresh',
            status=WorkItemStatus(id='1', name='Open'),
        )
        return ForYouResult(entries=[ForYouEntry(item)])

    monkeypatch.setattr(ForYouService, 'load', load)
    async with for_you_app.run_test(size=(120, 40)) as pilot:
        notify = Mock()
        monkeypatch.setattr(for_you_app, 'notify', notify)
        await for_you_app.action_show_for_you()
        screen = for_you_app.screen
        await pilot.press(']')
        for generation in range(1, 4):
            await wait_until(
                lambda expected=generation: all(attempts[s] == expected for s in FOR_YOU_SECTIONS)
            )
            assert all(pane.loading for pane in screen.query(TabPane))
            if generation < 3:
                await pilot.press('ctrl+r')
        assert all(cancelled[s] == 2 for s in FOR_YOU_SECTIONS)
        assert screen.tabs.active == 'for-you-updated'
        release.set()
        await wait_until(lambda: all(not pane.loading for pane in screen.query(TabPane)))
        for section in FOR_YOU_SECTIONS:
            table = screen.query_one(f'#{section}-table', ExtendedTable)
            assert table.row_count == 1
            assert table.get_row_at(0)[0].plain == f'FRESH-{section}'
        notify.assert_not_called()
