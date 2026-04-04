from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, WorkItemType
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_button import ExtendedButton
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.vim_select import VimSelect

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ParentWorkItemSelector(VimSelect):
    """Dropdown with possible parent work items."""

    def __init__(self) -> None:
        super().__init__(
            options=[],
            prompt='Loading parent work items...',
            name='parent_work_item_select',
            type_to_search=True,
            compact=True,
            allow_blank=True,
        )
        self.disabled = True


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

    @property
    def parent_select(self) -> ParentWorkItemSelector:
        return self.query_one(ParentWorkItemSelector)

    @property
    def apply_button(self) -> ExtendedButton:
        return self.query_one('#parent-work-item-button-apply', ExtendedButton)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='parent-work-item-form'):
                with Vertical():
                    parent_work_item_label = Label('Parent Work Item')
                    parent_work_item_label.add_class('field_label')
                    yield parent_work_item_label
                    yield ParentWorkItemSelector()

            with Horizontal(id='modal_footer'):
                yield ExtendedButton(
                    'Set',
                    variant='success',
                    id='parent-work-item-button-apply',
                    disabled=True,
                    compact=True,
                )
                yield ExtendedButton(
                    'Cancel',
                    variant='error',
                    id='parent-work-item-button-cancel',
                    compact=True,
                )

        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.parent_select, 'focus')
            set_jump_mode(self.apply_button, 'click')
            set_jump_mode(self.query_one('#parent-work-item-button-cancel', Button), 'click')

        self.call_after_refresh(lambda: focus_first_available(self.parent_select))
        self.run_worker(self._load_parent_candidates(), exclusive=True)

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
    def _requires_parent(self) -> bool:
        return bool(self._work_item.work_item_type and self._work_item.work_item_type.subtask)

    @property
    def _current_parent_key(self) -> str:
        return self._work_item.parent_key.strip()

    def _selected_parent_key(self) -> str:
        selected_value = self.parent_select.selection
        if selected_value is None:
            return ''
        return str(selected_value).strip()

    def _update_apply_button_state(self) -> None:
        selected_parent_key = self._selected_parent_key()
        if self._requires_parent and not selected_parent_key:
            self.apply_button.disabled = True
            return

        self.apply_button.disabled = selected_parent_key == self._current_parent_key

    def _format_work_item_option(self, work_item: JiraWorkItem) -> tuple[Text, str]:
        work_item_type = work_item.work_item_type.name if work_item.work_item_type else 'Work Item'
        summary = work_item.cleaned_summary(80)
        label = Text(f'[{work_item_type}] {work_item.key} - {summary}')
        return (label, work_item.key)

    def _apply_parent_candidates(
        self,
        options: list[tuple[Text, str]],
        current_parent_key: str,
    ) -> None:
        self.parent_select.set_options(options)
        self.parent_select.prompt = 'No parent'
        self.parent_select.disabled = False

        if not options:
            self._update_apply_button_state()
            return

        if current_parent_key and any(value == current_parent_key for _, value in options):
            self.parent_select.value = current_parent_key
        else:
            self.parent_select.clear()

        self._update_apply_button_state()

        self.call_after_refresh(lambda: focus_first_available(self.parent_select))

    async def _load_parent_candidates(self) -> None:
        app = cast('JiraApp', self.app)
        self.apply_button.disabled = True
        project = self._work_item.project
        if project is None:
            self.parent_select.prompt = 'No parent work items available'
            return

        project_types_response = await app.api.get_work_item_types_for_project(project.key)
        if not project_types_response.success or not project_types_response.result:
            self.parent_select.prompt = 'Failed to load parent work items'
            self.notify(
                project_types_response.error or 'Failed to load parent work items',
                severity='error',
                title='Set Parent',
            )
            return

        allowed_parent_types = self._allowed_parent_types(project_types_response.result)
        if not allowed_parent_types:
            self.parent_select.prompt = 'No valid parent type available'
            return

        allowed_type_ids = [item.id for item in allowed_parent_types if item.id]
        if not allowed_type_ids:
            self.parent_select.prompt = 'No valid parent type available'
            return

        type_filter = ', '.join(allowed_type_ids)
        jql_query = (
            f'issuetype in ({type_filter}) and key != {self._work_item.key} order by updated DESC'
        )

        work_items_response = await app.api.search_work_items(
            project_key=project.key,
            jql_query=jql_query,
            limit=100,
            fields=['id', 'key', 'summary', 'issuetype'],
        )
        if not work_items_response.success or not work_items_response.result:
            self.parent_select.prompt = 'Failed to load parent work items'
            self.notify(
                work_items_response.error or 'Failed to load parent work items',
                severity='error',
                title='Set Parent',
            )
            return

        work_items = list(work_items_response.result.work_items)
        current_parent_key = self._work_item.parent_key.strip()
        if current_parent_key and not any(item.key == current_parent_key for item in work_items):
            current_parent_response = await app.api.get_work_item(
                work_item_id_or_key=current_parent_key,
                fields=['summary', 'issuetype'],
            )
            if (
                current_parent_response.success
                and current_parent_response.result
                and current_parent_response.result.work_items
            ):
                work_items.insert(0, current_parent_response.result.work_items[0])

        options = [self._format_work_item_option(item) for item in work_items]
        self.call_after_refresh(lambda: self._apply_parent_candidates(options, current_parent_key))

    @on(Select.Changed, 'ParentWorkItemSelector')
    def handle_parent_selected(self) -> None:
        self._update_apply_button_state()

    @on(Button.Pressed, '#parent-work-item-button-apply')
    def handle_apply(self) -> None:
        selected_value = self.parent_select.selection
        if selected_value is None:
            self.dismiss({'parent_key': ''})
            return
        self.dismiss({'parent_key': str(selected_value)})

    @on(Button.Pressed, '#parent-work-item-button-cancel')
    def handle_cancel(self) -> None:
        self.dismiss()
