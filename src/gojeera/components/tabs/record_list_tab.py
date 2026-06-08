from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, TypeVar, cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalGroup

from gojeera.utils.jira.urls import build_external_url_for_work_item
from gojeera.widgets.layout.record_list import Record, RecordList, update_record_list_from_items

T = TypeVar('T')

if TYPE_CHECKING:
    from gojeera.app import JiraApp


WORK_ITEM_NAVIGATION_BINDINGS = (
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
        key='ctrl+o',
        action='open_work_item_browser',
        description='Open in Browser',
        show=True,
    ),
)


class RecordListTabWidget(Vertical, can_focus=False):
    """Shared shell for tab panels backed by a RecordList."""

    DEFAULT_CSS = """
    RecordListTabWidget {
        width: 100%;
        height: 1fr;
        background: transparent;
    }

    RecordListTabWidget > .tab-content-container {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, *, widget_id: str, record_list_id: str) -> None:
        super().__init__(id=widget_id)
        self._record_list_id = record_list_id
        self._work_item_key: str | None = None

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def record_list(self) -> RecordList:
        return self.query_one(RecordList)

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
            yield RecordList(
                widget_id=self._record_list_id,
                classes='tab-scroll-surface tab-scroll-surface--persistent',
            )

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def update_records_from_items(
        self,
        items: Sequence[T] | None,
        build_record: Callable[[T], Record],
    ) -> int:
        with self.app.batch_update():
            displayed_count = update_record_list_from_items(
                items=items,
                record_list=self.record_list,
                build_record=build_record,
            )
            self.is_loading = False
            return displayed_count

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading and not self.has_records

    def selected_payload_as(self, payload_type: type[T]) -> T | None:
        selected = self.record_list.selected_payload
        return selected if isinstance(selected, payload_type) else None

    async def _load_work_item_and_activate_tab(
        self, work_item_key: str, *, defer_tab_activation: bool = False
    ) -> None:
        screen = cast('JiraApp', self.app)
        await screen.load_work_item(work_item_key)

        if screen.tabs and not screen.tabs.disabled:
            if defer_tab_activation:
                self.set_timer(0.01, lambda: setattr(screen.tabs, 'active', 'tab-description'))
            else:
                screen.tabs.active = 'tab-description'

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

    def handle_row_invoked_load(self, event: RecordList.RowInvoked) -> None:
        if event.control is self.record_list:
            self.run_worker(self.action_load_selected_work_item())
