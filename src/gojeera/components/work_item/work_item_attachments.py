from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.reactive import Reactive, reactive

from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.new_attachment_screen import AddAttachmentScreen
from gojeera.components.screens.save_attachment_screen import SaveAttachmentScreen
from gojeera.components.tabs.record_list_tab import RecordListTabWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import Attachment
from gojeera.utils.jira.urls import build_external_url_for_attachment
from gojeera.widgets.layout.record_list import Record, RecordList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemAttachmentsWidget(RecordListTabWidget):
    """A container for displaying the files attached to a work item."""

    attachments: Reactive[list[Attachment] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    BINDINGS = [
        Binding(
            key='ctrl+n',
            action='add_attachment',
            description='New attachment',
            tooltip='Attach a file to the loaded work item',
            priority=True,
        ),
        Binding(
            key='ctrl+d',
            action='delete_attachment',
            description='Delete',
            tooltip='Deletes the attachment',
        ),
        Binding(
            key='ctrl+o',
            action='open_attachment',
            description='Browse',
            show=True,
            tooltip='Open file in the browser',
        ),
        Binding(
            key='ctrl+s',
            action='download_attachment',
            description='Download',
            show=True,
            tooltip='Download the attachment',
        ),
    ]

    def __init__(self):
        super().__init__(widget_id='attachments', record_list_id='attachments-list')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#attachments'

    @property
    def has_records(self) -> bool:
        return bool(self.attachments)

    def watch_is_loading(self, loading: bool) -> None:
        # Keep populated tab content stable during work-item switches; the loading
        # overlay causes a visible tint flash on the active tab.
        super().watch_is_loading(loading)

    async def action_add_attachment(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(
                AddAttachmentScreen(self.work_item_key), self.upload_attachment
            )
        else:
            self.notify(
                'You need to select a work item before attempting to attach a file.',
                severity='error',
            )

    def upload_attachment(self, content: str | None) -> None:
        """Uploads a file as an attachment to the work item.

        Args:
            content: the name of the file to attach.

        Returns:
            None
        """
        if content and (file_name := content.strip()):
            work_item_key = self.work_item_key
            if not work_item_key:
                self.notify(
                    'You need to select a work item before attempting to attach a file.',
                    severity='error',
                )
                return
            self.notify(
                'Uploading attachment...',
            )
            screen = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
            response: APIControllerResponse = screen.api.add_attachment(work_item_key, file_name)
            if not response.success:
                self.notify(
                    f'Failed to attach the file: {response.error}',
                    severity='error',
                )
            else:
                self.notify(
                    'File attached successfully',
                )

                current_attachments = self.attachments or []
                new_attachment = cast(Attachment, response.result)
                self.attachments = current_attachments + [new_attachment]

    def watch_attachments(self, attachments: list[Attachment] | None) -> None:
        with self.app.batch_update():
            self.is_loading = False

            if not attachments:
                self.record_list.clear_records()
                self.displayed_count = 0
                return

            if self.work_item_key:
                records: list[Record] = []
                for item in attachments:
                    title_parts = [part for part in (item.filename, item.created_date) if part]
                    records.append(
                        Record(
                            key=item.id,
                            title=' • '.join(title_parts),
                            payload=item,
                        )
                    )
                self.record_list.set_records(records)
                self.displayed_count = len(attachments)

    def focus_attachment_by_filename(self, filename: str) -> bool:
        attachment = next(
            (item for item in self.attachments or [] if item.filename == filename), None
        )
        if attachment is None:
            return False
        return self.record_list.focus_record_by_key(attachment.id)

    @property
    def selected_attachment(self) -> Attachment | None:
        return self.selected_payload_as(Attachment)

    async def action_open_attachment(self) -> None:
        attachment = self.selected_attachment
        if attachment and attachment.id and attachment.filename:
            if self.work_item_key:
                self.notify('Opening attachment in the browser...', title=self.work_item_key)
            app = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
            if url := build_external_url_for_attachment(attachment.id, attachment.filename, app):
                app.open_url(url)

    async def action_download_attachment(self) -> None:
        attachment = self.selected_attachment
        if not attachment or not attachment.id or not attachment.filename:
            self.notify(
                'Select a row, e.g. by clicking on it, before attempting to download the file.',
                severity='error',
            )
            return
        app = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
        response: APIControllerResponse = await app.api.get_attachment_content(attachment.id)

        if not response.success or not response.result:
            self.notify(
                f'Failed to download attachment: {response.error}',
                severity='error',
            )
            return

        attachment_content = response.result
        await self.app.push_screen(
            SaveAttachmentScreen(attachment.filename),
            callback=lambda save_path: self._handle_save_attachment(save_path, attachment_content),
        )

    def _handle_save_attachment(self, save_path: str | None, content: bytes) -> None:
        if save_path:
            work_item_key = self._work_item_key
            if not work_item_key:
                return
            try:
                file_path = Path(save_path)
                file_path.write_bytes(content)
                self.notify(
                    f'Attachment saved successfully to {file_path}',
                    title=work_item_key,
                )
            except Exception as e:
                self.notify(
                    f'Failed to save attachment: {e}',
                    severity='error',
                    title=work_item_key,
                )

    async def action_delete_attachment(self) -> None:
        if not self.selected_attachment:
            self.notify(
                'Select a row, e.g. by clicking on it, before attempting to delete the file.',
                severity='error',
            )
        else:
            await self.app.push_screen(
                ConfirmationScreen('Are you sure you want to delete the file?'),
                callback=self.handle_delete_choice,
            )

    def _update_attachments_after_delete(self) -> None:
        attachment = self.selected_attachment
        if attachment is None:
            return
        updated_attachments: list[Attachment] = []
        for current_attachment in self.attachments or []:
            if current_attachment.id == attachment.id:
                continue
            updated_attachments.append(current_attachment)
        self.attachments = updated_attachments

    async def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            attachment = self.selected_attachment
            if not attachment or not attachment.id:
                self.notify('No attachment selected', severity='error')
                return
            screen = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
            response: APIControllerResponse = await screen.api.delete_attachment(attachment.id)
            if not response.success:
                self.notify(
                    f'Failed to delete the file: {response.error}',
                    severity='error',
                )
            else:
                self.notify(
                    'File deleted successfully',
                )
                self._update_attachments_after_delete()

    @on(RecordList.RowInvoked)
    def on_row_invoked(self, event: RecordList.RowInvoked) -> None:
        if event.control is self.record_list:
            self.run_worker(self.action_open_attachment())
