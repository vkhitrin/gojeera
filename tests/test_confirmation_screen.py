import asyncio

from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_item_attachments import AttachmentsDataTable


async def open_confirmation_screen_via_delete_attachment(pilot):
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

    table = pilot.app.screen.query_one(AttachmentsDataTable)
    table.focus()
    await asyncio.sleep(0.3)

    await pilot.press('d')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen)}'
    )
    assert screen.message == 'Are you sure you want to delete the file?', (
        f'Expected delete file message, got: {screen.message}'
    )


class TestConfirmationScreen:
    def test_confirmation_screen_via_delete_attachment(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_confirmation_screen_via_delete_attachment,
        )
