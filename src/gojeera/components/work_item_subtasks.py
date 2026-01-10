from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator

from gojeera.models import JiraWorkItem
from gojeera.utils.urls import build_external_url_for_work_item
from gojeera.widgets.extended_data_table import ExtendedDataTable

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemChildWorkItemsWidget(VerticalScroll, can_focus=False):
    work_items: Reactive[list[JiraWorkItem] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)

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
            key='o',
            action='open_work_item_browser',
            description='Open in Browser',
            show=True,
        ),
    ]

    def __init__(self):
        super().__init__(id='workitem_subtasks')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#subtasks'

    @property
    def work_item_key(self) -> str | None:
        return self._work_item_key

    @work_item_key.setter
    def work_item_key(self, value: str | None) -> None:
        self._work_item_key = value

    @property
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def data_table(self) -> ExtendedDataTable:
        return self.query_one(ExtendedDataTable)

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            table = ExtendedDataTable(id='subtasks-table', cursor_type='row')
            yield table

    def on_mount(self) -> None:
        table = self.data_table
        table.add_column('Key', key='key', width=12)
        table.add_column('Summary', key='summary', width=50)
        table.add_column('Type', key='type', width=15)
        table.add_column('Status', key='status', width=15)
        table.add_column('Assignee', key='assignee', width=25)

    def show_loading(self) -> None:
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        self.loading_container.display = False
        self.content_container.display = True

    async def action_load_selected_work_item(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        row_key = table.get_row_at(cursor_row)[0]
        work_item_key = str(row_key)

        screen = cast('MainScreen', self.screen)  # noqa: F821  # type: ignore[arg-type]

        worker = self.run_worker(screen.fetch_work_items(work_item_key), exclusive=True)
        await worker.wait()

        if screen.tabs and not screen.tabs.disabled:
            screen.tabs.active = 'tab-summary'

    async def action_view_selected_work_item(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        row_key = table.get_row_at(cursor_row)[0]
        str(row_key)

    async def action_open_work_item_browser(self) -> None:
        table = self.data_table
        if table.row_count == 0:
            return

        cursor_row = table.cursor_row
        if cursor_row is None or cursor_row >= len(self.work_items or []):
            return

        row_key = table.get_row_at(cursor_row)[0]
        work_item_key = str(row_key)

        if url := build_external_url_for_work_item(work_item_key, cast('JiraApp', self.app)):
            import webbrowser

            webbrowser.open(url)

    def watch_work_items(self, items: list[JiraWorkItem] | None) -> None:
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

            self.loading_container.display = False
            self.content_container.display = True

            for item in items:
                work_item_type_name = item.work_item_type.name if item.work_item_type else 'Unknown'

                assignee_display = ''
                if item.assignee:
                    assignee_display = (
                        item.assignee.display_name
                        or item.assignee.email
                        or item.assignee.account_id
                    )

                table.add_row(
                    Text(item.key),
                    Text(item.cleaned_summary(max_length=50)),
                    Text(work_item_type_name),
                    Text(item.status_name),
                    Text(assignee_display),
                    key=item.key,
                )

            self.loading_container.display = False
            self.content_container.display = True
            self.displayed_count = len(items)
