from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_attachment_screen import AddAttachmentScreen
from gojeera.components.save_attachment_screen import SaveAttachmentScreen
from gojeera.models import Attachment
from gojeera.utils.urls import build_external_url_for_attachment
from gojeera.widgets.extended_data_table import ExtendedDataTable

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class AttachmentsContainer(Container):
    """Container for holding attachment table elements."""

    def __init__(self):
        super().__init__(id='attachments-container')


class WorkItemAttachmentsWidget(VerticalScroll, can_focus=False):
    """A container for displaying the files attached to a work item."""

    DEFAULT_CSS = """
    WorkItemAttachmentsWidget {
        width: 100%;
        height: 1fr;
        hatch: right $success 20%;
        scrollbar-size-vertical: 1;
    }

    WorkItemAttachmentsWidget > .tab-content-container {
        width: 100%;
        height: 1fr;
    }
    """

    attachments: Reactive[list[Attachment] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(id='attachments')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#attachments'

    @property
    def work_item_key(self) -> str | None:
        return self._work_item_key

    @work_item_key.setter
    def work_item_key(self, value: str | None) -> None:
        self._work_item_key = value

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def attachments_container_widget(self) -> AttachmentsContainer:
        return self.query_one(AttachmentsContainer)

    @property
    def attachments_table(self) -> 'AttachmentsDataTable | None':
        return self.query_one(AttachmentsDataTable) if self.query(AttachmentsDataTable) else None

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield AttachmentsContainer()

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading

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
            screen = cast('MainScreen', self.screen)  # noqa: F821  # type: ignore[arg-type]
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
        container = self.attachments_container_widget

        with self.app.batch_update():
            container.remove_children()
            self.is_loading = False

            if not attachments:
                self.displayed_count = 0
                return

            if self.work_item_key:
                table = AttachmentsDataTable(self.work_item_key)
                table.add_columns(*['File Name', 'Type', 'Size (KB)', 'Author', 'Added'])

                item: Attachment
                for item in attachments:
                    table.add_row(
                        *[
                            item.filename,
                            item.get_mime_type(),
                            item.get_size() or '-',
                            item.display_author,
                            item.created_date,
                        ],
                        key=item.id,
                    )
                container.mount(table)
                self.displayed_count = len(attachments)

    def focus_attachment_by_filename(self, filename: str) -> bool:
        table = self.attachments_table
        if table is None:
            return False

        return table.focus_attachment_by_filename(filename)


class AttachmentsDataTable(ExtendedDataTable):
    """A data table to list the files attached to a work item."""

    BINDINGS = [
        Binding(
            key='ctrl+n',
            action='new_attachment',
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

    def __init__(self, work_item_key: str):
        super().__init__(cursor_type='row')
        self._selected_attachment_id: str | None = None
        self._selected_attachment_file_name: str | None = None
        self._work_item_key: str | None = work_item_key

    def _get_attachments_widget(self) -> 'WorkItemAttachmentsWidget | None':
        current = self.parent
        while current is not None:
            if isinstance(current, WorkItemAttachmentsWidget):
                return current
            current = current.parent
        return None

    def focus_attachment_by_filename(self, filename: str) -> bool:
        attachments_widget = self._get_attachments_widget()
        attachments = attachments_widget.attachments if attachments_widget is not None else None
        if not attachments:
            return False

        attachment = next((item for item in attachments if item.filename == filename), None)
        if attachment is None:
            return False

        row_index = self.get_row_index(attachment.id)
        self.move_cursor(row=row_index)
        self.focus()
        self._selected_attachment_id = attachment.id
        self._selected_attachment_file_name = attachment.filename
        return True

    async def action_new_attachment(self) -> None:
        widget = self._get_attachments_widget()
        if widget is not None:
            await widget.action_add_attachment()

    @on(ExtendedDataTable.RowHighlighted)
    def highlighted(self, event: ExtendedDataTable.RowHighlighted) -> None:
        if event.row_key.value is not None:
            self._selected_attachment_id = str(event.row_key.value)
            if (row := event.data_table.get_row(event.row_key.value)) and len(row) > 0:
                self._selected_attachment_file_name = row[0]

    @on(ExtendedDataTable.RowSelected)
    def selected(self, event: ExtendedDataTable.RowSelected) -> None:
        if event.row_key.value:
            self._selected_attachment_id = str(event.row_key.value)
            if (row := event.data_table.get_row(event.row_key.value)) and len(row) > 0:
                self._selected_attachment_file_name = row[0]
                if self._selected_attachment_id and self._selected_attachment_file_name:
                    work_item_key = self._work_item_key
                    if work_item_key:
                        self.notify('Opening attachment in the browser...', title=work_item_key)
                    app = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
                    if url := build_external_url_for_attachment(
                        self._selected_attachment_id, self._selected_attachment_file_name, app
                    ):
                        app.open_url(url)

    async def action_open_attachment(self) -> None:
        if self._selected_attachment_id and self._selected_attachment_file_name:
            work_item_key = self._work_item_key
            if work_item_key:
                self.notify('Opening attachment in the browser...', title=work_item_key)
            app = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
            if url := build_external_url_for_attachment(
                self._selected_attachment_id, self._selected_attachment_file_name, app
            ):
                app.open_url(url)

    async def action_download_attachment(self) -> None:
        if not self._selected_attachment_id or not self._selected_attachment_file_name:
            self.notify(
                'Select a row, e.g. by clicking on it, before attempting to download the file.',
                severity='error',
            )
            return
        app = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
        response: APIControllerResponse = await app.api.get_attachment_content(
            self._selected_attachment_id
        )

        if not response.success or not response.result:
            self.notify(
                f'Failed to download attachment: {response.error}',
                severity='error',
            )
            return

        attachment_content = response.result
        await self.app.push_screen(
            SaveAttachmentScreen(self._selected_attachment_file_name),
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
        if not self._selected_attachment_id:
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
        if self.parent is None or self.parent.parent is None or self.parent.parent.parent is None:
            return
        attachments_widget = self.parent.parent.parent
        if not isinstance(attachments_widget, WorkItemAttachmentsWidget):
            return

        updated_attachments: list[Attachment] = []
        for attachment in attachments_widget.attachments or []:
            if attachment.id == self._selected_attachment_id:
                continue
            updated_attachments.append(attachment)
        attachments_widget.attachments = updated_attachments

    async def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            if not self._selected_attachment_id:
                self.notify('No attachment selected', severity='error')
                return
            screen = cast('MainScreen', self.screen)  # noqa: F821  # type: ignore[arg-type]
            response: APIControllerResponse = await screen.api.delete_attachment(
                self._selected_attachment_id
            )
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
