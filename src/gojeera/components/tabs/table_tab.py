from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypeVar, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalGroup
from textual.widgets import DataTable

from gojeera.utils.jira.urls import build_external_url_for_work_item
from gojeera.widgets.layout.extended_table import ExtendedTable, TableRecord

__all__ = ['WORK_ITEM_NAVIGATION_BINDINGS', 'TableTabWidget']

T = TypeVar('T')

if TYPE_CHECKING:
    from gojeera.app import JiraApp


WORK_ITEM_NAVIGATION_BINDINGS = (
    Binding('enter', 'view_selected_work_item', 'View Work Item', show=True),
    Binding('ctrl+o', 'open_work_item_browser', 'Open in Browser', show=True),
)


class TableTabWidget(Vertical, can_focus=False):
    """Shared shell for tab panels backed by an ExtendedTable."""

    DEFAULT_CSS = """
    TableTabWidget {
        width: 100%;
        height: 1fr;
        background: transparent;
    }

    TableTabWidget > .tab-content-container {
        width: 100%;
        height: 1fr;
    }

    TableTabWidget ExtendedTable {
        width: 100%;
        height: 1fr;
        background: transparent;
    }
    """

    COLUMNS: tuple[str, ...] = ()

    def __init__(self, *, widget_id: str, table_id: str) -> None:
        super().__init__(id=widget_id)
        self._table_id = table_id
        self._work_item_key: str | None = None

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def table(self) -> ExtendedTable:
        return self.query_one(ExtendedTable)

    @property
    def has_records(self) -> bool:
        raise NotImplementedError

    async def action_load_selected_work_item(self) -> None:
        raise NotImplementedError

    @property
    def work_item_key(self) -> str | None:
        return self._work_item_key

    @work_item_key.setter
    def work_item_key(self, value: str | None) -> None:
        self._work_item_key = value

    def compose(self) -> ComposeResult:
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield ExtendedTable(
                id=self._table_id,
                columns=self.COLUMNS,
                disable_empty=True,
                cursor_type='row',
                zebra_stripes=True,
                classes='tab-scroll-surface tab-scroll-surface--persistent',
            )

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def update_records_from_items(
        self,
        items: Sequence[T] | None,
        build_record: Callable[[T], TableRecord],
    ) -> int:
        with self.app.batch_update():
            records = [build_record(item) for item in items or []]
            self.table.set_records(records)
            displayed_count = len(records)
            self.is_loading = False
            return displayed_count

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading and not self.has_records

    def selected_payload_as(self, payload_type: type[T]) -> T | None:
        selected = self.table.selected_payload
        return selected if isinstance(selected, payload_type) else None

    async def _load_work_item_and_activate_tab(
        self, work_item_key: str, *, defer_tab_activation: bool = False
    ) -> None:
        screen = cast('JiraApp', self.app)
        focused = screen.focused
        restore_content_focus = focused is not None and (
            focused is self or focused in self.walk_children()
        )
        await screen.load_work_item(work_item_key)

        if screen.tabs and not screen.tabs.disabled:

            def activate_tab() -> None:
                if restore_content_focus:
                    screen.tabs.activate_from_content('tab-description')
                else:
                    screen.tabs.active = 'tab-description'

            if defer_tab_activation:
                self.set_timer(0.01, activate_tab)
            else:
                activate_tab()

    def load_work_item(self, work_item_key: str, *, defer_tab_activation: bool = False) -> None:
        self.run_worker(
            self._load_work_item_and_activate_tab(
                work_item_key,
                defer_tab_activation=defer_tab_activation,
            ),
            exclusive=True,
            group='work-item',
        )

    def open_work_item_in_browser(self, work_item_key: str) -> None:
        application = cast('JiraApp', self.app)
        if url := build_external_url_for_work_item(work_item_key, application):
            import webbrowser

            webbrowser.open_new_tab(url)

    def handle_row_invoked_load(self, event: DataTable.RowSelected) -> None:
        if event.control is self.table:
            self.run_worker(self.action_load_selected_work_item())
