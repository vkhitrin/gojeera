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
    def __init__(self, initial_value: str = ''):
        super().__init__(
            value=initial_value,
            placeholder='Click "Browse..." to select save location',
            valid_empty=False,
        )
        self.tooltip = 'Selected file path will appear here'
        self.compact = True
        self.disabled = True


class SaveAttachmentScreen(ModalScreen[str]):
    """A modal screen to save an attachment to a file."""

    BINDINGS = [
        ('escape', 'dismiss_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, attachment_file_name: str):
        super().__init__()
        self._attachment_file_name = attachment_file_name
        self._modal_title: str = f'Save Attachment - {attachment_file_name}'
        self._selected_file: Path | None = None

    @property
    def file_path_input(self) -> FilePathInput:
        return self.query_one(FilePathInput)

    @property
    def browse_button(self) -> Button:
        return self.query_one('#browse-save-location-button', expect_type=Button)

    @property
    def save_button(self) -> Button:
        return self.query_one('#save-attachment-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='save-attachment-form'):
                with Vertical(id='file-path-container'):
                    yield Label('Save Location').add_class('field_label')
                    with Horizontal(id='file-path-input-row'):
                        yield FilePathInput(
                            initial_value=str(Path.home() / self._attachment_file_name)
                        )
                        yield Button(
                            'Browse...',
                            id='browse-save-location-button',
                            variant='primary',
                            compact=True,
                        )
                    yield Label(
                        '• Click "Browse..." to select where to save the file\n'
                        '• You can edit the filename in the picker',
                        id='file-path-hint',
                    )

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='save-attachment-button-save',
                    disabled=False,
                    compact=True,
                )
                yield Button(
                    'Cancel', variant='error', id='save-attachment-button-quit', compact=True
                )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        default_path = Path.home() / self._attachment_file_name
        self._selected_file = default_path
        self.file_path_input.value = str(default_path)

        if CONFIGURATION.get().jumper.enabled:
            self.browse_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#save-attachment-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def action_dismiss_screen(self) -> None:
        self.dismiss('')

    @on(Button.Pressed, '#browse-save-location-button')
    async def open_file_picker(self) -> None:
        await self.app.push_screen(
            ExtendedFileOpen(
                location=Path.home(),
                title='Select Save Location',
                open_button='Save',
                must_exist=False,
                default_file=self._attachment_file_name,
                suggest_completions=True,
            ),
            callback=self._handle_file_selection,
        )

    def _handle_file_selection(self, file_path: Path | None) -> None:
        if file_path:
            self._selected_file = file_path
            self.file_path_input.value = str(file_path)
            self.save_button.disabled = False

    def on_click(self) -> None:
        self.dismiss('')

    @on(Button.Pressed, '#save-attachment-button-save')
    def handle_save(self) -> None:
        if self._selected_file:
            self.dismiss(str(self._selected_file))
        else:
            self.dismiss('')

    @on(Button.Pressed, '#save-attachment-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss('')
