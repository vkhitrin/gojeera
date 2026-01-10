from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class ConfirmationScreen(ModalScreen[bool]):
    """Screen with a dialog to confirm an action."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, message: str):
        super().__init__()
        self.message = message or 'Are you sure you want to perform this action?'

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Confirm Action', id='modal_title')
            yield Static(self.message, id='modal_message')
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Cancel', variant='primary', id='confirmation-button-cancel', compact=True
                )
                yield Button(
                    'Accept', variant='error', id='confirmation-button-accept', compact=True
                )

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.query_one('#confirmation-button-cancel', Button).jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#confirmation-button-accept', Button).jump_mode = 'click'  # type: ignore[attr-defined]

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
        self.dismiss(False)

    def on_click(self) -> None:
        self.dismiss(False)
