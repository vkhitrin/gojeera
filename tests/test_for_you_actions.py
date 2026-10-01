from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest
from textual.pilot import Pilot
from textual.widgets import TabPane

from gojeera.app import JiraApp
from gojeera.components.screens.for_you_screen import ForYouScreen
from gojeera.components.screens.help_screen import HelpScreen
from gojeera.widgets.layout.extended_table import ExtendedTable

from .for_you_test_helpers import prepare_for_you_tab
from .test_helpers import wait_until


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['workspace', 'modal', 'palette'])
async def test_f10_opens_for_you_globally_without_duplicate_modals(for_you_app, origin):
    app = for_you_app
    async with app.run_test(size=(120, 40)) as pilot:
        if origin == 'modal':
            await app.push_screen(HelpScreen())
        elif origin == 'palette':
            app.action_command_palette()
        await pilot.pause()
        previous_screen = app.screen
        stack_size = len(app.screen_stack)

        await pilot.press('f10')
        await wait_until(lambda: isinstance(app.screen, ForYouScreen))
        for_you = app.screen
        assert len(app.screen_stack) == stack_size + 1
        await pilot.press('f10')
        assert app.screen is for_you
        assert len(app.screen_stack) == stack_size + 1

        await pilot.press('escape')
        assert app.screen is previous_screen
        await pilot.press('f10')
        await wait_until(lambda: isinstance(app.screen, ForYouScreen))
        assert app.screen is not for_you
        await pilot.press('escape')
        assert app.screen is previous_screen


@dataclass
class ForYouActions:
    app: JiraApp
    pilot: Pilot
    screen: ForYouScreen
    open_url: Mock
    copy: Mock
    load: AsyncMock
    background_browse: Mock


@pytest.fixture
async def for_you_actions(for_you_app, mock_jira_api_for_you, monkeypatch, request):
    app = for_you_app
    open_url = Mock()
    copy = Mock()
    load = AsyncMock()
    background_browse = Mock()
    monkeypatch.setattr(app, 'open_url', open_url)
    monkeypatch.setattr(app, 'copy_to_clipboard', copy)
    monkeypatch.setattr(app, 'load_work_item', load)
    monkeypatch.setattr(app, 'action_open_loaded_work_item_in_browser', background_browse)

    async with app.run_test(size=(120, 40)) as pilot:
        await app._ensure_work_item_details_mounted()
        screen = await prepare_for_you_tab(
            pilot, getattr(request, 'param', 'due'), mock_jira_api_for_you
        )
        app.current_loaded_work_item_key = 'ENG-999'
        app.focused_work_item_link_key = 'ENG-998'
        yield ForYouActions(app, pilot, screen, open_url, copy, load, background_browse)


@pytest.mark.asyncio
@pytest.mark.parametrize('for_you_actions', ['due', 'updated', 'mentions'], indirect=True)
async def test_for_you_shortcuts_use_highlighted_row_in_active_tab(for_you_actions):
    actions = for_you_actions
    await wait_until(lambda: actions.app.atlassian_context.server_info is not None)
    # Browser URLs must use the Jira site's URL, not an OAuth API gateway URL.
    server_info = actions.app.atlassian_context.server_info
    assert server_info is not None
    server_info.base_url = 'https://jira.example.net'
    table = actions.screen.tabs.active_pane.query_one(ExtendedTable)
    await actions.pilot.press('j')
    assert table.cursor_row == 1
    key = table.get_row_at(1)[0].plain
    url = f'https://jira.example.net/browse/{key}'

    await actions.pilot.press('ctrl+o')
    actions.open_url.assert_called_once_with(url)
    actions.background_browse.assert_not_called()
    await actions.pilot.press('ctrl+y')
    actions.copy.assert_called_once_with(key)
    await actions.pilot.press('ctrl+u')
    assert actions.copy.call_count == 2
    assert actions.copy.call_args.args == (url,)
    assert actions.app.screen is actions.screen
    actions.load.assert_not_awaited()

    await actions.pilot.press('enter')
    await wait_until(lambda: actions.load.await_count == 1)
    actions.load.assert_awaited_once_with(key)
    assert actions.app.screen is not actions.screen


@pytest.mark.asyncio
@pytest.mark.parametrize('for_you_actions', ['due', 'updated', 'mentions'], indirect=True)
@pytest.mark.parametrize('mock_jira_api_for_you', ['empty', 'loading'], indirect=True)
async def test_for_you_shortcuts_ignore_empty_and_loading_tabs(for_you_actions):
    actions = for_you_actions
    await actions.pilot.press('ctrl+o', 'ctrl+y', 'ctrl+u', 'enter')
    await actions.pilot.pause()
    assert actions.app.screen is actions.screen
    actions.open_url.assert_not_called()
    actions.copy.assert_not_called()
    actions.load.assert_not_awaited()
    actions.background_browse.assert_not_called()
    await actions.pilot.press('escape')


@pytest.mark.asyncio
async def test_for_you_shortcuts_follow_tab_changes_and_ignore_stale_rows_while_loading(
    for_you_actions,
):
    actions = for_you_actions
    await actions.pilot.press('j', 'ctrl+y')
    actions.copy.assert_called_once_with('ENG-102')
    await actions.pilot.press(']', 'ctrl+y')
    assert actions.copy.call_args.args == ('ENG-104',)
    await actions.pilot.press('[', 'ctrl+y')
    assert actions.copy.call_args.args == ('ENG-102',)
    actions.copy.reset_mock()
    pane = actions.screen.query_one('#for-you-due', TabPane)
    assert pane.query_one(ExtendedTable).row_count > 0
    pane.loading = True
    await actions.pilot.press('ctrl+o', 'ctrl+y', 'ctrl+u', 'enter')
    await actions.pilot.pause()
    actions.copy.assert_not_called()
    actions.open_url.assert_not_called()
    actions.load.assert_not_awaited()
    assert actions.app.screen is actions.screen
    await actions.pilot.press('escape')
