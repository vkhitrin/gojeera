from typing import TYPE_CHECKING, cast
import webbrowser

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.models import JiraWorkItem, JiraWorkItemGenericFields, RelatedJiraWorkItem
from gojeera.utils.urls import build_external_url_for_work_item
from gojeera.widgets.extended_data_table import ExtendedDataTable

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class RelatedWorkItemsWidget(VerticalScroll, can_focus=False):
    """A container for displaying the work items related to a work item."""

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
            key='d',
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
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', expect_type=Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', expect_type=VerticalGroup)

    @property
    def data_table(self) -> ExtendedDataTable:
        return self.query_one(ExtendedDataTable)

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            table = ExtendedDataTable(id='related-work-items-table', cursor_type='row')
            yield table

    def on_mount(self) -> None:
        table = self.data_table
        table.add_column('Link Type', key='link_type', width=20)
        table.add_column('Key', key='key', width=12)
        table.add_column('Status', key='status', width=15)
        table.add_column('Priority', key='priority', width=12)
        table.add_column('Summary', key='summary', width=50)

    def show_loading(self) -> None:
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        self.loading_container.display = False
        self.content_container.display = True

    def add_relationship(self, data: dict | None = None) -> None:
        if data:
            self.run_worker(self.link_work_items(data))

    async def action_link_work_item(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(
                AddWorkItemRelationshipScreen(self.work_item_key), callback=self.add_relationship
            )
        else:
            self.notify(
                'Select a work item before attempting to add a link.',
                severity='warning',
                title='Related Work Items',
            )

    async def link_work_items(self, data: dict) -> None:
        # Validate required fields
        if not self.work_item_key:
            self.notify('Work item key is missing', severity='error')
            return

        right_work_item_key = data.get('right_work_item_key')
        link_type = data.get('link_type')
        link_type_id = data.get('link_type_id')

        if not right_work_item_key or not isinstance(right_work_item_key, str):
            self.notify('Missing or invalid work item key', severity='error')
            return
        if not link_type or not isinstance(link_type, str):
            self.notify('Missing or invalid link type', severity='error')
            return
        if not link_type_id or not isinstance(link_type_id, str):
            self.notify('Missing or invalid link type ID', severity='error')
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
            self.notify('Work items linked successfully', title=self.work_item_key)

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
            self.set_timer(0.01, lambda: setattr(screen.tabs, 'active', 'tab-summary'))

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
            webbrowser.open(url)

    async def action_unlink_work_item(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            self.notify(
                'Select a row before attempting to unlink.',
                severity='error',
                title='Related Work Items',
            )
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
            else:
                self.notify(
                    'Link between work items deleted successfully',
                    title=self.work_item_key,
                )

            self.work_items = [i for i in self.work_items or [] if i.id != link_id]

    def watch_work_items(self, items: list[RelatedJiraWorkItem] | None) -> None:
        table = self.data_table

        with self.app.batch_update():
            table.clear()

            if not items:
                self.loading_container.display = False
                self.content_container.display = True
                table.display = False
                self.displayed_count = 0
                return

            table.display = True

            work_item: RelatedJiraWorkItem
            for work_item in items:
                table.add_row(
                    Text(work_item.link_type),
                    Text(work_item.key),
                    Text(work_item.display_status()),
                    Text(work_item.priority_name or '-'),
                    Text(work_item.cleaned_summary()),
                    key=work_item.id,
                )

            self.loading_container.display = False
            self.content_container.display = True
            self.displayed_count = len(items)
