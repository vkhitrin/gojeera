from io import BytesIO
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PIL import UnidentifiedImageError
from textual import on
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Footer, LoadingIndicator, Static, TextArea
from textual_image.widget import Image

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.save_attachment_screen import SaveAttachmentScreen
from gojeera.config import CONFIGURATION
from gojeera.utils.mime import (
    SupportedAttachmentVisualizationMimeTypes,
    is_image,
)
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class ViewAttachmentScreen(ModalScreen):
    """A modal screen to display files attached to a work item."""

    BINDINGS = [
        ('escape', 'dismiss_screen', 'Close'),
        ('ctrl+s', 'download_attachment', 'Download'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, attachment_id: str, attachment_file_type: str, attachment_file_name: str):
        super().__init__()
        self._attachment_id = attachment_id
        self._attachment_file_type = attachment_file_type
        self._attachment_file_name = attachment_file_name
        self._modal_title = f'View Attachment - {attachment_file_name}'
        self._attachment_content: bytes | None = None

    @property
    def center_widget(self) -> Center:
        return self.query_one(Center)

    @property
    def content_scroll(self) -> VerticalScroll:
        return self.query_one('#attachment-content', VerticalScroll)

    @property
    def download_button(self) -> Button:
        return self.query_one('#attachment-button-download', Button)

    @property
    def close_button(self) -> Button:
        return self.query_one('#attachment-button-close', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='attachment-content'):
                with Center():
                    yield LoadingIndicator()
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Download', variant='success', id='attachment-button-download', compact=True
                )
                yield Button('Close', variant='error', id='attachment-button-close', compact=True)
        yield Footer(show_command_palette=False)

    async def _download_attachment(self, attachment_id: str) -> None:
        app = cast('JiraApp', self.screen.app)  # noqa: F821
        response: APIControllerResponse = await app.api.get_attachment_content(attachment_id)
        container = self.center_widget

        with self.app.batch_update():
            await container.remove_children(LoadingIndicator)
            if response.success and response.result:
                self._attachment_content = response.result
                try:
                    widget = FileAttachmentWidget.build_widget(
                        self._attachment_file_type, response.result
                    )
                except Exception:
                    await container.mount(Static('Unable to display the file'))
                else:
                    if widget:
                        await container.mount(widget)
                    else:
                        await container.mount(Static('Unsupported file type'))
            else:
                await container.mount(Static('Unable to download the attached file'))
                self.notify(
                    f'Unable to download the attached file: {response.error}',
                    severity='error',
                    title='Download Attachment',
                )

    async def on_mount(self) -> None:
        self.run_worker(self._download_attachment(self._attachment_id))

        if CONFIGURATION.get().jumper.enabled:
            self.download_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.close_button.jump_mode = 'click'  # type: ignore[attr-defined]

    def on_click(self) -> None:
        self.dismiss()

    def action_dismiss_screen(self) -> None:
        self.dismiss()

    async def action_download_attachment(self) -> None:
        if not self._attachment_content:
            self.notify(
                'Attachment content not yet loaded. Please wait.',
                severity='warning',
                title='Download Attachment',
            )
            return

        await self.app.push_screen(
            SaveAttachmentScreen(self._attachment_file_name),
            callback=self._handle_save_location,
        )

    def _handle_save_location(self, save_path: str | None) -> None:
        if save_path and self._attachment_content:
            try:
                file_path = Path(save_path)

                file_path.write_bytes(self._attachment_content)
                self.notify(
                    f'Attachment saved successfully to {file_path}',
                    title='Download Attachment',
                )
            except Exception as e:
                self.notify(
                    f'Failed to save attachment: {e}',
                    severity='error',
                    title='Download Attachment',
                )

    @on(Button.Pressed, '#attachment-button-download')
    async def handle_download_button(self) -> None:
        await self.action_download_attachment()

    @on(Button.Pressed, '#attachment-button-close')
    def handle_close_button(self) -> None:
        self.dismiss()

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()


class FileAttachmentWidget:
    """A factory to build Widgets to view different types of files attached to a work item."""

    @staticmethod
    def build_widget(file_type: str, content: bytes) -> Widget | None:
        try:
            mime = SupportedAttachmentVisualizationMimeTypes(file_type)
        except ValueError:
            return None
        if mime == SupportedAttachmentVisualizationMimeTypes.APPLICATION_JSON:
            try:
                return TextArea.code_editor(
                    json.dumps(json.loads(content), indent=3),
                    language='json',
                    read_only=True,
                    show_line_numbers=False,
                )
            except (json.JSONDecodeError, ValueError):
                return None
        if mime == SupportedAttachmentVisualizationMimeTypes.APPLICATION_XML:
            return TextArea.code_editor(
                str(content.decode()), language='xml', read_only=True, show_line_numbers=False
            )
        if (
            mime == SupportedAttachmentVisualizationMimeTypes.TEXT_CSV
            or mime == SupportedAttachmentVisualizationMimeTypes.TEXT_PLAIN
        ):
            return TextArea.code_editor(
                str(content.decode()), read_only=True, show_line_numbers=False
            )
        if mime == SupportedAttachmentVisualizationMimeTypes.TEXT_MARKDOWN:
            return GojeeraMarkdown(str(content.decode()))

        if is_image(file_type) and _image_support_is_enabled():
            try:
                return Image(BytesIO(content))
            except UnidentifiedImageError:
                return None
        return None


def _image_support_is_enabled() -> bool:
    return CONFIGURATION.get().enable_images_support
