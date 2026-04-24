from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, Input, Label, Static
from textual.worker import Worker

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem
from gojeera.utils.focus import focus_first_available
from gojeera.utils.work_item_reference import (
    WorkItemReferenceLoader,
    load_work_item_reference,
    resolve_work_item_reference,
)
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.work_item_footer_details import WorkItemFooterDetails

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class QuickNavigationScreen(ExtendedModalScreen[dict[str, str]]):
    """A modal screen to load a Jira work item directly by key."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

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

    @property
    def work_item_footer_details(self) -> WorkItemFooterDetails:
        return self.query_one(WorkItemFooterDetails)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
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
                yield Button(
                    'Open',
                    variant='success',
                    id='quick-navigation-button-open',
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='quick-navigation-button-cancel',
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )
            yield WorkItemFooterDetails()
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self.call_after_refresh(lambda: focus_first_available(self.work_item_key_input))
        self._reset_validation_message()

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.work_item_key_input, 'focus')
            set_jump_mode(self.open_button, 'click')
            set_jump_mode(self.query_one('#quick-navigation-button-cancel', Button), 'click')

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

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
        response: APIControllerResponse = await app.api.get_work_item(
            work_item_id_or_key=work_item_key,
            fields=['id', 'key', 'summary', 'issuetype', 'status'],
        )
        if not response.success or not response.result or not response.result.work_items:
            self.call_after_refresh(lambda: self._set_not_found_state('Work item not found'))
            return

        work_item = response.result.work_items[0]
        self.call_after_refresh(lambda: self._set_resolved_work_item(work_item, reference))

    def _schedule_lookup(self, value: str) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self._search_worker is not None:
            self._search_worker.cancel()
            self._search_worker = None

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
        self._search_timer = self.set_timer(
            0.1,
            lambda: setattr(
                self,
                '_search_worker',
                self.run_worker(self._lookup_work_item(work_item_key, raw_value), exclusive=False),
            ),
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
        screen_stack = app.screen_stack
        if len(screen_stack) >= 2:
            calling_screen = screen_stack[-2]
            if calling_screen.__class__.__name__ == 'MainScreen':
                main_screen = cast('MainScreen', calling_screen)
                self.dismiss()
                main_screen.run_worker(
                    load_work_item_reference(
                        cast(WorkItemReferenceLoader, main_screen),
                        work_item_reference,
                        title='Quick Navigation',
                    ),
                    exclusive=True,
                )
                return

        self.dismiss({'work_item_reference': work_item_reference})

    @on(Button.Pressed, '#quick-navigation-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
