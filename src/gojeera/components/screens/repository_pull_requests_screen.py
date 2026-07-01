from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Static

from gojeera.internal.models.jira import JiraProjectRepository, JiraRepositoryPullRequest
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.extended_table import ExtendedTable
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.extended_jumper import set_jump_mode

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class RepositoryPullRequestsScreen(ExtendedModalScreen[None]):
    """Modal screen displaying pull requests associated with a repository."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+g', 'go_to_work_item', 'Go to work item'),
        Binding('ctrl+o', 'open_pull_request_in_browser', 'Open in browser'),
    ]
    TITLE = 'Repository Pull Requests'

    def __init__(self, project_key: str, repository: JiraProjectRepository) -> None:
        super().__init__()
        self.project_key = project_key
        self.repository = repository
        self._loaded_pull_requests: list[JiraRepositoryPullRequest] = []
        self._rendered_pull_requests: list[JiraRepositoryPullRequest] = []

    @property
    def table(self) -> ExtendedTable:
        return self.query_one('#repository-pull-requests-table', ExtendedTable)

    @property
    def pull_requests_scroll(self) -> VerticalScroll:
        return self.query_one('#repository-pull-requests-scroll', VerticalScroll)

    @property
    def text_filter(self) -> Input:
        return self.query_one('#repository-pull-request-text-filter', Input)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(
                f'Recent Pull Requests - {self.project_key} - {self.repository.name}',
                id='modal_title',
            )
            with Horizontal(id='repository-pull-requests-filter-row'):
                yield ExtendedInput(
                    placeholder='Filter pull requests',
                    id='repository-pull-request-text-filter',
                    compact=True,
                )
            with VerticalScroll(id='repository-pull-requests-scroll'):
                yield ExtendedTable(
                    id='repository-pull-requests-table',
                    zebra_stripes=True,
                    cursor_type='row',
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
        response = await app.api.get_repository_pull_requests(self.project_key, self.repository)
        self._set_loading(False)

        if not response.success:
            app.notify(
                response.error or f'Failed to load pull requests for {self.repository.name}',
                title='Pull Requests',
                severity='error',
            )
            return

        self._loaded_pull_requests = cast(list[JiraRepositoryPullRequest], response.result or [])
        self._render_pull_requests()

    def _set_loading(self, loading: bool) -> None:
        self.pull_requests_scroll.loading = loading
        self.text_filter.disabled = loading

    def _render_pull_requests(self) -> None:
        table = self.table
        table.clear()

        pull_requests = self._filtered_loaded_pull_requests()
        self._rendered_pull_requests = pull_requests

        for pull_request in pull_requests:
            table.add_row(
                pull_request.title,
                pull_request.status or '',
                pull_request.work_item_key,
                pull_request.source_branch or '',
                pull_request.destination_branch or '',
                pull_request.author or '',
                pull_request.last_updated or '',
                pull_request.url or '',
            )

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

    @on(Input.Changed, '#repository-pull-request-text-filter')
    def _on_text_filter_changed(self) -> None:
        self._render_pull_requests()

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
