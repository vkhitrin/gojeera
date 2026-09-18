from textual.widgets import Footer

from gojeera.internal.store.config import CONFIGURATION


class ExtendedFooter(Footer):
    """Footer widget that respects the current footer visibility setting."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.display = CONFIGURATION.get().show_footer
