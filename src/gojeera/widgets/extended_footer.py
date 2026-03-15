from textual.widgets import Footer

from gojeera.config import CONFIGURATION


class ExtendedFooter(Footer):
    """Footer widget that respects the current footer visibility setting."""

    def on_mount(self) -> None:
        super().on_mount()
        self.display = CONFIGURATION.get().show_footer
