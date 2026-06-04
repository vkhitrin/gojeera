import asyncio
from typing import TYPE_CHECKING, cast

from textual.reactive import Reactive, reactive
from textual.worker import Worker

from gojeera.components.tabs.record_list_tab import RecordListTabWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.work_items import PaginatedWorkItemHistory, WorkItemHistoryEntry
from gojeera.widgets.layout.record_list import Record

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemHistoryWidget(RecordListTabWidget):
    """A container for displaying changelog history for a work item."""

    PAGE_SIZE = 100
    MAX_PAGES = 100

    work_item_key: Reactive[str | None] = reactive(None, always_update=True)
    history: Reactive[list[WorkItemHistoryEntry] | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(widget_id='work_item_history', record_list_id='history-list')
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
        return bool(self.history)

    def load_if_needed(self) -> None:
        if not self.work_item_key or self._loaded_work_item_key == self.work_item_key:
            return
        if self._loading_worker is not None and not self._loading_worker.is_finished:
            return

        self.show_loading()
        self._loading_worker = self.run_worker(
            self.fetch_history(self.work_item_key), exclusive=True
        )

    def cancel_loading(self) -> None:
        if self._loading_worker is not None and not self._loading_worker.is_finished:
            self._loading_worker.cancel()
        self._loading_worker = None
        self.hide_loading()

    def _mark_loaded(self, work_item_key: str) -> None:
        self._loaded_work_item_key = work_item_key
        self._partial_work_item_key = None
        self._next_offset = 0
        self._pages_loaded = 0

    async def fetch_history(self, work_item_key: str) -> None:
        screen = cast('JiraApp', self.app)
        if self._partial_work_item_key != work_item_key:
            self._partial_work_item_key = work_item_key
            self._history_entries = []
            self._next_offset = 0
            self._pages_loaded = 0

        try:
            while self._pages_loaded < self.MAX_PAGES:
                response: APIControllerResponse = await screen.api.get_work_item_history(
                    work_item_key,
                    offset=self._next_offset,
                    limit=self.PAGE_SIZE,
                )
                if not response.success or not isinstance(
                    response.result, PaginatedWorkItemHistory
                ):
                    self.notify(
                        'Unable to retrieve the history associated to the work item.',
                        severity='warning',
                        title=work_item_key,
                    )
                    self.hide_loading()
                    return

                if self.work_item_key != work_item_key:
                    return

                page = response.result
                self._history_entries.extend(page.entries)
                self._pages_loaded += 1
                self.history = sorted(
                    self._history_entries,
                    key=lambda item: item.created_on,
                    reverse=True,
                )

                if page.is_last or not page.entries:
                    self._mark_loaded(work_item_key)
                    return

                self._next_offset = page.start_at + len(page.entries)

            self._mark_loaded(work_item_key)
            self.notify(
                'Stopped loading history after the pagination safety limit.',
                severity='warning',
                title=work_item_key,
            )
        except asyncio.CancelledError:
            raise
        finally:
            self.hide_loading()

    def watch_history(self, history: list[WorkItemHistoryEntry] | None) -> None:
        with self.app.batch_update():
            if not history:
                self.record_list.clear_records()
                self.hide_loading()
                self.displayed_count = 0
                return

            records: list[Record] = []
            for item in history:
                changes = item.changes or []
                first_change = changes[0] if changes else None
                if first_change is None:
                    title = 'Work item updated'
                    footer = ''
                elif len(changes) == 1:
                    title = first_change.sentence()
                    footer = ''
                else:
                    title = f'{first_change.sentence()} and {len(changes) - 1} more'
                    footer = '; '.join(change.sentence() for change in changes[1:4])
                    if len(changes) > 4:
                        footer = f'{footer}; +{len(changes) - 4} more'

                records.append(
                    Record(
                        key=item.id,
                        meta=' by '.join(
                            part for part in (item.created_on, item.display_author) if part
                        ),
                        title=title,
                        footer=footer,
                        payload=item,
                    )
                )

            self.record_list.set_records(records)
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
