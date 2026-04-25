from textual import on
from textual.widgets import Button

from gojeera.components.screens.base_confirmation_dialog_screen import BaseConfirmationDialogScreen


class ConfirmationScreen(BaseConfirmationDialogScreen[bool]):
    """Screen with a dialog to confirm an action."""

    title_text = 'Confirm Action'
    cancel_button_id = 'confirmation-button-cancel'
    confirm_button_id = 'confirmation-button-accept'
    confirm_button_label = 'Accept'

    def __init__(self, message: str):
        super().__init__()
        self.message_text = message or 'Are you sure you want to perform this action?'

    @property
    def message(self) -> str:
        return self.message_text

    @on(Button.Pressed, '#confirmation-button-accept')
    def handle_accept(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, '#confirmation-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
