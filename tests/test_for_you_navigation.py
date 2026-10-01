from unittest.mock import AsyncMock, Mock

import pytest

from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.screens.for_you_screen import ForYouScreen
from gojeera.components.screens.help_screen import HelpScreen
from gojeera.widgets.layout.extended_table import ExtendedTable

from .test_helpers import wait_until


@pytest.fixture
async def for_you_navigation(for_you_app, monkeypatch):
    async with for_you_app.run_test(size=(120, 40)) as pilot:

        async def load_on_workspace(_key):
            assert len(for_you_app.screen_stack) == 1

        load = AsyncMock(side_effect=load_on_workspace)
        notify = Mock()
        monkeypatch.setattr(for_you_app, 'load_work_item', load)
        monkeypatch.setattr(for_you_app, 'notify', notify)
        yield for_you_app, pilot, load, notify


async def select_first_for_you_item(pilot):
    await pilot.press('f10')
    await wait_until(lambda: isinstance(pilot.app.screen, ForYouScreen))
    table = pilot.app.screen.query_one('#due-table', ExtendedTable)
    await wait_until(lambda: table.row_count > 0)
    table.focus()
    await pilot.press('enter')
    await pilot.pause()


@pytest.mark.asyncio
@pytest.mark.parametrize('origin', ['workspace', 'modal', 'palette', 'nested', 'clean-editor'])
async def test_for_you_selection_returns_to_workspace(for_you_navigation, origin):
    app, pilot, load, _notify = for_you_navigation
    workspace = app.screen
    cancelled = Mock()
    if origin in {'modal', 'nested'}:
        await app._push_screen_exclusive(HelpScreen(), cancelled)
    elif origin == 'clean-editor':
        await app._push_screen_exclusive(CommentScreen(work_item_key='ENG-999'), cancelled)
    if origin in {'palette', 'nested'}:
        app.action_command_palette()
    await pilot.pause()

    await select_first_for_you_item(pilot)
    await wait_until(lambda: load.await_count == 1)
    load.assert_awaited_once_with('ENG-101')
    assert app.screen is workspace
    assert not app._pending_screen_types
    if origin in {'modal', 'nested', 'clean-editor'}:
        cancelled.assert_called_once_with(None)
    await pilot.press('f10')
    assert isinstance(app.screen, ForYouScreen)
    await pilot.press('escape')
    assert app.screen is workspace


@pytest.mark.asyncio
@pytest.mark.parametrize('covered', [False, True])
async def test_for_you_selection_preserves_unsaved_editors(for_you_navigation, covered):
    app, pilot, load, notify = for_you_navigation
    cancelled = Mock()
    editor = CommentScreen(work_item_key='ENG-999')
    await app._push_screen_exclusive(editor, cancelled)
    await pilot.pause()
    editor.reset_dirty_state()
    editor.comment_field.text = 'Keep this unsaved comment'
    await wait_until(editor.is_dirty)
    if covered:
        await app._push_screen_exclusive(HelpScreen())
    previous_stack = app.screen_stack

    await select_first_for_you_item(pilot)
    load.assert_not_awaited()
    cancelled.assert_not_called()
    assert app.screen_stack == previous_stack
    assert editor.comment_field.text == 'Keep this unsaved comment'
    assert editor.is_dirty()
    assert CommentScreen in app._pending_screen_types
    notify.assert_called_once()
    assert notify.call_args.kwargs['severity'] == 'warning'
    assert 'unsaved changes' in notify.call_args.args[0]

    # Once the editor is clean, navigation is no longer blocked.
    editor.reset_dirty_state()
    await select_first_for_you_item(pilot)
    await wait_until(lambda: load.await_count == 1)
    assert len(app.screen_stack) == 1
    cancelled.assert_called_once_with(None)
