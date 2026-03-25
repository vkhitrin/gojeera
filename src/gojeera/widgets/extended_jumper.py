"""Custom Jumper widget for gojeera application."""

from typing import Literal, Protocol, cast

from textual.errors import NoWidget
from textual.geometry import Offset
from textual.widget import Widget
from textual.widgets import ListView
from textual.widgets._tabbed_content import ContentTab
from textual_jumper import Jumper
from textual_jumper.jump_overlay import JumpOverlay
from textual_jumper.jumper import JumpInfo

JumpMode = Literal['focus', 'click']


class SupportsJumpMode(Protocol):
    """Protocol for widgets that support textual-jumper metadata."""

    jump_mode: JumpMode | None


def set_jump_mode(widget: object, jump_mode: JumpMode | None) -> None:
    """Assign jump mode to a widget through a typed protocol."""

    cast(SupportsJumpMode, widget).jump_mode = jump_mode


class ExtendedJumper(Jumper):
    """Custom Jumper."""

    def focus_returned_widget(self, widget: Widget | None) -> None:
        """Focus a jump target without deferred animated scrolling."""
        if widget is None:
            return
        self.app.set_focus(widget, scroll_visible=False)

        if not self.screen.can_view_entire(widget):
            widget.scroll_visible(animate=False, immediate=True)

    def show(self) -> None:
        self.app.push_screen(JumpOverlay(self.overlays), self.focus_returned_widget)

    def get_overlays(self):
        """Build jump targets in a single filtered pass."""
        screen = self.screen
        content_tabs = [
            widget for widget in screen.walk_children() if isinstance(widget, ContentTab)
        ]

        original_states = {}
        for tab in content_tabs:
            original_states[tab] = tab.can_focus
            tab.can_focus = True

        try:
            ids_to_keys = self.ids_to_keys
            jumpable_widgets: list[tuple[Offset, Widget, JumpMode]] = []
            custom_key_count = 0
            seen_widgets: set[Widget] = set()
            focused_widget = screen.focused

            candidate_widgets: list[Widget] = list(screen.focus_chain)
            candidate_widgets.extend(content_tabs)

            for child in candidate_widgets:
                if child in seen_widgets:
                    continue
                seen_widgets.add(child)
                if child is focused_widget:
                    continue
                if isinstance(child, ContentTab) and child.has_class('-active'):
                    continue

                jump_mode = getattr(child, 'jump_mode', None)
                if jump_mode not in ('focus', 'click') or not child.can_focus:
                    continue
                if not self._is_widget_jumpable(child):
                    continue

                try:
                    widget_x, widget_y = screen.get_offset(child)
                except NoWidget:
                    continue

                jumpable_widgets.append(
                    (
                        Offset(widget_x, widget_y),
                        child,
                        cast(JumpMode, jump_mode),
                    )
                )
                if child.id and child.id in ids_to_keys:
                    custom_key_count += 1

            available_keys = iter(
                self._generate_available_keys(len(jumpable_widgets) - custom_key_count)
            )
            overlays: dict[Offset, JumpInfo] = {}

            for widget_offset, child, jump_mode in jumpable_widgets:
                if child.id and child.id in ids_to_keys:
                    jump_key = ids_to_keys[child.id]
                else:
                    jump_key = next(available_keys, None)
                    if jump_key is None:
                        continue

                overlays[widget_offset] = JumpInfo(jump_key, child, jump_mode)

            self._overlays = overlays
            return overlays
        finally:
            for tab, original_state in original_states.items():
                tab.can_focus = original_state

    def _is_widget_jumpable(self, widget: Widget) -> bool:
        if not widget.display or not widget.visible or not widget.is_on_screen:
            return False

        if not widget.region:
            return False

        if isinstance(widget, ListView):
            if len(widget) == 0:
                return False

        current = widget
        while current is not None:
            if hasattr(current, 'display') and not current.display:
                return False
            if hasattr(current, 'visible') and not current.visible:
                return False
            if getattr(current, 'disabled', False):
                return False
            if getattr(current, 'read_only', False):
                return False
            current = current.parent

        return True
