import asyncio

from textual.widgets import Button, Input
from textual.widgets._tabbed_content import ContentTabs

from gojeera.components.screens.edit_work_item_info_screen import EditWorkItemInfoScreen
from gojeera.utils.system import clipboard_attachments as clipboard_attachments_module

from .test_helpers import (
    assert_snapshot_matches,
    load_work_item_from_search,
    stage_clipboard_upload,
    with_snapshot_assertion,
)


async def open_work_item_and_edit(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+e')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert save_button.disabled, 'Save button should be disabled in initial state'


async def open_edit_screen_and_modify_fields(pilot):
    await open_work_item_and_edit(pilot)

    screen = pilot.app.screen
    summary_input = screen.query_one('#edit-work-item-summary', Input)
    summary_input.focus()
    await asyncio.sleep(0.2)

    summary_input.value = summary_input.value + ' - Modified'
    await asyncio.sleep(0.3)

    await pilot.press('tab')
    await asyncio.sleep(0.3)

    await pilot.press(*'Updated description with new content')
    await asyncio.sleep(0.3)

    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert not save_button.disabled, 'Save button should be enabled after making changes'


async def open_edit_screen_and_clear_summary(pilot):
    await open_work_item_and_edit(pilot)

    screen = pilot.app.screen
    summary_input = screen.query_one('#edit-work-item-summary', Input)
    summary_input.focus()
    await asyncio.sleep(0.2)

    summary_input.value = ''
    await asyncio.sleep(0.3)

    save_button = screen.query_one('#edit-work-item-button-save', Button)
    assert save_button.disabled, 'Save button should be disabled when summary is empty'


async def paste_clipboard_attachment_into_edit_work_item(pilot):
    await open_work_item_and_edit(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, EditWorkItemInfoScreen)

    await screen.action_paste_clipboard_attachment()
    await asyncio.sleep(0.3)

    assert '<!-- gojeera:staged-clipboard-attachment -->' in screen.description_field.text


class TestEditWorkItemInfoScreen:
    @with_snapshot_assertion(open_work_item_and_edit)
    def test_edit_work_item_info_screen_initial_state(self): ...

    @with_snapshot_assertion(open_edit_screen_and_modify_fields)
    def test_edit_work_item_info_screen_fields_modified(self): ...

    @with_snapshot_assertion(open_edit_screen_and_clear_summary)
    def test_edit_work_item_info_screen_empty_summary(self): ...

    def test_edit_work_item_info_screen_with_clipboard_attachment(
        self,
        snap_compare,
        monkeypatch,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
        staged_upload_file,
    ):
        stage_clipboard_upload(monkeypatch, clipboard_attachments_module, staged_upload_file)
        assert_snapshot_matches(
            snap_compare,
            mock_configuration,
            mock_user_info,
            paste_clipboard_attachment_into_edit_work_item,
        )
