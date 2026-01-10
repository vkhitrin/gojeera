"""A vertical container widget that suppresses click propagation except for buttons."""

from textual import events
from textual.containers import Vertical


class VerticalSuppressClicks(Vertical):
    """Vertical container that stops click propagation except for buttons."""

    def on_click(self, message: events.Click) -> None:
        from textual.widgets import Button

        if not isinstance(message.control, Button):
            message.stop()
