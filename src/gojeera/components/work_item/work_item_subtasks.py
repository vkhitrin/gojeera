from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.reactive import Reactive, reactive

from gojeera.components.screens.edit_work_item_info_screen import EditWorkItemInfoScreen
from gojeera.components.tabs.record_list_tab import (
    WORK_ITEM_NAVIGATION_BINDINGS,
    RecordListTabWidget,
)
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.widgets.layout.record_list import Record, RecordList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemChildWorkItemsWidget(RecordListTabWidget):
    work_items: Reactive[list[JiraWorkItem] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    BINDINGS = [
        *WORK_ITEM_NAVIGATION_BINDINGS,
        Binding(
            key='ctrl+b',
            action='clone_selected_work_item',
            description='Clone',
            show=True,
        ),
        Binding(
            key='ctrl+e',
            action='edit_selected_work_item_summary',
            description='Edit Summary',
            show=True,
        ),
    ]

    def __init__(self):
        super().__init__(widget_id='workitem_subtasks', record_list_id='subtasks-list')

    @property
    def help_anchor(self) -> str:
        return '#subtasks'

    @property
    def has_records(self) -> bool:
        return bool(self.work_items)

    def _selected_work_item(self) -> JiraWorkItem | None:
        return self.selected_payload_as(JiraWorkItem)

    async def action_load_selected_work_item(self) -> None:
        current_work_item = self._selected_work_item()
        if current_work_item is None:
            return

        self.load_work_item(current_work_item.key)

    async def action_view_selected_work_item(self) -> None:
        await self.action_load_selected_work_item()

    async def action_open_work_item_browser(self) -> None:
        current_work_item = self._selected_work_item()
        if current_work_item is None:
            return

        self.open_work_item_in_browser(current_work_item.key)

    @on(RecordList.RowInvoked)
    def selected(self, event: RecordList.RowInvoked) -> None:
        self.handle_row_invoked_load(event)

    def action_clone_selected_work_item(self) -> None:
        current_work_item = self._selected_work_item()
        if current_work_item is None:
            return

        screen = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
        self.run_worker(screen.clone_work_item(current_work_item.key))

    async def action_edit_selected_work_item_summary(self) -> None:
        current_work_item = self._selected_work_item()
        if current_work_item is None:
            return

        application = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]
        screen = cast('JiraApp', self.app)  # noqa: F821  # type: ignore[arg-type]

        response: APIControllerResponse = await application.api.get_work_item(current_work_item.key)
        if not response.success or not response.result or not response.result.work_items:
            self.notify(
                f'Unable to load subtask {current_work_item.key} for editing',
                severity='error',
                title='Subtasks',
            )
            return

        work_item = response.result.work_items[0]

        async def handle_updates(updates: dict | None) -> None:
            if not updates:
                return

            update_response: APIControllerResponse = await application.api.update_work_item(
                work_item=work_item,
                updates=updates,
            )

            if not update_response.success:
                self.notify(
                    f'Failed to update subtask: {update_response.error}',
                    severity='error',
                    title=work_item.key,
                )
                return

            self.notify(f'Work item {work_item.key} updated successfully', title=work_item.key)

            if self.work_item_key:
                await screen.retrieve_work_item_subtasks(self.work_item_key)

        await self.app.push_screen(
            EditWorkItemInfoScreen(work_item=work_item),
            callback=handle_updates,
        )

    def watch_work_items(self, items: list[JiraWorkItem] | None) -> None:
        def build_record(item: JiraWorkItem) -> Record:
            work_item_type_name = item.work_item_type.name if item.work_item_type else 'Unknown'
            assignee_display = ''
            if item.assignee:
                assignee_display = (
                    item.assignee.display_name or item.assignee.email or item.assignee.account_id
                )
            footer_parts = [part for part in (item.status_name, assignee_display) if part]
            return Record(
                key=item.key,
                meta=f'[{work_item_type_name}] {item.key}',
                title=item.cleaned_summary(max_length=80),
                footer=' • '.join(footer_parts),
                payload=item,
            )

        self.displayed_count = self.update_records_from_items(items, build_record)
