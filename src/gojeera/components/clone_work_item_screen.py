from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class CloneWorkItemScreen(ModalScreen[dict | None]):
    """A modal screen to configure the cloned work item's summary."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, work_item_key: str, original_summary: str):
        super().__init__()
        self.work_item_key = work_item_key
        self.original_summary = original_summary
        self.default_summary = f'CLONE - {original_summary}'
        self._modal_title = f'Clone Work Item - {self.work_item_key}'

    @property
    def summary_input(self) -> Input:
        return self.query_one('#clone-work-item-summary', Input)

    @property
    def clone_button(self) -> Button:
        return self.query_one('#clone-work-item-button-save', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='clone-work-item-form'):
                with Vertical(id='summary-field-container'):
                    yield Label('Summary').add_class('field_label')
                    summary_widget = Input(
                        id='clone-work-item-summary',
                        placeholder='',
                        value=self.default_summary,
                        valid_empty=False,
                    )
                    summary_widget.tooltip = 'Enter a summary for the cloned work item'
                    summary_widget.compact = True
                    yield summary_widget
                    yield Label(
                        '• Edit the summary above or keep the default\n'
                        '• Same project and issue type will be used',
                        id='summary-hint',
                    )
                    yield Label(
                        '⚠ Most fields copied; status, comments, attachments excluded',
                        id='summary-warning',
                    )

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Clone',
                    variant='success',
                    id='clone-work-item-button-save',
                    disabled=False,
                    compact=True,
                )
                yield Button(
                    'Cancel', variant='error', id='clone-work-item-button-quit', compact=True
                )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        """Configure jumper after mount and set up initial state."""
        if CONFIGURATION.get().jumper.enabled:
            self.summary_input.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.clone_button.jump_mode = 'click'  # type: ignore[attr-defined]
            cancel_button = self.query_one('#clone-work-item-button-quit', Button)
            cancel_button.jump_mode = 'click'  # type: ignore[attr-defined]

        self.summary_input.focus()

        self.summary_input.action_select_all()

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Input.Changed, '#clone-work-item-summary')
    def on_summary_changed(self, event: Input.Changed) -> None:
        summary = event.value.strip()
        self.clone_button.disabled = len(summary) == 0

    @on(Button.Pressed, '#clone-work-item-button-save')
    def handle_clone(self) -> None:
        summary = self.summary_input.value.strip()
        if not summary:
            return

        self.dismiss({'summary': summary, 'clone': True})

    @on(Button.Pressed, '#clone-work-item-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)
