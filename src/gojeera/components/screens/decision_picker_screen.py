from gojeera.components.screens.simple_option_picker_screen import (
    SimpleOptionPickerScreen,
)
from gojeera.widgets.selection.vim_select import VimSelect


class DecisionSelector(VimSelect):
    """Custom VimSelect for decision marker selection."""

    def __init__(self, items: list[tuple[str, tuple[str, str]]]) -> None:
        super().__init__(
            options=items,
            prompt='Select decision type...',
            name='decision_select',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class DecisionPickerScreen(SimpleOptionPickerScreen):
    """Modal screen for selecting a decision marker type."""

    BINDINGS = [
        ('ctrl+c', 'dismiss_screen_with_ctrl_c', 'Close'),
        *SimpleOptionPickerScreen.BINDINGS,
    ]

    def action_dismiss_screen_with_ctrl_c(self) -> None:
        self.dismiss()

    DECISION_TYPES = [
        ('DECIDED', ('[decision:d]', 'DECIDED')),
        ('ACKNOWLEDGED', ('[decision:a]', 'ACKNOWLEDGED')),
        ('UP FOR DISCUSSION', ('[decision:u]', 'UP FOR DISCUSSION')),
    ]
    MODAL_TITLE = 'Insert Decision Marker'
    FIELD_LABEL = 'Decision Type'
    OPTIONS = DECISION_TYPES
    FORM_ID = 'decision-form'
    INSERT_BUTTON_ID = 'decision-button-insert'
    CANCEL_BUTTON_ID = 'decision-button-quit'

    @property
    def option_select(self) -> DecisionSelector:
        return self.query_one(DecisionSelector)

    def build_selector(self) -> DecisionSelector:
        return DecisionSelector(self.OPTIONS)
