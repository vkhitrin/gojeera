from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class QuitScreen(ModalScreen[str]):
    """Screen with a dialog to quit."""

    BINDINGS = [
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
            self.query_one('#button-cancel', Button).jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

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

    def on_click(self) -> None:
        self.app.pop_screen()
