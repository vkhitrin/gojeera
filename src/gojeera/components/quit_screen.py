from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static

from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class QuitScreen(ExtendedModalScreen[str]):
    """Screen with a dialog to quit."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Quit gojeera', id='modal_title')
            yield Static('Are you sure you want to quit?', id='modal_message')
            with Horizontal(id='modal_footer'):
                yield Button('Cancel', variant='primary', id='button-cancel', compact=True)
                yield Button('Quit', variant='error', id='button-quit', compact=True)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.query_one('#button-cancel', Button), 'click')
            set_jump_mode(self.query_one('#button-quit', Button), 'click')
        self.call_after_refresh(
            lambda: focus_first_available(
                self.query_one('#button-cancel', Button),
                self.query_one('#button-quit', Button),
            )
        )

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def close_connections(self):
        app = cast('JiraApp', self.screen.app)  # noqa: F821
        await app.api.api.client.close_async_client()
        await app.api.api.async_http_client.close_async_client()

    @on(Button.Pressed, '#button-quit')
    def handle_quit(self) -> None:
        self.run_worker(self.close_connections)
        self.app.exit()

    @on(Button.Pressed, '#button-cancel')
    def handle_cancel(self) -> None:
        self.app.pop_screen()
