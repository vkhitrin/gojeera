from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from gojeera.app import JiraApp

from textual import on
from textual.widgets import Button

from gojeera.components.screens.base_confirmation_dialog_screen import BaseConfirmationDialogScreen


class QuitScreen(BaseConfirmationDialogScreen[str]):
    """Screen with a dialog to quit."""

    title_text = 'Quit gojeera'
    message_text = 'Are you sure you want to quit?'
    cancel_button_id = 'button-cancel'
    confirm_button_id = 'button-quit'
    confirm_button_label = 'Quit'
    confirm_button_classes = 'dialog-button dialog-button--danger-soft'

    async def close_connections(self):
        app = cast('JiraApp', self.screen.app)  # noqa: F821
        await app.api.close()

    @on(Button.Pressed, '#button-quit')
    def handle_quit(self) -> None:
        self.run_worker(self.close_connections)
        self.app.exit()

    @on(Button.Pressed, '#button-cancel')
    def handle_cancel(self) -> None:
        self.app.pop_screen()
