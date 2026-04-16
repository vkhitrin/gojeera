from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class ConfirmationScreen(ExtendedModalScreen[bool]):
    """Screen with a dialog to confirm an action."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, message: str):
        super().__init__()
        self.message = message or 'Are you sure you want to perform this action?'

    @property
    def cancel_button(self) -> Button:
        return self.query_one('#confirmation-button-cancel', Button)

    @property
    def accept_button(self) -> Button:
        return self.query_one('#confirmation-button-accept', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Confirm Action', id='modal_title')
            yield Static(self.message, id='modal_message')
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Cancel',
                    variant='primary',
                    id='confirmation-button-cancel',
                    classes='dialog-button dialog-button--secondary',
                    compact=True,
                )
                yield Button(
                    'Accept',
                    variant='error',
                    id='confirmation-button-accept',
                    classes='dialog-button dialog-button--danger',
                    compact=True,
                )

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.cancel_button, 'click')
            set_jump_mode(self.accept_button, 'click')
        self.call_after_refresh(
            lambda: focus_first_available(self.cancel_button, self.accept_button)
        )

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Button.Pressed, '#confirmation-button-accept')
    def handle_accept(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, '#confirmation-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
