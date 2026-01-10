from pathlib import Path
from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Container, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_attachment_screen import AddAttachmentScreen
from gojeera.components.save_attachment_screen import SaveAttachmentScreen
from gojeera.components.view_attachment_screen import ViewAttachmentScreen
from gojeera.config import CONFIGURATION
from gojeera.models import Attachment, JiraWorkItemSearchResponse
from gojeera.utils.mime import can_view_attachment
from gojeera.utils.urls import build_external_url_for_attachment
from gojeera.widgets.extended_data_table import ExtendedDataTable


class AttachmentsContainer(Container):
    """Container for holding attachment table elements."""

    def __init__(self):
        super().__init__(id='attachments-container')


class WorkItemAttachmentsWidget(VerticalScroll, can_focus=False):
    """A container for displaying the files attached to a work item."""

    attachments: Reactive[list[Attachment] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)

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
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def attachments_container_widget(self) -> AttachmentsContainer:
        return self.query_one(AttachmentsContainer)

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            with AttachmentsContainer():
                pass

    def show_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = True
            self.content_container.display = False

    def hide_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = False
            self.content_container.display = True

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
            self.notify(
                'Uploading attachment...',
            )
            screen = cast('MainScreen', self.screen)  # noqa: F821  # type: ignore[arg-type]
            response: APIControllerResponse = screen.api.add_attachment(
                self.work_item_key, file_name
            )
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

            self.loading_container.display = False
            self.content_container.display = True

            if not attachments:
                self.displayed_count = 0
                return

            if self.work_item_key:
                table = AttachmentsDataTable(self.work_item_key)
                table.add_columns(*['File Name', 'Size (KB)', 'Added', 'Author', 'Type'])

                item: Attachment
                for item in attachments:
                    table.add_row(
                        *[
                            item.filename,
                            item.get_size() or '-',
                            item.created_date,
                            item.display_author,
                            item.get_mime_type(),
                        ],
                        key=item.id,
                    )
                container.mount(table)
                self.displayed_count = len(attachments)


class AttachmentsDataTable(ExtendedDataTable):
    """A data table to list the files attached to a work item."""

    BINDINGS = [
        Binding(
            key='d',
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
                selected_attachment_file_type = row[-1]
                if selected_attachment_file_type:
                    if not can_view_attachment(selected_attachment_file_type.lower()):
                        self.notify(
                            f'The type of file {selected_attachment_file_type} is not supported'
                        )
                    elif self._selected_attachment_file_name:
                        self.app.push_screen(
                            ViewAttachmentScreen(
                                self._selected_attachment_id,
                                selected_attachment_file_type,
                                self._selected_attachment_file_name,
                            )
                        )

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
                if CONFIGURATION.get().fetch_attachments_on_delete:
                    if not self._work_item_key:
                        self._update_attachments_after_delete()
                    else:
                        fetch_response = await screen.api.get_work_item(
                            self._work_item_key, fields=['attachment']
                        )
                        if not fetch_response.success or not fetch_response.result:
                            self._update_attachments_after_delete()
                        else:
                            if (
                                self.parent is not None
                                and self.parent.parent is not None
                                and self.parent.parent.parent is not None
                            ):
                                attachments_widget = self.parent.parent.parent
                                if isinstance(attachments_widget, WorkItemAttachmentsWidget):
                                    work_item_data = cast(
                                        JiraWorkItemSearchResponse, fetch_response.result
                                    )
                                    new_attachments = work_item_data.work_items[0].attachments
                                    attachments_widget.attachments = new_attachments
                else:
                    self._update_attachments_after_delete()
