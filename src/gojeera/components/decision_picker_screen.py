from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static

from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.vim_select import VimSelect


class DecisionSelector(VimSelect):
    """Custom VimSelect for decision marker selection."""

    def __init__(self, items: list[tuple[str, tuple[str, str]]]):
        super().__init__(
            options=items,
            prompt='Select decision type...',
            name='decision_select',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class DecisionPickerScreen(ExtendedModalScreen[tuple[str, str] | None]):
    """Modal screen for selecting a decision marker type."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+c', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    DECISION_TYPES = [
        ('DECIDED', ('[decision:d]', 'DECIDED')),
        ('ACKNOWLEDGED', ('[decision:a]', 'ACKNOWLEDGED')),
        ('UP FOR DISCUSSION', ('[decision:u]', 'UP FOR DISCUSSION')),
    ]

    def __init__(self):
        super().__init__()
        self._modal_title = 'Insert Decision Marker'

    @property
    def decision_select(self) -> DecisionSelector:
        return self.query_one(DecisionSelector)

    @property
    def insert_button(self) -> Button:
        return self.query_one('#decision-button-insert', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='decision-form'):
                with Vertical():
                    decision_type_label = Label('Decision Type')
                    decision_type_label.add_class('field_label')
                    yield decision_type_label
                    yield DecisionSelector(self.DECISION_TYPES)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Insert',
                    variant='success',
                    id='decision-button-insert',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='decision-button-quit',
                    compact=True,
                )

        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.decision_select, 'focus')
            set_jump_mode(self.insert_button, 'click')
            set_jump_mode(self.query_one('#decision-button-quit', Button), 'click')
        self.call_after_refresh(lambda: focus_first_available(self.decision_select))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Select.Changed, 'DecisionSelector')
    def handle_decision_selected(self) -> None:
        if self.decision_select.selection:
            self.insert_button.disabled = False
        else:
            self.insert_button.disabled = True

    @on(Button.Pressed, '#decision-button-insert')
    def handle_insert(self) -> None:
        selected_value = self.decision_select.value
        if selected_value and isinstance(selected_value, tuple):
            result = cast(tuple[str, str], selected_value)
            self.dismiss(result)
        else:
            self.dismiss()

    @on(Button.Pressed, '#decision-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
