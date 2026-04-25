from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static

from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.jumper_file_picker import ExtendedFileOpen


class FilePathInput(ExtendedInput):
    def __init__(self, *, placeholder: str, initial_value: str = ''):
        super().__init__(
            value=initial_value,
            placeholder=placeholder,
            valid_empty=False,
        )
        self.tooltip = 'Selected file path will appear here'
        self.compact = True
        self.disabled = True


class AttachmentPathModalScreen(ExtendedModalScreen[str]):
    """Shared modal for selecting a file path for attachment workflows."""

    def __init__(
        self,
        *,
        modal_title: str,
        form_id: str,
        field_label: str,
        input_placeholder: str,
        browse_button_id: str,
        browse_title: str,
        browse_open_button: str,
        save_button_id: str,
        save_button_label: str,
        cancel_button_id: str,
        hint_text: str,
        warning_text: str | None = None,
        initial_path: Path | None = None,
        default_file_name: str | None = None,
        must_exist: bool,
    ):
        super().__init__()
        self._modal_title = modal_title
        self._form_id = form_id
        self._field_label = field_label
        self._input_placeholder = input_placeholder
        self._browse_button_id = browse_button_id
        self._browse_title = browse_title
        self._browse_open_button = browse_open_button
        self._save_button_id = save_button_id
        self._save_button_label = save_button_label
        self._cancel_button_id = cancel_button_id
        self._hint_text = hint_text
        self._warning_text = warning_text
        self._initial_path = initial_path
        self._default_file_name = default_file_name
        self._must_exist = must_exist
        self._selected_file: Path | None = initial_path

    @property
    def file_path_input(self) -> FilePathInput:
        return self.query_one(FilePathInput)

    @property
    def browse_button(self) -> Button:
        return self.query_one(f'#{self._browse_button_id}', expect_type=Button)

    @property
    def save_button(self) -> Button:
        return self.query_one(f'#{self._save_button_id}', expect_type=Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id=self._form_id, classes='modal-form modal-form--tight'):
                with Vertical(id='file-path-container', classes='modal-form-section'):
                    file_path_label = Label(self._field_label)
                    file_path_label.add_class('field_label')
                    yield file_path_label
                    with Horizontal(id='file-path-input-row', classes='modal-form-input-row'):
                        yield FilePathInput(
                            placeholder=self._input_placeholder,
                            initial_value=str(self._initial_path) if self._initial_path else '',
                        )
                        yield Button(
                            'Browse...',
                            id=self._browse_button_id,
                            variant='primary',
                            classes='modal-action-button modal-action-button--browse',
                            compact=True,
                        )
                    yield Label(
                        self._hint_text,
                        id='file-path-hint',
                        classes='modal-form-hint',
                    )
                    if self._warning_text:
                        yield Label(
                            self._warning_text,
                            id='file-path-warning',
                            classes='modal-form-warning',
                        )

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button,
                    button_id=self._save_button_id,
                    label=self._save_button_label,
                    disabled=self._selected_file is None,
                )
                yield build_modal_cancel_button(Button, button_id=self._cancel_button_id)
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        if self._initial_path is not None:
            self.file_path_input.value = str(self._initial_path)

        self.activate_modal_actions(self.browse_button)
        self.activate_modal_actions(
            self.save_button,
            self.query_one(f'#{self._cancel_button_id}', Button),
            focus=False,
        )

    def action_dismiss_screen(self) -> None:
        self.dismiss()

    @on(Button.Pressed, '#browse-file-button')
    @on(Button.Pressed, '#browse-save-location-button')
    async def open_file_picker(self) -> None:
        await self.app.push_screen(
            ExtendedFileOpen(
                location=Path.home(),
                title=self._browse_title,
                open_button=self._browse_open_button,
                must_exist=self._must_exist,
                default_file=self._default_file_name,
                suggest_completions=True,
            ),
            callback=self._handle_file_selection,
        )

    def _handle_file_selection(self, file_path: Path | None) -> None:
        if file_path:
            self._selected_file = file_path
            self.file_path_input.value = str(file_path)
            self.save_button.disabled = False
        elif self._initial_path is None:
            self._selected_file = None
            self.save_button.disabled = True

    @on(Button.Pressed, '#add-attachment-button-save')
    @on(Button.Pressed, '#save-attachment-button-save')
    def handle_save(self) -> None:
        if self._selected_file:
            self.dismiss(str(self._selected_file))
        else:
            self.dismiss()

    @on(Button.Pressed, '#add-attachment-button-quit')
    @on(Button.Pressed, '#save-attachment-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
