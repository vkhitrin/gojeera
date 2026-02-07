import asyncio
from pathlib import Path

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.new_attachment_screen import AddAttachmentScreen


async def open_add_attachment_screen(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    await pilot.press('ctrl+n')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, AddAttachmentScreen), (
        f'Expected AddAttachmentScreen, got {type(screen)}'
    )
    assert screen.save_button.disabled is True, 'Attach button should be disabled initially'
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

    assert screen.save_button.disabled is False, (
        'Attach button should be enabled after file selection'
    )
    assert screen.file_path_input.value == str(test_file_path), (
        f'File path should be {test_file_path}, got {screen.file_path_input.value}'
    )
    assert screen._selected_file == test_file_path, (
        f'Selected file should be {test_file_path}, got {screen._selected_file}'
    )


class TestNewAttachmentScreen:
    def test_new_attachment_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=open_add_attachment_screen)

    def test_new_attachment_screen_file_selected(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_add_attachment_screen_with_file_selected,
        )
