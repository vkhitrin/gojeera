from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, Input, Label, Select, Static
from textual.worker import Worker

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, LinkWorkItemType
from gojeera.utils.focus import focus_first_available
from gojeera.utils.work_item_reference import resolve_work_item_reference
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.vim_select import VimSelect
from gojeera.widgets.work_item_footer_details import WorkItemFooterDetails

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class LinkedWorkItemInputWidget(ExtendedInput):
    def __init__(self):
        super().__init__(
            classes='required',
            type='text',
            placeholder='KEY or Browse URL',
            tooltip='Enter a work item key or Jira browse URL',
        )
        self.compact = True


class WorkItemLinkTypeSelector(VimSelect):
    def __init__(self, items: list[tuple[str, str]]):
        super().__init__(
            options=items,
            prompt='Select a link type',
            name='work_item_link_types',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class AddWorkItemRelationshipScreen(ExtendedModalScreen[dict]):
    """A modal screen to allow the user to link work items."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, work_item_key: str | None = None):
        super().__init__()
        self.work_item_key = work_item_key
        self._modal_title: str = f'Link Work Items - Work Item: {self.work_item_key}'
        self._resolved_work_item: JiraWorkItem | None = None
        self._search_timer: Timer | None = None
        self._search_worker: Worker | None = None

    @property
    def relationship_type(self) -> WorkItemLinkTypeSelector:
        return self.query_one(WorkItemLinkTypeSelector)

    @property
    def linked_work_item_key(self) -> LinkedWorkItemInputWidget:
        return self.query_one(LinkedWorkItemInputWidget)

    @property
    def save_button(self) -> Button:
        return self.query_one('#add-link-button-save', expect_type=Button)

    @property
    def work_item_footer_details(self) -> WorkItemFooterDetails:
        return self.query_one(WorkItemFooterDetails)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='link-work-items-form'):
                with Vertical():
                    link_type_label = Label('Link Type')
                    link_type_label.add_class('field_label')
                    yield link_type_label
                    yield WorkItemLinkTypeSelector([])
                    work_item_key_label = Label('Work Item')
                    work_item_key_label.add_class('field_label')
                    yield work_item_key_label
                    yield LinkedWorkItemInputWidget()
            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='add-link-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='add-link-button-quit',
                    compact=True,
                )
            yield WorkItemFooterDetails()
        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        self.run_worker(self.fetch_work_item_link_types())

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.relationship_type, 'focus')
            set_jump_mode(self.linked_work_item_key, 'focus')

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.query_one('#add-link-button-quit', Button), 'click')
        self.call_after_refresh(
            lambda: focus_first_available(self.relationship_type, self.linked_work_item_key)
        )
        self._reset_validation_message()

    def _extract_work_item_key(self, value: str) -> str | None:
        return resolve_work_item_reference(value)

    def _update_save_button_state(self) -> None:
        self.save_button.disabled = not (
            self._resolved_work_item is not None and self.relationship_type.selection
        )

    def _set_searching_state(self, message: str) -> None:
        self._resolved_work_item = None
        self.work_item_footer_details.show_searching(message)
        self._update_save_button_state()

    def _set_not_found_state(self, message: str) -> None:
        self._resolved_work_item = None
        self.work_item_footer_details.show_not_found(message)
        self._update_save_button_state()

    def _set_resolved_work_item(self, work_item: JiraWorkItem) -> None:
        self._resolved_work_item = work_item
        summary = work_item.cleaned_summary(48)
        self.work_item_footer_details.show_resolved(summary)
        self._update_save_button_state()

    def _reset_validation_message(self) -> None:
        self._resolved_work_item = None
        self.work_item_footer_details.show_not_found()
        self._update_save_button_state()

    async def _lookup_work_item(self, work_item_key: str) -> None:
        app = cast('JiraApp', self.app)
        response: APIControllerResponse = await app.api.get_work_item(
            work_item_id_or_key=work_item_key,
            fields=['id', 'key', 'summary', 'issuetype', 'status'],
        )
        if not response.success or not response.result or not response.result.work_items:
            self.call_after_refresh(lambda: self._set_not_found_state('Work item not found'))
            return

        work_item = response.result.work_items[0]
        self.call_after_refresh(lambda: self._set_resolved_work_item(work_item))

    def _schedule_lookup(self, value: str) -> None:
        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self._search_worker is not None:
            self._search_worker.cancel()
            self._search_worker = None

        raw_value = value.strip() if value else ''
        if not raw_value:
            self.linked_work_item_key.remove_class('-invalid')
            self._reset_validation_message()
            return

        work_item_key = self._extract_work_item_key(raw_value)
        if work_item_key is None:
            self.linked_work_item_key.add_class('-invalid')
            self._set_not_found_state('Work item not found')
            return

        self.linked_work_item_key.remove_class('-invalid')
        self._set_searching_state('Looking up work item...')
        self._search_timer = self.set_timer(
            0.1,
            lambda: setattr(
                self,
                '_search_worker',
                self.run_worker(self._lookup_work_item(work_item_key), exclusive=False),
            ),
        )

    @on(Input.Changed, 'LinkedWorkItemInputWidget')
    def validate_change(self, _: Input.Changed):
        self._schedule_lookup(self.linked_work_item_key.value)

    @on(Select.Changed, 'WorkItemLinkTypeSelector')
    def validate_relationship(self):
        self._update_save_button_state()

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def fetch_work_item_link_types(self) -> None:
        app = cast('JiraApp', self.app)
        response: APIControllerResponse = await app.api.work_item_link_types()
        if not response.success:
            self.notify(
                'Unable to fetch the types of supported links',
                title='Link Work Items',
                severity='error',
            )
            self.relationship_type.set_options([])
        else:
            link_type: LinkWorkItemType
            options: list[tuple[str, str]] = []
            for link_type in response.result or []:
                options.append((link_type.inward, f'{link_type.id}:inward'))
                options.append((link_type.outward, f'{link_type.id}:outward'))
            self.relationship_type.set_options(options)

    @on(Button.Pressed, '#add-link-button-save')
    def handle_save(self) -> None:
        selection = self.relationship_type.selection
        if not selection or self._resolved_work_item is None:
            return

        link_type_id, link_type = selection.split(':')
        self.dismiss(
            {
                'right_work_item_key': self._resolved_work_item.key,
                'link_type': link_type,
                'link_type_id': link_type_id,
            }
        )

    @on(Button.Pressed, '#add-link-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
