"""SelectionList widget with vim-style ctrl+j/k navigation support."""

from __future__ import annotations

from textual import events
from textual.widgets import SelectionList


class VimSelectionList(SelectionList):
    """SelectionList widget that supports vim-style navigation."""

    async def _on_key(self, event: events.Key) -> None:
        if event.key == 'ctrl+j':
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return

        if event.key == 'ctrl+k':
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return

        return await super()._on_key(event)
