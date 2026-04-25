from __future__ import annotations

from typing import ClassVar, Generic, Literal, TypeVar

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks

T = TypeVar('T')


class BaseConfirmationDialogScreen(ExtendedModalScreen[T], Generic[T]):
    """Shared two-button confirmation dialog layout."""

    title_text: ClassVar[str] = ''
    message_text: str = ''
    cancel_button_id: ClassVar[str] = ''
    cancel_button_label: ClassVar[str] = 'Cancel'
    confirm_button_id: ClassVar[str] = ''
    confirm_button_label: ClassVar[str] = ''
    confirm_button_variant: ClassVar[
        Literal['default', 'primary', 'success', 'warning', 'error']
    ] = 'error'
    confirm_button_classes: ClassVar[str] = 'dialog-button dialog-button--danger'

    @property
    def cancel_button(self) -> Button:
        return self.query_one(f'#{self.cancel_button_id}', Button)

    @property
    def confirm_button(self) -> Button:
        return self.query_one(f'#{self.confirm_button_id}', Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self.title_text, id='modal_title')
            yield Static(self.message_text, id='modal_message')
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    self.cancel_button_label,
                    variant='primary',
                    id=self.cancel_button_id,
                    classes='dialog-button dialog-button--secondary',
                    compact=True,
                )
                yield Button(
                    self.confirm_button_label,
                    variant=self.confirm_button_variant,
                    id=self.confirm_button_id,
                    classes=self.confirm_button_classes,
                    compact=True,
                )

    def on_mount(self) -> None:
        self.activate_modal_actions(self.cancel_button, self.confirm_button)
