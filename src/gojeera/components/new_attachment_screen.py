from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.jumper_file_picker import ExtendedFileOpen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class FilePathInput(Input):
    def __init__(self):
        super().__init__(
            placeholder='Click "Browse..." to select a file',
            valid_empty=False,
        )
        self.tooltip = 'Selected file path will appear here'
        self.compact = True
        self.disabled = True


class AddAttachmentScreen(ModalScreen[str]):
    """A modal screen to add an attachment to a work item."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, work_item_key: str | None = None):
        super().__init__()
        self._work_item_key = work_item_key
        self._modal_title: str = f'Add Attachment - {work_item_key}'
        self._selected_file: Path | None = None

    @property
    def file_path_input(self) -> FilePathInput:
        return self.query_one(FilePathInput)

    @property
    def browse_button(self) -> Button:
        return self.query_one('#browse-file-button', expect_type=Button)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-attachment-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='add-attachment-form'):
                with Vertical(id='file-path-container'):
                    yield Label('File Path').add_class('field_label')
                    with Horizontal(id='file-path-input-row'):
                        yield FilePathInput()
                        yield Button(
                            'Browse...', id='browse-file-button', variant='primary', compact=True
                        )
                    yield Label(
                        '• Click "Browse..." to open the file picker\n'
                        '• Navigate and select the file to attach',
                        id='file-path-hint',
                    )
                    yield Label(
                        '⚠ Large files may cause temporary UI unresponsiveness!',
                        id='file-path-warning',
                    )

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Attach',
                    variant='success',
                    id='add-attachment-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel', variant='error', id='add-attachment-button-quit', compact=True
                )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.browse_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#add-attachment-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Button.Pressed, '#browse-file-button')
    async def open_file_picker(self) -> None:
        await self.app.push_screen(
            ExtendedFileOpen(
                location=Path.home(),
                title='Select File to Attach',
                open_button='Select',
                must_exist=True,
                suggest_completions=True,
            ),
            callback=self._handle_file_selection,
        )

    def _handle_file_selection(self, file_path: Path | None) -> None:
        """Handle the file selection from the file picker.

        Args:
            file_path: The selected file path or None if cancelled.
        """
        if file_path:
            self._selected_file = file_path
            self.file_path_input.value = str(file_path)
            self.save_button.disabled = False
        else:
            self._selected_file = None
            self.save_button.disabled = True

    def on_click(self) -> None:
        self.dismiss('')

    @on(Button.Pressed, '#add-attachment-button-save')
    def handle_save(self) -> None:
        if self._selected_file:
            self.dismiss(str(self._selected_file))
        else:
            self.dismiss('')

    @on(Button.Pressed, '#add-attachment-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss('')
