from textual.widgets import Static


class Spacer(Static, can_focus=False):
    """A generic transparent spacer widget."""

    DEFAULT_CSS = """
    Spacer {
        height: 1;
        margin: 0;
        padding: 0;
        background: transparent;
    }
    """
