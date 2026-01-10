"""Custom Jumper widget for gojeera application."""

from textual_jumper import Jumper


class ExtendedJumper(Jumper):
    """Custom Jumper."""

    def get_overlays(self):
        """Override to temporarily enable ContentTab focus and filter hidden widgets."""
        from textual.widgets._tabbed_content import ContentTab

        content_tabs = [
            widget for widget in self.screen.walk_children() if isinstance(widget, ContentTab)
        ]

        original_states = {}
        for tab in content_tabs:
            original_states[tab] = tab.can_focus
            tab.can_focus = True

        try:
            overlays = super().get_overlays()

            filtered_overlays = {
                offset: jump_info
                for offset, jump_info in overlays.items()
                if self._is_widget_visible(jump_info.widget)
            }
            return filtered_overlays
        finally:
            for tab, original_state in original_states.items():
                tab.can_focus = original_state

    def _is_widget_visible(self, widget_ref):
        from textual.widget import Widget
        from textual.widgets import ListView

        if isinstance(widget_ref, str):
            try:
                widget = self.screen.query_one(f'#{widget_ref}', Widget)
            except Exception:
                return False
        elif isinstance(widget_ref, Widget):
            widget = widget_ref
        else:
            return False

        if not widget.display:
            return False

        if isinstance(widget, ListView):
            if len(widget) == 0:
                return False

        current = widget.parent
        while current is not None and hasattr(current, 'display'):
            if not current.display:
                return False
            current = getattr(current, 'parent', None)

        return True
