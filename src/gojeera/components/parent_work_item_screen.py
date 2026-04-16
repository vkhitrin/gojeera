from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import Button, Input, Label, Static
from textual.worker import Worker

from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, WorkItemType
from gojeera.utils.focus import focus_first_available
from gojeera.utils.urls import normalize_work_item_key
from gojeera.widgets.extended_button import ExtendedButton
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.work_item_footer_details import WorkItemFooterDetails
from gojeera.widgets.work_item_key_picker import WorkItemKeyInput

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ParentWorkItemScreen(ExtendedModalScreen[dict[str, str] | None]):
    """Modal screen for selecting a valid parent work item."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(self, work_item: JiraWorkItem) -> None:
        super().__init__()
        self._work_item = work_item
        self._modal_title = 'Set Parent'
        self._allowed_parent_type_ids: set[str] = set()
        self._search_timer: Timer | None = None
        self._search_worker: Worker | None = None
        self._parent_types_loaded = False
        self._resolved_parent: JiraWorkItem | None = None

    @property
    def parent_input(self) -> WorkItemKeyInput:
        return self.query_one(WorkItemKeyInput)

    @property
    def apply_button(self) -> ExtendedButton:
        return self.query_one('#parent-work-item-button-apply', ExtendedButton)

    @property
    def work_item_footer_details(self) -> WorkItemFooterDetails:
        return self.query_one(WorkItemFooterDetails)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(
                id='parent-work-item-form', classes='modal-form modal-form--fields'
            ):
                with Vertical():
                    parent_work_item_label = Label('Parent Work Item')
                    parent_work_item_label.add_class('field_label')
                    yield parent_work_item_label
                    parent_input = WorkItemKeyInput()
                    parent_input.disabled = True
                    yield parent_input

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield ExtendedButton(
                    'Set',
                    variant='success',
                    id='parent-work-item-button-apply',
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=True,
                    compact=True,
                )
                yield ExtendedButton(
                    'Cancel',
                    variant='error',
                    id='parent-work-item-button-cancel',
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )

            yield WorkItemFooterDetails()

        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        current_parent_key = self._current_parent_key
        self.parent_input.disabled = False
        with self.prevent(Input.Changed):
            self.parent_input.value = current_parent_key
        self._reset_validation_message()
        self._update_apply_button_state()

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.parent_input, 'focus')
            set_jump_mode(self.apply_button, 'click')
            set_jump_mode(self.query_one('#parent-work-item-button-cancel', Button), 'click')

        self.call_after_refresh(lambda: focus_first_available(self.parent_input))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def _allowed_parent_types(self, project_types: list[WorkItemType]) -> list[WorkItemType]:
        current_type = self._work_item.work_item_type
        if current_type is None:
            return []

        if current_type.subtask:
            return [
                item for item in project_types if not item.subtask and item.hierarchy_level == 0
            ]

        if current_type.hierarchy_level is None:
            return []

        parent_level = current_type.hierarchy_level + 1
        return [
            item
            for item in project_types
            if not item.subtask and item.hierarchy_level == parent_level
        ]

    @property
    def _current_parent_key(self) -> str:
        return self._work_item.parent_key.strip()

    def _selected_parent_key(self) -> str:
        if self._resolved_parent is not None:
            return self._resolved_parent.key
        return ''

    def _update_apply_button_state(self) -> None:
        selected_parent_key = self._selected_parent_key()
        if not selected_parent_key:
            self.apply_button.disabled = True
            return

        self.apply_button.disabled = selected_parent_key == self._current_parent_key

    def _set_resolved_parent(self, work_item: JiraWorkItem) -> None:
        if work_item.key == self._current_parent_key:
            self._reset_validation_message()
            return
        work_item_type = work_item.work_item_type.name if work_item.work_item_type else 'Work Item'
        summary = work_item.cleaned_summary(48)
        self._resolved_parent = work_item
        message = Text()
        message.append(f'[{work_item_type}] ')
        message.append(work_item.key)
        message.append(' - ')
        message.append(summary)
        self.work_item_footer_details.show_resolved(message)
        self._update_apply_button_state()

    def _set_searching_state(self, message: str) -> None:
        self._resolved_parent = None
        self.work_item_footer_details.show_searching(message)
        self._update_apply_button_state()

    def _set_not_found_state(self, message: str) -> None:
        self._resolved_parent = None
        self.work_item_footer_details.show_not_found(message)
        self._update_apply_button_state()

    def _reset_validation_message(self) -> None:
        self._resolved_parent = None
        current_parent_key = self._current_parent_key
        if current_parent_key:
            self.work_item_footer_details.show_current_parent(current_parent_key)
        else:
            self.work_item_footer_details.show_prompt('Type a full work item key')
        self._update_apply_button_state()

    def _is_valid_parent_candidate(self, work_item: JiraWorkItem) -> bool:
        project = self._work_item.project
        candidate_project = work_item.project
        candidate_type = work_item.work_item_type

        if work_item.key == self._work_item.key or project is None or candidate_project is None:
            return False
        if candidate_project.key != project.key or candidate_type is None or not candidate_type.id:
            return False
        return candidate_type.id in self._allowed_parent_type_ids

    def _validation_error_for_key(self, key: str) -> str | None:
        normalized_key = key.strip().upper()
        if normalized_key == self._work_item.key:
            return 'A work item cannot be its own parent'
        if normalized_key == self._current_parent_key:
            return None
        return None

    async def _fetch_exact_parent_candidate(self, query: str) -> JiraWorkItem | None:
        normalized_key = normalize_work_item_key(query)
        if normalized_key is None:
            return None

        app = cast('JiraApp', self.app)
        response = await app.api.get_work_item(
            work_item_id_or_key=normalized_key,
            fields=['id', 'key', 'summary', 'issuetype', 'project'],
        )
        if (
            not response.success
            or not response.result
            or not response.result.work_items
            or not self._is_valid_parent_candidate(response.result.work_items[0])
        ):
            return None
        return response.result.work_items[0]

    async def _ensure_parent_types_loaded(self) -> bool:
        if self._parent_types_loaded:
            return True

        app = cast('JiraApp', self.app)
        project = self._work_item.project
        if project is None:
            self.parent_input.placeholder = 'No parent work items available'
            return False

        project_types_response = await app.api.get_work_item_types_for_project(project.key)
        if not project_types_response.success or not project_types_response.result:
            self.parent_input.placeholder = 'Failed to load parent work items'
            self.notify(
                project_types_response.error or 'Failed to load parent work items',
                severity='error',
                title='Set Parent',
            )
            return False

        allowed_parent_types = self._allowed_parent_types(project_types_response.result)
        allowed_type_ids = [item.id for item in allowed_parent_types if item.id]
        if not allowed_type_ids:
            self.parent_input.placeholder = 'No valid parent type available'
            return False

        self._allowed_parent_type_ids = set(allowed_type_ids)
        self._parent_types_loaded = True
        return True

    async def _lookup_parent_candidate(self, query: str) -> None:
        if validation_error := self._validation_error_for_key(query):
            self.call_after_refresh(lambda: self._set_not_found_state(validation_error))
            return

        if not await self._ensure_parent_types_loaded():
            self.call_after_refresh(
                lambda: self._set_not_found_state('Could not determine valid parent types')
            )
            return

        exact_match = await self._fetch_exact_parent_candidate(query)
        if exact_match is not None:
            self.call_after_refresh(lambda: self._set_resolved_parent(exact_match))
            return
        self.call_after_refresh(
            lambda: self._set_not_found_state('Issue not found or not a valid parent')
        )

    @on(Input.Changed, 'WorkItemKeyInput')
    def handle_parent_input_changed(self, event: Input.Changed) -> None:
        self._update_apply_button_state()

        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None
        if self._search_worker is not None:
            self._search_worker.cancel()
            self._search_worker = None

        query = event.value.strip()
        if not query:
            self._reset_validation_message()
            return

        normalized_query = normalize_work_item_key(query)
        if normalized_query is None:
            self._set_not_found_state('Type a full work item key like PLAT-123')
            return

        self._set_searching_state('Looking up parent work item...')
        self._search_timer = self.set_timer(
            0.1,
            lambda: setattr(
                self,
                '_search_worker',
                self.run_worker(self._lookup_parent_candidate(normalized_query), exclusive=False),
            ),
        )

    @on(Button.Pressed, '#parent-work-item-button-apply')
    def handle_apply(self) -> None:
        selected_value = self._selected_parent_key()
        if not selected_value:
            self.dismiss({'parent_key': ''})
            return
        self.dismiss({'parent_key': selected_value})

    @on(Button.Pressed, '#parent-work-item-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
