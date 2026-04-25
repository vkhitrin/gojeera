from typing import ClassVar, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static

from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.selection.vim_select import VimSelect


class SimpleOptionPickerScreen(ExtendedModalScreen[tuple[str, str] | None]):
    """Shared modal for selecting a tuple payload from a list of options."""

    MODAL_TITLE: ClassVar[str]
    FIELD_LABEL: ClassVar[str]
    OPTIONS: ClassVar[list[tuple[str, tuple[str, str]]]]
    FORM_ID: ClassVar[str]
    INSERT_BUTTON_ID: ClassVar[str]
    CANCEL_BUTTON_ID: ClassVar[str]

    def __init__(self) -> None:
        super().__init__()
        self._modal_title = self.MODAL_TITLE

    @property
    def option_select(self) -> VimSelect:
        return self.query_one(VimSelect)

    def build_selector(self) -> VimSelect:
        raise NotImplementedError

    @property
    def insert_button(self) -> Button:
        return self.query_one(f'#{self.INSERT_BUTTON_ID}', Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id=self.FORM_ID, classes='modal-form modal-form--fields'):
                with Vertical():
                    option_type_label = Label(self.FIELD_LABEL)
                    option_type_label.add_class('field_label')
                    yield option_type_label
                    yield self.build_selector()

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button,
                    button_id=self.INSERT_BUTTON_ID,
                    label='Insert',
                    disabled=True,
                )
                yield build_modal_cancel_button(Button, button_id=self.CANCEL_BUTTON_ID)

        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self.activate_modal_actions(self.option_select, jump_mode='focus')
        self.activate_modal_actions(
            self.insert_button,
            self.query_one(f'#{self.CANCEL_BUTTON_ID}', Button),
            focus=False,
        )

    @on(Select.Changed, 'VimSelect')
    def handle_option_selected(self) -> None:
        self.insert_button.disabled = not self.option_select.selection

    @on(Button.Pressed)
    def handle_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == self.INSERT_BUTTON_ID:
            selected_value = self.option_select.value
            if selected_value and isinstance(selected_value, tuple):
                self.dismiss(cast(tuple[str, str], selected_value))
            else:
                self.dismiss()
            return

        if event.button.id == self.CANCEL_BUTTON_ID:
            self.dismiss()
