from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic, Literal, TypeVar, cast

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Select, TextArea

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

    ENABLE_CTRL_S_POSITIVE_BUTTON = True

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
        Binding('ctrl+c', 'dismiss_screen_with_ctrl_c', 'Close', show=False),
        Binding('ctrl+s', 'press_positive_button', 'Save', show=False),
        ('escape', 'dismiss_screen', 'Close'),
        Binding('f12', 'app.debug_info', 'Debug', show=False),
        Binding('ctrl+backslash', 'show_overlay', 'Jump', show=False),
        build_toggle_footer_binding(),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dirty = False
        self._dirty_baseline: dict[int, object] = {}
        self._dirty_tracked_widgets: list[Widget] = []

    def action_toggle_footer_visibility(self) -> None:
        app = cast('JiraApp', self.app)
        app.toggle_footer_visibility()

    def action_dismiss_screen(self) -> None:
        self.dismiss()

    def action_press_positive_button(self) -> None:
        if not self.ENABLE_CTRL_S_POSITIVE_BUTTON:
            return

        try:
            positive_buttons = self.query(Button).filter('.modal-action-button--confirm')
        except Exception:
            return

        for button in positive_buttons:
            if not button.disabled and button.display:
                button.press()
                return

    @on(events.Mount)
    def _on_mount_dirty_tracking(self) -> None:
        self.call_after_refresh(self.reset_dirty_state)

    def action_dismiss_screen_with_ctrl_c(self) -> None:
        if not self.is_dirty():
            self.dismiss()
            return

        from gojeera.components.screens.confirmation_screen import ConfirmationScreen

        self.app.push_screen(
            ConfirmationScreen('Discard unsaved changes and close this screen?'),
            self._handle_dirty_dismiss_confirmation,
        )

    def _handle_dirty_dismiss_confirmation(self, should_close: bool | None = None) -> None:
        if should_close:
            self.dismiss()

    def reset_dirty_state(self) -> None:
        """Mark the current widget values as clean."""

        tracked_widgets = self._collect_dirty_tracked_widgets()
        self._dirty_tracked_widgets = [widget for widget, _value in tracked_widgets]
        self._dirty_baseline = {id(widget): value for widget, value in tracked_widgets}
        self.dirty = False

    def is_dirty(self) -> bool:
        self._refresh_dirty_state()
        return self.dirty

    def on_input_changed(self, event: Input.Changed) -> None:
        self._refresh_dirty_state_from_event(event.input)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._refresh_dirty_state_from_event(event.text_area)

    def on_select_changed(self, event: Select.Changed) -> None:
        self._refresh_dirty_state_from_event(event.select)

    def _refresh_dirty_state_from_event(self, widget: Widget) -> None:
        if any(widget is tracked_widget for tracked_widget in self._dirty_tracked_widgets):
            self._refresh_dirty_state()

    def _refresh_dirty_state(self) -> None:
        self.dirty = any(self._widget_is_dirty(widget) for widget in self._dirty_tracked_widgets)

    def _widget_is_dirty(self, widget: Widget) -> bool:
        try:
            value_has_changed = getattr(widget, 'value_has_changed', None)
            if isinstance(value_has_changed, bool):
                return value_has_changed
        except Exception:
            pass

        current_value = self._dirty_widget_value(widget)
        if current_value is None:
            return False
        return current_value != self._dirty_baseline.get(id(widget), current_value)

    def _collect_dirty_tracked_widgets(self) -> list[tuple[Widget, object]]:
        tracked_widgets: list[tuple[Widget, object]] = []

        for widget in self.query(Widget):
            value = self._dirty_widget_value(widget)
            if value is not None:
                tracked_widgets.append((widget, value))

        return tracked_widgets

    @staticmethod
    def _dirty_widget_value(widget: Widget) -> object | None:
        if isinstance(widget, TextArea):
            return widget.text

        if isinstance(widget, Input | Select):
            return widget.value

        if hasattr(widget, 'text'):
            try:
                text = getattr(widget, 'text')
            except Exception:
                text = None
            if isinstance(text, str):
                return text

        if hasattr(widget, 'selection'):
            try:
                return getattr(widget, 'selection')
            except Exception:
                return None

        if hasattr(widget, 'value'):
            try:
                return getattr(widget, 'value')
            except Exception:
                return None

        return None

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
