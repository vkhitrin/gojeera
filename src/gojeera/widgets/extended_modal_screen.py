from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar, cast

from textual import events
from textual.binding import Binding
from textual.screen import ModalScreen

from gojeera.commands.binding_provider import register_binding_in_command_palette

if TYPE_CHECKING:
    from gojeera.app import JiraApp

T = TypeVar('T')


class ExtendedModalScreen(ModalScreen[T], Generic[T]):
    """Modal screen with global overlay bindings that remain available in modals."""

    DEFAULT_CSS = """
    ExtendedModalScreen {
        align: center middle;
    }

    ExtendedModalScreen #modal_outer {
        background: $surface;
        padding: 0;
        max-height: 90%;
        overflow: hidden hidden;
    }

    ExtendedModalScreen #modal_title {
        width: 100%;
        height: auto;
        padding: 1;
        background: $surface;
        color: $text;
        text-align: center;
        text-style: bold;
    }

    ExtendedModalScreen #modal_footer {
        width: 100%;
        height: auto;
        align: center middle;
        padding: 0 2;
        background: $surface;
    }

    ExtendedModalScreen #modal_message {
        width: 100%;
        height: auto;
        padding: 0 2 1 2;
        background: $surface;
        color: $text;
        text-align: center;
    }

    ExtendedModalScreen #modal-form-scroll {
        width: 100%;
        height: 1fr;
        background: $surface;
        scrollbar-size-vertical: 1;
    }
    """

    BINDINGS = [
        register_binding_in_command_palette(
            Binding(
                key='f11',
                action='toggle_footer_visibility',
                description='Toggle Footer',
                tooltip='Show or hide the footer',
                show=False,
            )
        )
    ]

    def action_toggle_footer_visibility(self) -> None:
        app = cast('JiraApp', self.app)
        app.toggle_footer_visibility()

    def dismiss_on_backdrop_click(self) -> None:
        self.dismiss()

    def on_click(self, event: events.Click) -> None:
        try:
            modal_outer = self.query_one('#modal_outer')
        except Exception:
            self.dismiss_on_backdrop_click()
            return

        control = event.control
        if control is not None and modal_outer in control.ancestors_with_self:
            return

        self.dismiss_on_backdrop_click()
