from __future__ import annotations

from typing import TYPE_CHECKING, Generic, Literal, TypeVar, cast

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget

from gojeera.commands.binding_provider import build_toggle_footer_binding
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.navigation.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.work_item.work_item_footer_details import WorkItemFooterDetails

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

    ExtendedModalScreen LoadingIndicator,
    ExtendedModalScreen LoadingIndicator.-textual-loading-indicator {
        background: $surface;
        color: $accent;
    }
    """

    BINDINGS = [
        ('escape', 'dismiss_screen', 'Close'),
        Binding('f12', 'app.debug_info', 'Debug', show=False),
        Binding('ctrl+backslash', 'show_overlay', 'Jump', show=False),
        build_toggle_footer_binding(),
    ]

    def action_toggle_footer_visibility(self) -> None:
        app = cast('JiraApp', self.app)
        app.toggle_footer_visibility()

    def action_dismiss_screen(self) -> None:
        self.dismiss()

    def compose_modal_jumper(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

    @property
    def work_item_footer_details(self) -> WorkItemFooterDetails:
        return self.query_one(WorkItemFooterDetails)

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        try:
            jumper = self.query_one(ExtendedJumper)
        except NoMatches:
            return
        jumper.show()

    def dismiss_on_backdrop_click(self) -> None:
        self.dismiss()

    def activate_modal_actions(
        self,
        *controls: Widget,
        jump_mode: Literal['click', 'focus'] = 'click',
        focus: bool = True,
    ) -> None:
        if CONFIGURATION.get().jumper.enabled:
            for control in controls:
                set_jump_mode(control, jump_mode)
        if focus:
            self.call_after_refresh(lambda: focus_first_available(*controls))

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
