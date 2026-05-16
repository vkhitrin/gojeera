"""Select widget with vim-style ctrl+j/k navigation support."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from textual import events
from textual.widgets import Select
from textual.widgets._select import SelectOverlay


class VimSelect(Select):
    """Select widget that supports vim-style navigation."""

    @property
    def selection(self) -> str | None:
        if self.value == Select.NULL:
            return None

        return str(self.value) if self.value else None

    def replace_options(
        self,
        options: Sequence[tuple[str, Any]],
        *,
        selection: str | None = None,
    ) -> None:
        current_value = None if self.value == Select.NULL else self.value
        self.set_options(options)

        if selection is not None and any(option_value == selection for _, option_value in options):
            self.value = selection
            return

        if any(option_value == current_value for _, option_value in options):
            self.value = current_value
            return

        if getattr(self, '_allow_blank', True):
            self.value = Select.NULL
        elif options:
            self.value = options[0][1]

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
