from typing import cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Select, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
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


class DecisionPickerScreen(ModalScreen[tuple[str, str] | None]):
    """Modal screen for selecting a decision marker type."""

    BINDINGS = [
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
                    yield Label('Decision Type').add_class('field_label')
                    yield DecisionSelector(self.DECISION_TYPES)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Insert',
                    variant='success',
                    id='decision-button-insert',
                    disabled=True,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id='decision-button-quit', compact=True)

        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.decision_select.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.insert_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#decision-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

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
            self.dismiss(None)

    @on(Button.Pressed, '#decision-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)
