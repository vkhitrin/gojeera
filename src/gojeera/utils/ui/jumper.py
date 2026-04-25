from __future__ import annotations

from textual.widgets import Button

from gojeera.internal.store.config import CONFIGURATION
from gojeera.widgets.navigation.extended_jumper import set_jump_mode


def configure_modal_jumper_actions(
    focus_widget: object,
    primary_action_widget: object,
    cancel_button: Button,
) -> None:
    if not CONFIGURATION.get().jumper.enabled:
        return

    set_jump_mode(focus_widget, 'focus')
    set_jump_mode(primary_action_widget, 'click')
    set_jump_mode(cancel_button, 'click')
