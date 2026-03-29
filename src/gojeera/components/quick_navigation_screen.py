from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


WORK_ITEM_KEY_PATTERN = r'^[A-Z][A-Z0-9]+-\d+$'


class QuickNavigationScreen(ExtendedModalScreen[dict[str, str]]):
    """A modal screen to load a Jira work item directly by key."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._modal_title = 'Quick Navigation'

    @property
    def work_item_key_input(self) -> Input:
        return self.query_one('#quick-navigation-work-item-key', Input)

    @property
    def open_button(self) -> Button:
        return self.query_one('#quick-navigation-button-open', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with Vertical(id='quick-navigation-form'):
                yield Label('Work Item Key').add_class('field_label')
                yield ExtendedInput(
                    placeholder='KEY',
                    id='quick-navigation-work-item-key',
                    classes='work-item-key-input',
                    compact=True,
                )
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Open',
                    variant='success',
                    id='quick-navigation-button-open',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='quick-navigation-button-cancel',
                    compact=True,
                )
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        self.call_after_refresh(lambda: focus_first_available(self.work_item_key_input))

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.work_item_key_input, 'focus')
            set_jump_mode(self.open_button, 'click')
            set_jump_mode(self.query_one('#quick-navigation-button-cancel', Button), 'click')

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def _is_work_item_key_valid(self, value: str) -> bool:
        return bool(re.match(WORK_ITEM_KEY_PATTERN, value))

    @on(Input.Changed, '#quick-navigation-work-item-key')
    def handle_work_item_key_changed(self, event: Input.Changed) -> None:
        value = event.value.strip() if event.value else ''
        is_valid = bool(value) and self._is_work_item_key_valid(value)

        if self.open_button.disabled == is_valid:
            self.open_button.disabled = not is_valid

        if not value:
            self.work_item_key_input.remove_class('-invalid')
            return

        if self._is_work_item_key_valid(value):
            self.work_item_key_input.remove_class('-invalid')
        else:
            self.work_item_key_input.add_class('-invalid')

    @on(Input.Submitted, '#quick-navigation-work-item-key')
    def handle_submit(self) -> None:
        work_item_key = self.work_item_key_input.value.strip()
        if not work_item_key:
            self.work_item_key_input.remove_class('-invalid')
            return

        if not self._is_work_item_key_valid(work_item_key):
            self.work_item_key_input.add_class('-invalid')
            self.notify(
                'Invalid work item key format. Expected format: PROJECT-123',
                severity='warning',
                title='Validation Error',
            )
            return

        self.open_button.press()

    @on(Input.Blurred, '#quick-navigation-work-item-key')
    def handle_blur(self, event: Input.Blurred) -> None:
        value = event.value.strip() if event.value else ''
        is_valid = bool(value) and self._is_work_item_key_valid(value)

        if self.open_button.disabled == is_valid:
            self.open_button.disabled = not is_valid

        if not value:
            if self.work_item_key_input.has_class('-invalid'):
                self.work_item_key_input.remove_class('-invalid')
            return

        if self._is_work_item_key_valid(value):
            if self.work_item_key_input.has_class('-invalid'):
                self.work_item_key_input.remove_class('-invalid')
        else:
            if not self.work_item_key_input.has_class('-invalid'):
                self.work_item_key_input.add_class('-invalid')

    @on(Button.Pressed, '#quick-navigation-button-open')
    def handle_open(self) -> None:
        work_item_key = self.work_item_key_input.value.strip()

        if not self._is_work_item_key_valid(work_item_key):
            self.work_item_key_input.add_class('-invalid')
            self.notify(
                'Invalid work item key format. Expected format: PROJECT-123',
                severity='warning',
                title='Quick Navigation',
            )
            return

        self.run_worker(self._open_work_item(work_item_key), exclusive=True)

    async def _open_work_item(self, work_item_key: str) -> None:
        app = cast('JiraApp', self.app)
        response: APIControllerResponse = await app.api.get_work_item(
            work_item_id_or_key=work_item_key,
            fields=['summary'],
        )

        if not response.success or not response.result or not response.result.work_items:
            self.notify(
                response.error or 'Unable to access the selected work item',
                severity='error',
                title='Quick Navigation',
            )
            return

        screen_stack = app.screen_stack
        if len(screen_stack) >= 2:
            calling_screen = screen_stack[-2]
            if calling_screen.__class__.__name__ == 'MainScreen':
                main_screen = cast('MainScreen', calling_screen)
                self.dismiss()
                main_screen.run_worker(main_screen.fetch_work_items(work_item_key), exclusive=True)
                return

        self.dismiss({'work_item_key': work_item_key})

    @on(Button.Pressed, '#quick-navigation-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
