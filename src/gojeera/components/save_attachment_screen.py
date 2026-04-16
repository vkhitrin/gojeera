from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.jumper_file_picker import ExtendedFileOpen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class FilePathInput(ExtendedInput):
    def __init__(self, initial_value: str = ''):
        super().__init__(
            value=initial_value,
            placeholder='Click "Browse..." to select save location',
            valid_empty=False,
        )
        self.tooltip = 'Selected file path will appear here'
        self.compact = True
        self.disabled = True


class SaveAttachmentScreen(ExtendedModalScreen[str]):
    """A modal screen to save an attachment to a file."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
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
            with VerticalScroll(id='save-attachment-form', classes='modal-form modal-form--tight'):
                with Vertical(id='file-path-container', classes='modal-form-section'):
                    save_location_label = Label('Save Location')
                    save_location_label.add_class('field_label')
                    yield save_location_label
                    with Horizontal(id='file-path-input-row', classes='modal-form-input-row'):
                        yield FilePathInput(
                            initial_value=str(Path.home() / self._attachment_file_name)
                        )
                        yield Button(
                            'Browse...',
                            id='browse-save-location-button',
                            variant='primary',
                            classes='modal-action-button modal-action-button--browse',
                            compact=True,
                        )
                    yield Label(
                        '• Click "Browse..." to select where to save the file\n'
                        '• You can edit the filename in the picker',
                        id='file-path-hint',
                        classes='modal-form-hint',
                    )

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Save',
                    variant='success',
                    id='save-attachment-button-save',
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=False,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='save-attachment-button-quit',
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        default_path = Path.home() / self._attachment_file_name
        self._selected_file = default_path
        self.file_path_input.value = str(default_path)

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.browse_button, 'click')
            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.query_one('#save-attachment-button-quit', Button), 'click')
        self.call_after_refresh(lambda: focus_first_available(self.browse_button))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def action_dismiss_screen(self) -> None:
        self.dismiss()

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

    @on(Button.Pressed, '#save-attachment-button-save')
    def handle_save(self) -> None:
        if self._selected_file:
            self.dismiss(str(self._selected_file))
        else:
            self.dismiss()

    @on(Button.Pressed, '#save-attachment-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
