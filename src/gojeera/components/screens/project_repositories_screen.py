from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.timer import Timer
from textual.widgets import Input, Static

from gojeera.internal.models.jira import JiraProjectRepository
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.ui.focus import focus_first_available
from gojeera.utils.ui.runtime import DebouncedFilterMixin
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.extended_table import ExtendedTable as RepositoryTable
from gojeera.widgets.layout.modal_components import build_incremental_loading_label
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.extended_jumper import set_jump_mode

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ProjectRepositoriesScreen(DebouncedFilterMixin, ExtendedModalScreen[None]):
    """Modal screen displaying repositories associated with a Jira project."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+o', 'open_repository_in_browser', 'Open in browser'),
        Binding('ctrl+g', 'view_repository_pull_requests', 'View pull requests'),
    ]
    TITLE = 'Project Repositories'
    FILTER_RENDER_DELAY_SECONDS = 0.075

    def __init__(self, project_key: str) -> None:
        super().__init__()
        self.project_key = project_key
        self._loaded_repositories: list[JiraProjectRepository] = []
        self._rendered_repositories: list[JiraProjectRepository] = []
        self._filter_render_timer: Timer | None = None

    @property
    def table(self) -> RepositoryTable:
        return self.query_one('#project-repositories-table', RepositoryTable)

    @property
    def repositories_scroll(self) -> VerticalScroll:
        return self.query_one('#project-repositories-scroll', VerticalScroll)

    @property
    def text_filter(self) -> Input:
        return self.query_one('#project-repository-text-filter', Input)

    @property
    def loading_label(self) -> Static:
        return self.query_one('#project-repositories-loading', Static)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(f'Repositories - {self.project_key}', id='modal_title')
            with Horizontal(id='project-repositories-filter-row'):
                yield ExtendedInput(
                    placeholder='Filter repositories',
                    id='project-repository-text-filter',
                    compact=True,
                )
            with VerticalScroll(id='project-repositories-scroll'):
                yield RepositoryTable(
                    id='project-repositories-table',
                    zebra_stripes=True,
                    cursor_type='row',
                )
            yield build_incremental_loading_label(
                'Loading more repositories…', 'project-repositories-loading'
            )

        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        table = self.table
        table.add_columns('Name', 'Provider', 'Type', 'URL', 'External ID')
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.text_filter, 'focus')
            set_jump_mode(table, 'focus')
        self.call_after_refresh(lambda: focus_first_available(table))
        self.repositories_scroll.loading = True
        self.text_filter.disabled = True
        self.call_after_refresh(
            lambda: self.run_worker(
                self._load_repositories(),
                exclusive=True,
                group='project-repositories',
            )
        )

    async def _load_repositories(self) -> None:
        app = cast('JiraApp', self.app)
        response = await app.api.get_project_repositories(
            self.project_key,
            on_page=self._publish_repository_page,
        )
        self._set_loading(False)

        if not response.success:
            app.notify(
                response.error or f'Failed to load repositories for {self.project_key}',
                severity='error',
            )
            return

        repositories = sorted(
            cast(list[JiraProjectRepository], response.result or []),
            key=lambda repository: repository.name.casefold(),
        )
        if [repository.id for repository in repositories] != [
            repository.id for repository in self._loaded_repositories
        ]:
            self._loaded_repositories = repositories
            self._render_repositories()

    def _publish_repository_page(self, repositories: list[JiraProjectRepository]) -> None:
        if self.app.screen is not self:
            return
        self._loaded_repositories = sorted(
            repositories,
            key=lambda repository: repository.name.casefold(),
        )
        self._render_repositories()
        self.repositories_scroll.loading = False
        self.text_filter.disabled = False
        self.loading_label.display = True

    def _set_loading(self, loading: bool) -> None:
        self.repositories_scroll.loading = loading
        self.text_filter.disabled = loading
        self.loading_label.display = False

    def _render_repositories(self) -> None:
        self._filter_render_timer = None
        table = self.table

        repositories = self._filtered_loaded_repositories()
        rendered_ids = [repository.id for repository in self._rendered_repositories]
        repository_ids = [repository.id for repository in repositories]
        can_append = repository_ids[: len(rendered_ids)] == rendered_ids
        if can_append:
            new_repositories = repositories[len(rendered_ids) :]
            if new_repositories:
                table.append_rows(
                    self._row_for_repository(repository) for repository in new_repositories
                )
        else:
            table.replace_rows(self._row_for_repository(repository) for repository in repositories)
        self._rendered_repositories = repositories

    @staticmethod
    def _row_for_repository(repository: JiraProjectRepository) -> tuple[str, ...]:
        return (
            repository.name,
            repository.provider_name or repository.provider_id or '',
            repository.repository_type or '',
            repository.url or '',
            repository.external_id or '',
        )

    def _schedule_filter_render(self) -> None:
        self._schedule_filter_callback(self._render_repositories)

    def _filtered_loaded_repositories(self) -> list[JiraProjectRepository]:
        query = self.text_filter.value.strip().casefold()
        if not query:
            return self._loaded_repositories

        return [
            repository
            for repository in self._loaded_repositories
            if self._repository_matches_text_filter(repository, query)
        ]

    @staticmethod
    def _repository_matches_text_filter(repository: JiraProjectRepository, query: str) -> bool:
        values = (
            repository.name,
            repository.provider_name or '',
            repository.provider_id or '',
            repository.repository_type or '',
            repository.url or '',
            repository.external_id or '',
        )
        return any(query in value.casefold() for value in values)

    @on(Input.Changed, '#project-repository-text-filter')
    def _on_text_filter_changed(self) -> None:
        self._schedule_filter_render()

    def _selected_repository(self) -> JiraProjectRepository | None:
        table = self.table
        if table.row_count == 0:
            return None

        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._rendered_repositories):
            return None
        return self._rendered_repositories[cursor_row]

    def action_open_repository_in_browser(self) -> None:
        repository = self._selected_repository()
        if repository is None:
            return
        if not repository.url:
            self.notify('Selected repository does not have a URL')
            return

        self.notify('Opening repository in the browser...', title=repository.name)
        self.app.open_url(repository.url)

    async def action_view_repository_pull_requests(self) -> None:
        repository = self._selected_repository()
        if repository is None:
            return

        from gojeera.components.screens.repository_pull_requests_screen import (
            RepositoryPullRequestsScreen,
        )

        app = cast('JiraApp', self.app)
        await app._push_screen_exclusive(RepositoryPullRequestsScreen(self.project_key, repository))
