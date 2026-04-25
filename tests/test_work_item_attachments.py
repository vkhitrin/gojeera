from pathlib import Path
import tempfile

from gojeera.app import JiraApp
from gojeera.components.screens.new_attachment_screen import AddAttachmentScreen
from gojeera.components.work_item.work_item_attachments import WorkItemAttachmentsWidget
from gojeera.widgets.layout.record_list import RecordList

from .test_helpers import (
    accept_confirmation,
    assert_snapshot_matches,
    focus_work_item_tab,
    wait_for_screen_to_settle,
    wait_for_worker_idle,
    wait_until,
)


async def select_work_item_with_attachments_and_highlight_row(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=1)

    record_list = pilot.app.screen.query_one(RecordList)
    record_list.focus()
    await pilot.pause()


async def upload_attachment_and_verify(pilot):

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as tmp_file:
        tmp_file.write('Test attachment content')
        test_file_path = Path(tmp_file.name)

    try:
        await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=1)

        attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
        initial_count = attachments_widget.displayed_count

        await pilot.press('ctrl+n')
        await wait_until(lambda: isinstance(pilot.app.screen, AddAttachmentScreen), timeout=3.0)

        screen = pilot.app.screen
        assert isinstance(screen, AddAttachmentScreen)

        screen._handle_file_selection(test_file_path)
        await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)

        assert not screen.save_button.disabled, 'Attach button should be enabled'
        screen.save_button.press()

        await wait_until(lambda: not isinstance(pilot.app.screen, AddAttachmentScreen), timeout=3.0)
        await wait_for_screen_to_settle(pilot)

        assert not isinstance(pilot.app.screen, AddAttachmentScreen)

        attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
        await wait_until(
            lambda: attachments_widget.displayed_count == initial_count + 1,
            timeout=3.0,
        )
        new_count = attachments_widget.displayed_count

        assert new_count == initial_count + 1, (
            f'Expected {initial_count + 1} attachments, got {new_count}'
        )

        assert attachments_widget.attachments is not None

        new_attachment = attachments_widget.attachments[-1]
        assert new_attachment.filename == 'new_test_file.txt', (
            f'Expected filename "new_test_file.txt", got "{new_attachment.filename}"'
        )

        await wait_for_worker_idle(pilot)
    finally:
        if test_file_path.exists():
            test_file_path.unlink()


async def delete_attachment_and_verify(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=1)

    attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
    initial_count = attachments_widget.displayed_count
    assert initial_count > 0, 'Should have at least one attachment to delete'

    record_list = attachments_widget.query_one(RecordList)
    record_list.focus()
    await pilot.pause()

    await pilot.press('ctrl+d')
    await accept_confirmation(pilot)

    attachments_widget = pilot.app.screen.query_one(WorkItemAttachmentsWidget)
    await wait_until(
        lambda: attachments_widget.displayed_count == initial_count - 1,
        timeout=3.0,
    )
    new_count = attachments_widget.displayed_count
    assert new_count == initial_count - 1, (
        f'Expected {initial_count - 1} attachments, got {new_count}'
    )


HIGHLIGHT = select_work_item_with_attachments_and_highlight_row
DELETE = delete_attachment_and_verify
UPLOAD = upload_attachment_and_verify


class TestWorkItemAttachments:
    def test_work_item_attachments_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, HIGHLIGHT)

    def test_delete_attachment(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_attachment_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=DELETE)

    def test_upload_attachment(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_attachment_upload,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=UPLOAD)
