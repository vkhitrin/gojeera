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


class PanelSelector(VimSelect):
    """Custom VimSelect for alert marker selection."""

    def __init__(self, items: list[tuple[str, tuple[str, str]]]):
        super().__init__(
            options=items,
            prompt='Select alert type...',
            name='alert_select',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class PanelPickerScreen(ModalScreen[tuple[str, str] | None]):
    """Modal screen for selecting an alert marker type."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    ALERT_TYPES = [
        ('Note', ('[!NOTE]', 'Note')),
        ('Tip', ('[!TIP]', 'Tip')),
        ('Important', ('[!IMPORTANT]', 'Important')),
        ('Warning', ('[!WARNING]', 'Warning')),
        ('Caution', ('[!CAUTION]', 'Caution')),
    ]

    def __init__(self):
        super().__init__()
        self._modal_title = 'Insert Panel'

    @property
    def alert_select(self) -> PanelSelector:
        return self.query_one(PanelSelector)

    @property
    def insert_button(self) -> Button:
        return self.query_one('#alert-button-insert', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='alert-form'):
                with Vertical():
                    yield Label('Panel Type').add_class('field_label')
                    yield PanelSelector(self.ALERT_TYPES)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Insert',
                    variant='success',
                    id='alert-button-insert',
                    disabled=True,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id='alert-button-quit', compact=True)

        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.alert_select.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.insert_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#alert-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Select.Changed, 'PanelSelector')
    def handle_alert_selected(self) -> None:
        if self.alert_select.selection:
            self.insert_button.disabled = False
        else:
            self.insert_button.disabled = True

    @on(Button.Pressed, '#alert-button-insert')
    def handle_insert(self) -> None:
        selected_value = self.alert_select.value
        if selected_value and isinstance(selected_value, tuple):
            result = cast(tuple[str, str], selected_value)
            self.dismiss(result)
        else:
            self.dismiss(None)

    @on(Button.Pressed, '#alert-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)
