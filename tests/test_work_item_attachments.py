import asyncio
from pathlib import Path
import tempfile

from textual.widgets import Button
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_attachment_screen import AddAttachmentScreen
from gojeera.components.work_item_attachments import (
    AttachmentsDataTable,
    WorkItemAttachmentsWidget,
)


async def select_work_item_with_attachments_and_highlight_row(pilot):
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


async def upload_attachment_and_verify(pilot):

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_file:
        tmp_file.write('Test attachment content')
        test_file_path = Path(tmp_file.name)

    try:
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

        attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
        initial_count = attachments_widget.displayed_count

        await pilot.press('ctrl+n')
        await asyncio.sleep(0.5)

        screen = pilot.app.screen
        assert isinstance(screen, AddAttachmentScreen)

        screen._handle_file_selection(test_file_path)
        await asyncio.sleep(0.3)

        assert not screen.save_button.disabled, 'Attach button should be enabled'
        screen.save_button.press()

        await asyncio.sleep(1.5)

        assert not isinstance(pilot.app.screen, AddAttachmentScreen)

        attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
        new_count = attachments_widget.displayed_count

        assert new_count == initial_count + 1, (
            f'Expected {initial_count + 1} attachments, got {new_count}'
        )

        assert attachments_widget.attachments is not None

        new_attachment = attachments_widget.attachments[-1]
        assert new_attachment.filename == 'new_test_file.txt', (
            f'Expected filename "new_test_file.txt", got "{new_attachment.filename}"'
        )
    finally:
        if test_file_path.exists():
            test_file_path.unlink()


async def delete_attachment_and_verify(pilot):

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

    attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
    initial_count = attachments_widget.displayed_count
    assert initial_count > 0, 'Should have at least one attachment to delete'

    data_table = attachments_widget.query_one(AttachmentsDataTable)
    data_table.focus()
    await asyncio.sleep(0.2)

    await pilot.press('d')
    await asyncio.sleep(0.5)

    screen = pilot.app.screen
    assert isinstance(screen, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen)}'
    )

    screen.query_one('#confirmation-button-accept', Button).press()
    await asyncio.sleep(1.0)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(1.0)

    assert not isinstance(pilot.app.screen, ConfirmationScreen)

    attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
    new_count = attachments_widget.displayed_count
    assert new_count == initial_count - 1, (
        f'Expected {initial_count - 1} attachments, got {new_count}'
    )


class TestWorkItemAttachments:
    def test_work_item_attachments_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=select_work_item_with_attachments_and_highlight_row,
        )

    def test_delete_attachment_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_attachment_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_attachment_and_verify)

    def test_upload_attachment_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_attachment_upload,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=upload_attachment_and_verify)
