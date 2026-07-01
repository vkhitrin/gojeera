from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.reactive import Reactive, reactive
from textual.worker import Worker

from gojeera.components.tabs.record_list_tab import RecordListTabWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraRepositoryPullRequest
from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.widgets.layout.record_list import Record, RecordList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemDevelopmentWidget(RecordListTabWidget):
    """A container for displaying development details associated with a work item."""

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)
    pull_requests: Reactive[list[JiraRepositoryPullRequest] | None] = reactive(
        None, always_update=True
    )
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    BINDINGS = [
        Binding('ctrl+o', 'open_remote_link', 'Open Remote Link', show=True),
    ]

    def __init__(self):
        super().__init__(
            widget_id='work-item-development',
            record_list_id='work-item-development-list',
        )
        self._loaded_work_item_key: str | None = None
        self._loading_worker: Worker | None = None

    @property
    def help_anchor(self) -> str:
        return '#development'

    @property
    def has_records(self) -> bool:
        return bool(self.pull_requests)

    def load_if_needed(self) -> None:
        work_item = self.work_item
        if work_item is None or self._loaded_work_item_key == work_item.key:
            return
        if self._loading_worker is not None and not self._loading_worker.is_finished:
            return

        self.show_loading()
        self._loading_worker = self.run_worker(
            self._fetch_pull_requests(work_item),
            exclusive=True,
            group='work-item-development',
        )

    def cancel_loading(self) -> None:
        if self._loading_worker is not None and not self._loading_worker.is_finished:
            self._loading_worker.cancel()
        self._loading_worker = None
        self.hide_loading()

    async def _fetch_pull_requests(self, work_item: JiraWorkItem) -> None:
        app = cast('JiraApp', self.app)
        project_key = work_item.project.key if work_item.project else None
        response: APIControllerResponse = await app.api.get_work_item_development_pull_requests(
            work_item.key,
            work_item_id=work_item.id,
            project_key=project_key,
        )
        if self.work_item is not work_item:
            return

        if not response.success:
            self.notify(
                response.error or 'Unable to retrieve development details.',
                severity='error',
                title=work_item.key,
            )
            self.pull_requests = None
            self.hide_loading()
            return

        self._loaded_work_item_key = work_item.key
        self.pull_requests = cast(list[JiraRepositoryPullRequest], response.result or [])
        self.hide_loading()

    def _selected_pull_request(self) -> JiraRepositoryPullRequest | None:
        return self.selected_payload_as(JiraRepositoryPullRequest)

    def action_open_remote_link(self) -> None:
        pull_request = self._selected_pull_request()
        if pull_request is None:
            return
        if not pull_request.url:
            self.notify(
                'Selected development item does not have a remote link', title='Development'
            )
            return

        self.app.open_url(pull_request.url)

    @on(RecordList.RowInvoked)
    def selected(self, event: RecordList.RowInvoked) -> None:
        if event.control is self.record_list:
            self.action_open_remote_link()

    def watch_pull_requests(self, pull_requests: list[JiraRepositoryPullRequest] | None) -> None:
        def build_record(pull_request: JiraRepositoryPullRequest) -> Record:
            repository = (
                pull_request.repository_name
                or pull_request.repository_id
                or pull_request.provider_name
                or pull_request.provider_id
                or ''
            )
            branches = ' -> '.join(
                part
                for part in (pull_request.source_branch, pull_request.destination_branch)
                if part
            )
            footer = ' | '.join(
                part
                for part in (
                    repository,
                    pull_request.repository_url or None,
                    branches,
                    pull_request.url or '',
                )
                if part
            )
            meta = ' | '.join(
                part
                for part in (
                    'Pull Request',
                    pull_request.status or None,
                    pull_request.last_updated or None,
                )
                if part
            )
            return Record(
                key=pull_request.id,
                meta=meta,
                title=pull_request.title,
                footer=footer,
                payload=pull_request,
            )

        self.displayed_count = self.update_records_from_items(pull_requests, build_record)

    def watch_work_item(self, work_item: JiraWorkItem | None = None) -> None:
        self.cancel_loading()
        self._loaded_work_item_key = None
        self.pull_requests = None

        if work_item is None:
            self.displayed_count = 0
            return

        app = cast('JiraApp', self.app)
        if app.tabs.active == 'tab-development':
            self.load_if_needed()
