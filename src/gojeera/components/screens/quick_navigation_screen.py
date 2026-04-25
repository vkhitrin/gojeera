from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, Input, Label, Static
from textual.worker import Worker

from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.utils.jira.reference import (
    WorkItemReferenceLoader,
    load_work_item_reference,
    lookup_work_item_for_reference,
    resolve_work_item_reference,
)
from gojeera.utils.ui.delayed_lookup import cancel_delayed_lookup, schedule_delayed_lookup
from gojeera.utils.ui.focus import defer_focus_first_available
from gojeera.utils.ui.jumper import configure_modal_jumper_actions
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.work_item.work_item_footer_details import WorkItemFooterDetails

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class QuickNavigationScreen(ExtendedModalScreen[dict[str, str]]):
    """A modal screen to load a Jira work item directly by key."""

    def __init__(self) -> None:
        super().__init__()
        self._modal_title = 'Quick Navigation'
        self._resolved_work_item: JiraWorkItem | None = None
        self._resolved_work_item_reference: str | None = None
        self._search_timer: Timer | None = None
        self._search_worker: Worker | None = None

    @property
    def work_item_key_input(self) -> Input:
        return self.query_one('#quick-navigation-work-item-key', Input)

    @property
    def open_button(self) -> Button:
        return self.query_one('#quick-navigation-button-open', expect_type=Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(
                id='quick-navigation-form', classes='modal-form modal-form--fields'
            ):
                with Vertical():
                    work_item_label = Label('Work Item')
                    work_item_label.add_class('field_label')
                    yield work_item_label
                    yield ExtendedInput(
                        placeholder='KEY or Browse URL',
                        id='quick-navigation-work-item-key',
                        classes='work-item-key-input',
                        compact=True,
                    )
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button,
                    button_id='quick-navigation-button-open',
                    label='Open',
                    disabled=True,
                )
                yield build_modal_cancel_button(Button, button_id='quick-navigation-button-cancel')
            yield WorkItemFooterDetails()
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        defer_focus_first_available(self, self.work_item_key_input)
        self._reset_validation_message()
        configure_modal_jumper_actions(
            self.work_item_key_input,
            self.open_button,
            self.query_one('#quick-navigation-button-cancel', Button),
        )

    def _extract_work_item_key(self, value: str) -> str | None:
        return resolve_work_item_reference(value)

    def _update_open_button_state(self) -> None:
        self.open_button.disabled = self._resolved_work_item is None

    def _set_searching_state(self, message: str) -> None:
        self._resolved_work_item = None
        self._resolved_work_item_reference = None
        self.work_item_footer_details.show_searching(message)
        self._update_open_button_state()

    def _set_resolved_work_item(self, work_item: JiraWorkItem, reference: str) -> None:
        self._resolved_work_item = work_item
        self._resolved_work_item_reference = reference
        summary = work_item.cleaned_summary(48)
        self.work_item_footer_details.show_resolved(summary)
        self._update_open_button_state()

    def _reset_validation_message(self) -> None:
        self._resolved_work_item = None
        self._resolved_work_item_reference = None
        self.work_item_footer_details.show_not_found()
        self._update_open_button_state()

    async def _lookup_work_item(self, work_item_key: str, reference: str) -> None:
        app = cast('JiraApp', self.app)
        work_item = await lookup_work_item_for_reference(app.api, work_item_key)
        if work_item is None:
            self.call_after_refresh(lambda: self._set_not_found_state('Work item not found'))
            return

        self.call_after_refresh(lambda: self._set_resolved_work_item(work_item, reference))

    def _schedule_lookup(self, value: str) -> None:
        self._search_timer, self._search_worker = cancel_delayed_lookup(
            self._search_timer,
            self._search_worker,
        )

        raw_value = value.strip() if value else ''
        if not raw_value:
            self.work_item_key_input.remove_class('-invalid')
            self._reset_validation_message()
            return

        work_item_key = self._extract_work_item_key(raw_value)
        if work_item_key is None:
            self.work_item_key_input.add_class('-invalid')
            self._set_not_found_state('Work item not found')
            return

        self.work_item_key_input.remove_class('-invalid')
        self._set_searching_state('Looking up work item...')
        self._search_timer = schedule_delayed_lookup(
            self,
            lambda: self._lookup_work_item(work_item_key, raw_value),
        )

    def _set_not_found_state(self, message: str) -> None:
        self._resolved_work_item = None
        self._resolved_work_item_reference = None
        self.work_item_footer_details.show_not_found(message)
        self._update_open_button_state()

    @on(Input.Changed, '#quick-navigation-work-item-key')
    def handle_work_item_key_changed(self, event: Input.Changed) -> None:
        self._schedule_lookup(event.value)

    @on(Input.Submitted, '#quick-navigation-work-item-key')
    def handle_submit(self) -> None:
        raw_value = self.work_item_key_input.value.strip()
        if not raw_value:
            self._reset_validation_message()
            return

        if self._resolved_work_item is None:
            return

        self.open_button.press()

    @on(Button.Pressed, '#quick-navigation-button-open')
    def handle_open(self) -> None:
        if self._resolved_work_item is None:
            return

        work_item_reference = self._resolved_work_item_reference or self._resolved_work_item.key
        self.run_worker(self._open_work_item(work_item_reference), exclusive=True)

    async def _open_work_item(self, work_item_reference: str) -> None:
        app = cast('JiraApp', self.app)
        self.dismiss()
        app.run_worker(
            load_work_item_reference(
                cast(WorkItemReferenceLoader, app),
                work_item_reference,
                title='Quick Navigation',
            ),
            exclusive=True,
        )

    @on(Button.Pressed, '#quick-navigation-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
