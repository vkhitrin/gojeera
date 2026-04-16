from typing import TYPE_CHECKING, cast
import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.models import JiraWorkItem, JiraWorkItemGenericFields, RelatedJiraWorkItem
from gojeera.utils.urls import build_external_url_for_work_item
from gojeera.utils.work_item_reference import resolve_work_item_reference
from gojeera.widgets.extended_data_table import ExtendedDataTable

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class RelatedWorkItemsDataTable(ExtendedDataTable):
    BINDINGS = [
        Binding(
            key='ctrl+n',
            action='new_related_work_item',
            description='New related item',
            tooltip='Create a new relationship from the loaded work item',
            priority=True,
        ),
        *ExtendedDataTable.BINDINGS,
    ]

    def action_new_related_work_item(self) -> None:
        current = self.parent
        while current is not None:
            if isinstance(current, RelatedWorkItemsWidget):
                current.run_worker(current.action_link_work_item())
                return
            current = current.parent


class RelatedWorkItemsWidget(VerticalScroll, can_focus=False):
    """A container for displaying the work items related to a work item."""

    DEFAULT_CSS = """
    RelatedWorkItemsWidget {
        width: 100%;
        height: 1fr;
        hatch: right $success 20%;
        scrollbar-size-vertical: 1;
    }

    RelatedWorkItemsWidget > .tab-content-container {
        width: 100%;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding(
            key='ctrl+g',
            action='load_selected_work_item',
            description='Load Work Item',
            show=True,
        ),
        Binding(
            key='enter',
            action='view_selected_work_item',
            description='View Work Item',
            show=True,
        ),
        Binding(
            key='ctrl+d',
            action='unlink_work_item',
            description='Unlink',
        ),
        Binding(
            key='ctrl+o',
            action='open_work_item_browser',
            description='Open in Browser',
            show=True,
        ),
    ]

    work_items: Reactive[list[RelatedJiraWorkItem] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(id='related_work_items')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#related-work-items'

    @property
    def work_item_key(self) -> str | None:
        return self._work_item_key

    @work_item_key.setter
    def work_item_key(self, value: str | None) -> None:
        self._work_item_key = value

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', expect_type=VerticalGroup)

    @property
    def data_table(self) -> RelatedWorkItemsDataTable:
        return self.query_one(RelatedWorkItemsDataTable)

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            table = RelatedWorkItemsDataTable(id='related-work-items-table', cursor_type='row')
            yield table

    def on_mount(self) -> None:
        table = self.data_table
        table.add_column('Key', key='key', width=12)
        table.add_column('Summary', key='summary', width=50)
        table.add_column('Link Type', key='link_type', width=20)
        table.add_column('Status', key='status', width=15)
        table.add_column('Priority', key='priority', width=12)

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading

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
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        current_work_item = (self.work_items or [])[cursor_row]
        work_item_key = current_work_item.key

        screen = cast('MainScreen', self.screen)  # noqa: F821

        worker = self.run_worker(screen.fetch_work_items(work_item_key), exclusive=True)
        await worker.wait()

        if screen.tabs and not screen.tabs.disabled:
            self.set_timer(0.01, lambda: setattr(screen.tabs, 'active', 'tab-description'))

    async def action_view_selected_work_item(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        (self.work_items or [])[cursor_row]

    async def action_open_work_item_browser(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        current_work_item = (self.work_items or [])[cursor_row]
        work_item_key = current_work_item.key

        application = cast('JiraApp', self.app)  # noqa: F821
        if url := build_external_url_for_work_item(work_item_key, application):
            webbrowser.open_new_tab(url)

    async def action_unlink_work_item(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        await self.app.push_screen(
            ConfirmationScreen('Are you sure you want to delete the link between the work_items?'),
            callback=self.handle_delete_choice,
        )

    def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            self.run_worker(self.delete_link())

    async def delete_link(self) -> None:
        table = self.data_table
        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        current_work_item = (self.work_items or [])[cursor_row]
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
        table = self.data_table

        with self.app.batch_update():
            table.clear()

            if not items:
                self.is_loading = False
                table.display = False
                self.displayed_count = 0
                return

            table.display = True

            work_item: RelatedJiraWorkItem
            for work_item in items:
                table.add_row(
                    Text(work_item.key),
                    Text(work_item.cleaned_summary()),
                    Text(work_item.link_type),
                    Text(work_item.display_status()),
                    Text(work_item.priority_name or '-'),
                    key=work_item.id,
                )

            self.is_loading = False
            self.displayed_count = len(items)
