from __future__ import annotations

from typing import Generic, TypeVar

from textual import events

from gojeera.widgets.extended_modal_screen import ExtendedModalScreen

T = TypeVar('T')


class DynamicModalScreen(ExtendedModalScreen[T], Generic[T]):
    """Modal screen with a shared deferred layout hook for dynamic sizing."""

    def initialize_dynamic_modal(self) -> None:
        self.schedule_dynamic_modal_layout()

    def schedule_dynamic_modal_layout(self) -> None:
        self.call_after_refresh(self.apply_dynamic_modal_layout)

    def apply_dynamic_modal_layout(self) -> None:
        """Apply the current modal size. Subclasses should override this."""

    def on_resize(self, event: events.Resize) -> None:
        self.schedule_dynamic_modal_layout()
