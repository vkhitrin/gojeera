"""Deterministic HTTP fixtures and shared setup for For You visual/functional tests."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import cast

from httpx import Request, Response
import pytest
import respx
from textual.pilot import Pilot
from textual.widgets import TabPane

from gojeera.app import JiraApp
from gojeera.components.screens.for_you_screen import ForYouScreen
from gojeera.internal.jira.for_you import ForYouSection, ForYouService
from gojeera.internal.store.config import ForYouConfig
from gojeera.utils.jira.jql import quote_jql_string
from gojeera.widgets.layout.extended_table import ExtendedTable

from .test_helpers import wait_until

FOR_YOU_NOW = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
FOR_YOU_ACCOUNT_ID = '555000:11111111-1111-1111-1111-111111111111'
FOR_YOU_SECTIONS: tuple[ForYouSection, ...] = ('due', 'updated', 'mentions')
FOR_YOU_ROW_COUNTS = {'due': 3, 'updated': 3, 'mentions': 2}
FIXTURES_DIR = Path(__file__).parent / 'fixtures'


@dataclass
class ForYouFixtureState:
    mode: str
    searches: list[str] = field(default_factory=list)
    comment_keys: list[str] = field(default_factory=list)
    release_searches: asyncio.Event = field(default_factory=asyncio.Event)


def install_for_you_fixtures(monkeypatch: pytest.MonkeyPatch, mode: str) -> ForYouFixtureState:
    """Mock Jira HTTP responses, not service results, so parsing and filtering stay real."""
    assert mode in ('populated', 'empty', 'loading')
    state = ForYouFixtureState(mode)
    search_payloads = {
        section: json.loads((FIXTURES_DIR / f'jira_for_you_{section}.json').read_text())
        for section in FOR_YOU_SECTIONS
    }
    comments = json.loads((FIXTURES_DIR / 'jira_for_you_comments.json').read_text())
    empty = json.loads((FIXTURES_DIR / 'jira_search_empty.json').read_text())
    account_phrase = quote_jql_string(quote_jql_string(FOR_YOU_ACCOUNT_ID))
    query_sections: dict[str, ForYouSection] = {
        'assignee = currentUser() AND statusCategory != Done '
        'AND duedate <= endOfDay("+7d") ORDER BY duedate ASC, updated DESC': 'due',
        '(assignee = currentUser() OR watcher = currentUser()) '
        'AND updated >= -7d ORDER BY updated DESC': 'updated',
        f'updated >= -7d AND comment ~ {account_phrase} ORDER BY updated DESC': 'mentions',
    }

    async def search(request: Request) -> Response:
        payload = json.loads(request.content)
        jql = payload['jql']
        assert jql in query_sections, f'Unexpected For You search: {jql}'
        section = query_sections[jql]
        state.searches.append(section)
        if mode == 'loading':
            await state.release_searches.wait()
        return Response(200, json=empty if mode == 'empty' else search_payloads[section])

    def get_comments(request: Request) -> Response:
        key = request.url.path.split('/')[-2]
        assert key in comments
        assert request.url.params['orderBy'] == '-created'
        assert request.url.params['startAt'] == '0'
        state.comment_keys.append(key)
        return Response(200, json=comments[key])

    respx.post('https://example.atlassian.acme.net/rest/api/3/search/jql').mock(side_effect=search)
    for key in comments:
        respx.get(f'https://example.atlassian.acme.net/rest/api/3/issue/{key}/comment').mock(
            side_effect=get_comments
        )

    original_load = ForYouService.load

    async def load_at_fixed_time(self, section, account_id, *, now=None):
        return await original_load(self, section, account_id, now=now or FOR_YOU_NOW)

    monkeypatch.setattr(ForYouService, 'load', load_at_fixed_time)
    if mode == 'loading':
        # Freeze only the indicator's animation clock, not asyncio timers or Jira logic.
        monkeypatch.setattr('textual.widgets._loading_indicator.time', lambda: 123.0)
    return state


async def prepare_for_you_tab(
    pilot: Pilot, section: ForYouSection, state: ForYouFixtureState
) -> ForYouScreen:
    """Reach an explicit, stable tab state without producing or comparing a snapshot."""
    app = cast(JiraApp, pilot.app)
    await app.action_show_for_you()
    screen = cast(ForYouScreen, app.screen)
    await wait_until(lambda: len(state.searches) == 3)
    if state.mode == 'loading':
        assert all(pane.loading for pane in screen.query(TabPane))
    else:
        await wait_until(lambda: all(not pane.loading for pane in screen.query(TabPane)))
        for tab in FOR_YOU_SECTIONS:
            count = FOR_YOU_ROW_COUNTS[tab] if state.mode == 'populated' else 0
            assert screen.query_one(f'#{tab}-table', ExtendedTable).row_count == count
    await pilot.pause()
    screen.tabs.tabs_widget.focus()
    for _ in range(FOR_YOU_SECTIONS.index(section)):
        await pilot.press(']')
    await pilot.pause()
    assert screen.tabs.active == f'for-you-{section}'
    if state.mode != 'loading':
        screen.query_one(f'#{section}-table', ExtendedTable).focus()
    await pilot.pause()
    return screen


def configure_for_you_test_app(app: JiraApp, theme: str) -> None:
    app.config.for_you = ForYouConfig()
    app.theme = theme
