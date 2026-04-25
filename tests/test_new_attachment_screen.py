import asyncio
from pathlib import Path

from gojeera.components.screens.new_attachment_screen import AddAttachmentScreen

from .test_helpers import assert_snapshot_matches, focus_work_item_tab


async def open_add_attachment_screen(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=1)

    await pilot.press('ctrl+n')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, AddAttachmentScreen), (
        f'Expected AddAttachmentScreen, got {type(screen)}'
    )
    assert screen.save_button.disabled, 'Attach button should be disabled initially'
    assert screen.file_path_input.value == '', 'File path should be empty initially'


async def open_add_attachment_screen_with_file_selected(pilot):
    """Navigate to work item and open Add Attachment screen with file selected."""
    await open_add_attachment_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddAttachmentScreen), (
        f'Expected AddAttachmentScreen, got {type(screen)}'
    )

    test_file_path = Path('/tmp/test_attachment.txt')
    screen._handle_file_selection(test_file_path)
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, 'Attach button should be enabled after file selection'
    assert screen.file_path_input.value == str(test_file_path), (
        f'File path should be {test_file_path}, got {screen.file_path_input.value}'
    )
    assert screen._selected_file == test_file_path, (
        f'Selected file should be {test_file_path}, got {screen._selected_file}'
    )


OPEN = open_add_attachment_screen
OPEN_SELECTED = open_add_attachment_screen_with_file_selected


class TestNewAttachmentScreen:
    def test_new_attachment_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, OPEN)

    def test_new_attachment_screen_file_selected(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, OPEN_SELECTED)
