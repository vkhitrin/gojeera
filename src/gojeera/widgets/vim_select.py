"""Select widget with vim-style ctrl+j/k navigation support."""

from __future__ import annotations

from textual import events
from textual.widgets import Select
from textual.widgets._select import SelectOverlay


class VimSelect(Select):
    """Select widget that supports vim-style navigation."""

    async def _on_key(self, event: events.Key) -> None:
        if not self.expanded:
            return await super()._on_key(event)

        try:
            option_list = self.query_one(SelectOverlay)
        except Exception:
            return await super()._on_key(event)

        if option_list.option_count == 0:
            return await super()._on_key(event)

        if event.key == 'ctrl+j':
            event.prevent_default()
            event.stop()
            highlighted = option_list.highlighted or 0
            highlighted = (highlighted + 1) % option_list.option_count
            option_list.highlighted = highlighted
            return

        if event.key == 'ctrl+k':
            event.prevent_default()
            event.stop()
            highlighted = option_list.highlighted or 0
            highlighted = (highlighted - 1) % option_list.option_count
            option_list.highlighted = highlighted
            return

        return await super()._on_key(event)
