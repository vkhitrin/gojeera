from typing import TYPE_CHECKING, cast

from textual.reactive import Reactive, reactive
from textual.worker import Worker

from gojeera.components.tabs.table_tab import TableTabWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.work_items import PaginatedWorkItemHistory, WorkItemHistoryEntry
from gojeera.utils.ui.runtime import cancel_worker, should_start_keyed_load, worker_is_running
from gojeera.widgets.layout.extended_table import TableRecord

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemHistoryWidget(TableTabWidget):
    """A container for displaying changelog history for a work item."""

    COLUMNS = ('Created', 'Author', 'Changes')

    PAGE_SIZE = 100
    MAX_PAGES = 100

    work_item_key: Reactive[str | None] = reactive(None, always_update=True)
    history: Reactive[list[WorkItemHistoryEntry] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(widget_id='work_item_history', table_id='history-list')
        self._loaded_work_item_key: str | None = None
        self._loading_worker: Worker | None = None
        self._partial_work_item_key: str | None = None
        self._history_entries: list[WorkItemHistoryEntry] = []
        self._next_offset = 0
        self._pages_loaded = 0

    @property
    def help_anchor(self) -> str:
        return '#history'

    @property
    def has_records(self) -> bool:
        return bool(self._history_entries)

    def load_if_needed(self) -> None:
        if not should_start_keyed_load(
            self.work_item_key,
            self._loaded_work_item_key,
            self._loading_worker,
        ):
            return

        self.show_loading()
        self._start_next_page_load()

    def _start_next_page_load(self) -> None:
        if not self.work_item_key or self._loaded_work_item_key == self.work_item_key:
            return
        if worker_is_running(self._loading_worker):
            return
        self._loading_worker = self.run_worker(
            self.fetch_history(self.work_item_key), exclusive=True
        )

    def on_extended_table_near_end(self, event) -> None:
        if event.control is not self.table:
            return
        self._start_next_page_load()

    def _load_next_page_if_viewport_needs_it(self) -> None:
        if self._loaded_work_item_key == self.work_item_key:
            return
        viewport_height = max(1, self.table.scrollable_content_region.height)
        if self.table.max_scroll_y - self.table.scroll_y <= viewport_height:
            self._start_next_page_load()

    def cancel_loading(self) -> None:
        cancel_worker(self._loading_worker)
        self._loading_worker = None
        self.hide_loading()

    def _mark_loaded(self, work_item_key: str) -> None:
        self._loaded_work_item_key = work_item_key
        self._partial_work_item_key = None
        self._next_offset = 0
        self._pages_loaded = 0
        app = cast('JiraApp', self.app)
        app.mark_detail_tab_count_loaded('tab-history', len(self._history_entries))

    def _publish_history(self) -> None:
        sorted_history = sorted(
            self._history_entries,
            key=lambda item: item.created_on,
            reverse=True,
        )
        self.displayed_count = len(sorted_history)
        if [item.id for item in sorted_history] == [item.id for item in self._history_entries]:
            return
        self._history_entries = sorted_history
        self.history = sorted_history

    @staticmethod
    def _records_for_history(history: list[WorkItemHistoryEntry]) -> list[TableRecord]:
        return [
            TableRecord(
                key=item.id,
                cells=(
                    item.created_on,
                    item.display_author,
                    '; '.join(change.sentence() for change in item.changes or [])
                    or 'Work item updated',
                ),
                payload=item,
            )
            for item in history
        ]

    async def fetch_history(self, work_item_key: str) -> None:
        screen = cast('JiraApp', self.app)
        load_next_page = False
        if self._partial_work_item_key != work_item_key:
            self._partial_work_item_key = work_item_key
            self._history_entries = []
            self._next_offset = 0
            self._pages_loaded = 0

        try:
            response: APIControllerResponse = await screen.api.get_work_item_history(
                work_item_key,
                offset=self._next_offset,
                limit=self.PAGE_SIZE,
            )
            if not response.success or not isinstance(response.result, PaginatedWorkItemHistory):
                if self._history_entries:
                    self._publish_history()
                self.notify(
                    'Unable to retrieve the history associated to the work item.',
                    severity='warning',
                    title=work_item_key,
                )
                return

            if self.work_item_key != work_item_key:
                return

            page = response.result
            self._history_entries.extend(page.entries)
            self._pages_loaded += 1

            if self._pages_loaded == 1:
                self.history = list(self._history_entries)
            elif page.entries:
                self.table.append_records(self._records_for_history(page.entries))
                self.displayed_count = len(self._history_entries)

            if page.is_last or not page.entries:
                self._publish_history()
                self._mark_loaded(work_item_key)
                return

            self._next_offset = page.start_at + len(page.entries)
            if self._pages_loaded >= self.MAX_PAGES:
                self._publish_history()
                self._mark_loaded(work_item_key)
                self.notify(
                    'Stopped loading history after the pagination safety limit.',
                    severity='warning',
                    title=work_item_key,
                )
                return

            load_next_page = True
        finally:
            self.hide_loading()
            if load_next_page and self.is_mounted:
                self.call_after_refresh(self._load_next_page_if_viewport_needs_it)

    def watch_history(self, history: list[WorkItemHistoryEntry] | None) -> None:
        with self.app.batch_update():
            if not history:
                self.table.clear_records()
                self.hide_loading()
                self.displayed_count = 0
                return

            self.table.set_records(self._records_for_history(history))
            self.hide_loading()
            self.displayed_count = len(history)

    def watch_work_item_key(self, work_item_key: str | None = None) -> None:
        self.cancel_loading()
        self._work_item_key = work_item_key
        self._loaded_work_item_key = None
        self._partial_work_item_key = None
        self._history_entries = []
        self._next_offset = 0
        self._pages_loaded = 0
        self.history = None

        if not work_item_key:
            self.is_loading = False
            self.displayed_count = 0
