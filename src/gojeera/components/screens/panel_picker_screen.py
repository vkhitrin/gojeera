from gojeera.components.screens.simple_option_picker_screen import (
    SimpleOptionPickerScreen,
)
from gojeera.widgets.selection.vim_select import VimSelect


class PanelSelector(VimSelect):
    """Custom VimSelect for alert marker selection."""

    def __init__(self, items: list[tuple[str, tuple[str, str]]]) -> None:
        super().__init__(
            options=items,
            prompt='Select alert type...',
            name='alert_select',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class PanelPickerScreen(SimpleOptionPickerScreen):
    """Modal screen for selecting an alert marker type."""

    ALERT_TYPES = [
        ('Note', ('[!NOTE]', 'Note')),
        ('Tip', ('[!TIP]', 'Tip')),
        ('Important', ('[!IMPORTANT]', 'Important')),
        ('Warning', ('[!WARNING]', 'Warning')),
        ('Caution', ('[!CAUTION]', 'Caution')),
    ]
    MODAL_TITLE = 'Insert Panel'
    FIELD_LABEL = 'Panel Type'
    OPTIONS = ALERT_TYPES
    FORM_ID = 'alert-form'
    INSERT_BUTTON_ID = 'alert-button-insert'
    CANCEL_BUTTON_ID = 'alert-button-quit'

    @property
    def option_select(self) -> PanelSelector:
        return self.query_one(PanelSelector)

    def build_selector(self) -> PanelSelector:
        return PanelSelector(self.OPTIONS)
