from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.reactive import Reactive, reactive

from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.components.tabs.record_list_tab import (
    WORK_ITEM_NAVIGATION_BINDINGS,
    RecordListTabWidget,
)
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraWorkItemGenericFields
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    RelatedJiraWorkItem,
)
from gojeera.utils.jira.reference import resolve_work_item_reference
from gojeera.widgets.layout.record_list import Record, RecordList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class RelatedWorkItemsWidget(RecordListTabWidget):
    """A container for displaying the work items related to a work item."""

    BINDINGS = [
        *WORK_ITEM_NAVIGATION_BINDINGS,
        Binding(
            key='ctrl+d',
            action='unlink_work_item',
            description='Unlink',
        ),
    ]

    work_items: Reactive[list[RelatedJiraWorkItem] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(
            widget_id='related_work_items',
            record_list_id='related-work-items-list',
        )

    @property
    def help_anchor(self) -> str:
        return '#related-work-items'

    @property
    def has_records(self) -> bool:
        return bool(self.work_items)

    def add_relationship(self, data: dict | None = None) -> None:
        if data:
            self.run_worker(self.link_work_items(data))

    async def action_link_work_item(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(
                AddWorkItemRelationshipScreen(self.work_item_key), callback=self.add_relationship
            )

    async def link_work_items(self, data: dict) -> None:
        # Validate required fields
        if not self.work_item_key:
            return

        right_work_item_key = data.get('right_work_item_key')
        link_type = data.get('link_type')
        link_type_id = data.get('link_type_id')

        if not right_work_item_key or not isinstance(right_work_item_key, str):
            return
        right_work_item_key = resolve_work_item_reference(right_work_item_key)
        if right_work_item_key is None:
            return
        if not link_type or not isinstance(link_type, str):
            return
        if not link_type_id or not isinstance(link_type_id, str):
            return

        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.link_work_items(
            left_work_item_key=self.work_item_key,
            right_work_item_key=right_work_item_key,
            link_type=link_type,
            link_type_id=link_type_id,
        )
        if not response.success:
            self.notify(
                f'Failed to link the work items: {response.error}',
                severity='error',
                title=self.work_item_key,
            )
        else:
            response = await application.api.get_work_item(
                self.work_item_key,
                fields=[JiraWorkItemGenericFields.WORK_ITEM_LINKS.value],
            )
            if response.success and response.result and response.result.work_items:
                work_item: JiraWorkItem = response.result.work_items[0]
                self.work_items = work_item.related_work_items or []

    async def action_load_selected_work_item(self) -> None:
        current_work_item = self.selected_payload_as(RelatedJiraWorkItem)
        if current_work_item is None:
            return

        self.load_work_item(current_work_item.key, defer_tab_activation=True)

    async def action_view_selected_work_item(self) -> None:
        await self.action_load_selected_work_item()

    async def action_open_work_item_browser(self) -> None:
        current_work_item = self.selected_payload_as(RelatedJiraWorkItem)
        if current_work_item is None:
            return

        self.open_work_item_in_browser(current_work_item.key)

    async def action_unlink_work_item(self) -> None:
        if not isinstance(self.record_list.selected_payload, RelatedJiraWorkItem):
            return

        await self.app.push_screen(
            ConfirmationScreen('Are you sure you want to delete the link between the work items?'),
            callback=self.handle_delete_choice,
        )

    def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            self.run_worker(self.delete_link())

    async def delete_link(self) -> None:
        selected = self.record_list.selected_payload
        if not isinstance(selected, RelatedJiraWorkItem):
            return
        current_work_item = selected
        link_id = current_work_item.id

        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.delete_work_item_link(link_id)
        if self.work_item_key:
            if not response.success:
                self.notify(
                    f'Failed to delete the link: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )

            self.work_items = [i for i in self.work_items or [] if i.id != link_id]

    def watch_work_items(self, items: list[RelatedJiraWorkItem] | None) -> None:
        def build_record(work_item: RelatedJiraWorkItem) -> Record:
            footer_parts = [
                part for part in (work_item.display_status(), work_item.priority_name) if part
            ]
            return Record(
                key=work_item.id,
                meta=f'{work_item.link_type} • {work_item.key}',
                title=work_item.cleaned_summary(),
                footer=' • '.join(footer_parts),
                payload=work_item,
            )

        self.displayed_count = self.update_records_from_items(items, build_record)

    @on(RecordList.RowInvoked)
    def on_row_invoked(self, event: RecordList.RowInvoked) -> None:
        self.handle_row_invoked_load(event)
