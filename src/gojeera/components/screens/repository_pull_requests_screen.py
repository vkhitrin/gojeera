from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on as textual_on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.timer import Timer
from textual.widgets import Input, Static

from gojeera.internal.models.jira import JiraProjectRepository, JiraRepositoryPullRequest
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.ui.focus import focus_first_available
from gojeera.utils.ui.runtime import DebouncedFilterMixin
from gojeera.widgets.inputs.extended_input import ExtendedInput as PullRequestFilterInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.extended_table import ExtendedTable as PullRequestTable
from gojeera.widgets.layout.modal_components import build_incremental_loading_label
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.extended_jumper import set_jump_mode

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class RepositoryPullRequestsScreen(DebouncedFilterMixin, ExtendedModalScreen[None]):
    """Modal screen displaying pull requests associated with a repository."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+g', 'go_to_work_item', 'Go to work item'),
        Binding('ctrl+o', 'open_pull_request_in_browser', 'Open in browser'),
    ]
    TITLE = 'Repository Pull Requests'
    FILTER_RENDER_DELAY_SECONDS = 0.075

    def __init__(self, project_key: str, repository: JiraProjectRepository) -> None:
        super().__init__()
        self.project_key = project_key
        self.repository = repository
        self._loaded_pull_requests: list[JiraRepositoryPullRequest] = []
        self._rendered_pull_requests: list[JiraRepositoryPullRequest] = []
        self._pull_request_ids: set[str] = set()
        self._filter_render_timer: Timer | None = None

    @property
    def table(self) -> PullRequestTable:
        return self.query_one('#repository-pull-requests-table', PullRequestTable)

    @property
    def pull_requests_scroll(self) -> VerticalScroll:
        return self.query_one('#repository-pull-requests-scroll', VerticalScroll)

    @property
    def text_filter(self) -> Input:
        return self.query_one('#repository-pull-request-text-filter', Input)

    @property
    def loading_label(self) -> Static:
        return self.query_one('#repository-pull-requests-loading', Static)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(
                f'Recent Pull Requests - {self.project_key} - {self.repository.name}',
                id='modal_title',
            )
            with Horizontal(id='repository-pull-requests-filter-row'):
                yield PullRequestFilterInput(
                    placeholder='Filter pull requests',
                    id='repository-pull-request-text-filter',
                    compact=True,
                )
            with VerticalScroll(id='repository-pull-requests-scroll'):
                yield PullRequestTable(
                    id='repository-pull-requests-table',
                    zebra_stripes=True,
                    cursor_type='row',
                )
            yield build_incremental_loading_label(
                'Loading more pull requests…', 'repository-pull-requests-loading'
            )

        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        table = self.table
        table.add_columns(
            'Title',
            'Status',
            'Work Item',
            'Source',
            'Target',
            'Author',
            'Updated',
            'URL',
        )
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.text_filter, 'focus')
            set_jump_mode(table, 'focus')
        self.call_after_refresh(lambda: focus_first_available(table))
        self.pull_requests_scroll.loading = True
        self.text_filter.disabled = True
        self.call_after_refresh(
            lambda: self.run_worker(
                self._load_pull_requests(),
                exclusive=True,
                group='repository-pull-requests',
            )
        )

    async def _load_pull_requests(self) -> None:
        app = cast('JiraApp', self.app)
        response = await app.api.get_repository_pull_requests(
            self.project_key,
            self.repository,
            on_page=self._publish_pull_request_page,
        )
        self._set_loading(False)

        if not response.success:
            app.notify(
                response.error or f'Failed to load pull requests for {self.repository.name}',
                title='Pull Requests',
                severity='error',
            )
            return

        pull_requests = cast(list[JiraRepositoryPullRequest], response.result or [])
        if [item.id for item in pull_requests] != [item.id for item in self._loaded_pull_requests]:
            self._loaded_pull_requests = pull_requests
            self._pull_request_ids = {item.id for item in pull_requests}
            self._render_pull_requests()
        else:
            self._loaded_pull_requests = pull_requests
            if self.text_filter.value.strip():
                self._render_pull_requests()
            else:
                self._rendered_pull_requests = list(pull_requests)

    def _set_loading(self, loading: bool) -> None:
        self.pull_requests_scroll.loading = loading and not self._loaded_pull_requests
        self.text_filter.disabled = loading
        self.loading_label.display = loading and bool(self._loaded_pull_requests)

    async def _publish_pull_request_page(
        self,
        pull_requests: list[JiraRepositoryPullRequest],
    ) -> None:
        if not self.is_current:
            return

        new_pull_requests = [
            pull_request
            for pull_request in pull_requests
            if pull_request.id not in self._pull_request_ids
        ]
        self._pull_request_ids.update(item.id for item in new_pull_requests)
        self._loaded_pull_requests.extend(new_pull_requests)
        self.pull_requests_scroll.loading = False
        self.text_filter.disabled = False
        self.loading_label.display = True

        if not new_pull_requests:
            return
        if self.text_filter.value.strip():
            self._render_pull_requests()
            return

        self._rendered_pull_requests.extend(new_pull_requests)
        with self.app.batch_update():
            self.table.add_rows(
                self._row_for_pull_request(pull_request) for pull_request in new_pull_requests
            )

    @staticmethod
    def _row_for_pull_request(pull_request: JiraRepositoryPullRequest) -> tuple[str, ...]:
        return (
            pull_request.title,
            pull_request.status or '',
            pull_request.work_item_key,
            pull_request.source_branch or '',
            pull_request.destination_branch or '',
            pull_request.author or '',
            pull_request.last_updated or '',
            pull_request.url or '',
        )

    def _render_pull_requests(self) -> None:
        self._filter_render_timer = None
        table = self.table

        pull_requests = self._filtered_loaded_pull_requests()
        self._rendered_pull_requests = pull_requests
        table.replace_rows(
            self._row_for_pull_request(pull_request) for pull_request in pull_requests
        )

    def _schedule_filter_render(self) -> None:
        self._schedule_filter_callback(self._render_pull_requests)

    def _filtered_loaded_pull_requests(self) -> list[JiraRepositoryPullRequest]:
        query = self.text_filter.value.strip().casefold()
        if not query:
            return self._loaded_pull_requests

        return [
            pull_request
            for pull_request in self._loaded_pull_requests
            if self._pull_request_matches_text_filter(pull_request, query)
        ]

    @staticmethod
    def _pull_request_matches_text_filter(
        pull_request: JiraRepositoryPullRequest,
        query: str,
    ) -> bool:
        values = (
            pull_request.title,
            pull_request.status or '',
            pull_request.work_item_key,
            pull_request.work_item_id,
            pull_request.source_branch or '',
            pull_request.destination_branch or '',
            pull_request.author or '',
            pull_request.url or '',
        )
        return any(query in value.casefold() for value in values)

    @textual_on(Input.Changed, '#repository-pull-request-text-filter')
    def _on_text_filter_changed(self) -> None:
        self._schedule_filter_render()

    def _selected_pull_request(self) -> JiraRepositoryPullRequest | None:
        table = self.table
        if table.row_count == 0:
            return None

        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._rendered_pull_requests):
            return None
        return self._rendered_pull_requests[cursor_row]

    def action_open_pull_request_in_browser(self) -> None:
        pull_request = self._selected_pull_request()
        if pull_request is None:
            return
        if not pull_request.url:
            self.notify('Selected pull request does not have a URL', title='Pull Requests')
            return

        self.notify('Opening pull request in the browser...', title=pull_request.title)
        self.app.open_url(pull_request.url)

    def _dismiss_modal_stack(self) -> None:
        app = cast('JiraApp', self.app)
        while len(app.screen_stack) > 1 and isinstance(app.screen, ExtendedModalScreen):
            app.pop_screen()

    async def action_go_to_work_item(self) -> None:
        pull_request = self._selected_pull_request()
        if pull_request is None:
            return

        work_item_key = pull_request.work_item_key or pull_request.work_item_id
        if not work_item_key:
            self.notify(
                'Selected pull request does not have a correlated work item',
                title='Pull Requests',
            )
            return

        app = cast('JiraApp', self.app)
        self._dismiss_modal_stack()
        app.run_worker(
            app.load_work_item(work_item_key),
            exclusive=True,
            group='work-item',
        )
