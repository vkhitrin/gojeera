from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Static

from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks


class CloneWorkItemScreen(ExtendedModalScreen[dict | None]):
    """A modal screen to configure the cloned work item's summary."""

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
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='clone-work-item-form', classes='modal-form modal-form--tight'):
                with Vertical(id='summary-field-container', classes='modal-form-section'):
                    summary_label = Label('Summary')
                    summary_label.add_class('field_label')
                    yield summary_label
                    summary_widget = ExtendedInput(
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
                        classes='modal-form-hint',
                    )
                    yield Label(
                        '⚠ Most fields copied; status, comments, attachments excluded',
                        id='summary-warning',
                        classes='modal-form-warning',
                    )

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button, button_id='clone-work-item-button-save', label='Clone'
                )
                yield build_modal_cancel_button(Button, button_id='clone-work-item-button-quit')
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        """Configure jumper after mount and set up initial state."""
        self.activate_modal_actions(self.summary_input, jump_mode='focus', focus=False)
        self.activate_modal_actions(
            self.clone_button,
            self.query_one('#clone-work-item-button-quit', Button),
            focus=False,
        )

        def focus_summary() -> None:
            if focus_first_available(self.summary_input):
                self.summary_input.action_select_all()

        self.call_after_refresh(focus_summary)

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
        self.dismiss()
