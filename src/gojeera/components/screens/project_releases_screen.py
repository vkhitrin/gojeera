from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.style import Style
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.geometry import Offset
from textual.widgets import Button, Input, SelectionList, Static

from gojeera.internal.models.jira import JiraProjectRelease
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.jira.jql import release_work_items_jql
from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.extended_table import ExtendedTable
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.selection.vim_selection_list import VimSelectionList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ProjectReleasesScreen(ExtendedModalScreen[None]):
    """Modal screen displaying Jira releases for a project."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+g', 'search_release_work_items', 'Search release work items'),
    ]
    TITLE = 'Project Releases'
    STATUS_FILTER_OPEN_ARROW = '▲'
    STATUS_FILTER_CLOSED_ARROW = '▼'
    RELEASE_STATUS_FILTER_OPTIONS = (
        ('Released', 'released', False),
        ('Unreleased', 'unreleased', True),
        ('Archived', 'archived', False),
    )

    def __init__(self, project_key: str) -> None:
        super().__init__()
        self.project_key = project_key
        self._release_cache: dict[tuple[str, ...], list[JiraProjectRelease]] = {}
        self._loaded_releases: list[JiraProjectRelease] = []
        self._rendered_releases: list[JiraProjectRelease] = []

    @property
    def table(self) -> ExtendedTable:
        return self.query_one('#project-releases-table', ExtendedTable)

    @property
    def releases_scroll(self) -> VerticalScroll:
        return self.query_one('#project-releases-scroll', VerticalScroll)

    @property
    def text_filter(self) -> Input:
        return self.query_one('#project-release-text-filter', Input)

    @property
    def status_filter(self) -> VimSelectionList:
        return self.query_one('#project-release-status-filter', VimSelectionList)

    @property
    def status_filter_button(self) -> Button:
        return self.query_one('#project-release-status-filter-button', Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(f'Releases - {self.project_key}', id='modal_title')
            with Horizontal(id='project-releases-filter-row'):
                yield ExtendedInput(
                    placeholder='Filter releases',
                    id='project-release-text-filter',
                    compact=True,
                )
                yield Button(
                    f'Unreleased {self.STATUS_FILTER_CLOSED_ARROW}',
                    id='project-release-status-filter-button',
                    compact=True,
                )
            yield VimSelectionList(
                *self.RELEASE_STATUS_FILTER_OPTIONS,
                id='project-release-status-filter',
                compact=True,
            )
            with VerticalScroll(id='project-releases-scroll'):
                yield ExtendedTable(
                    id='project-releases-table',
                    zebra_stripes=True,
                    cursor_type='row',
                )

        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        table = self.table
        table.add_columns(
            'Name',
            'Status',
            'Start',
            'Release',
            'To Do',
            'In Progress',
            'Done',
            'Unmapped',
            'Description',
        )
        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.text_filter, 'focus')
            set_jump_mode(self.status_filter_button, 'click')
            set_jump_mode(table, 'focus')
        self.call_after_refresh(lambda: focus_first_available(table))
        self.releases_scroll.loading = True
        self.text_filter.disabled = True
        self.status_filter_button.disabled = True
        self.status_filter.disabled = True
        self.status_filter.display = False
        self.call_after_refresh(
            lambda: self.run_worker(
                self._load_releases_for_selected_statuses(),
                exclusive=True,
                group='project-releases',
            )
        )

    async def _load_releases_for_selected_statuses(self) -> None:
        app = cast('JiraApp', self.app)
        status_key = self._selected_status_key()
        cached_releases = self._release_cache.get(status_key)
        if cached_releases is not None:
            self._set_loaded_releases(cached_releases)
            self._set_loading(False)
            return

        response = await app.api.get_project_releases(
            self.project_key,
            status=self._status_param(status_key),
            order_by='releaseDate',
        )
        self._set_loading(False)

        if not response.success:
            app.notify(
                response.error or f'Failed to load releases for {self.project_key}',
                title='Releases',
                severity='error',
            )
            return

        releases = self._reorder_releases(cast(list[JiraProjectRelease], response.result or []))
        self._release_cache[status_key] = releases
        self._set_loaded_releases(releases)

    def _set_loading(self, loading: bool) -> None:
        self.releases_scroll.loading = loading
        self.text_filter.disabled = loading
        self.status_filter_button.disabled = loading
        self.status_filter.disabled = loading
        if loading:
            self.status_filter.display = False
        self._sync_status_filter_button_label()

    def _set_loaded_releases(self, releases: list[JiraProjectRelease]) -> None:
        self._loaded_releases = releases
        self._render_releases()

    def _render_releases(self) -> None:
        table = self.table
        table.clear()

        releases = self._filtered_loaded_releases()
        self._rendered_releases = releases
        if not releases:
            return

        for release in self._rendered_releases:
            row_key = table.add_row(
                release.name,
                release.status,
                release.start_date or '',
                release.release_date or '',
                self._format_count(release.todo_count),
                self._format_count(release.in_progress_count),
                self._format_count(release.done_count),
                self._format_count(release.unmapped_count),
                (release.description or '').replace('\n', ' '),
            )
            if release.status == 'Overdue':
                table.set_row_style(
                    row_key,
                    Style(color=self.app.theme_variables.get('error-lighten-1', 'red')),
                )

    @staticmethod
    def _format_count(value: int | None) -> str:
        return '' if value is None else str(value)

    @staticmethod
    def _reorder_releases(
        releases: list[JiraProjectRelease],
    ) -> list[JiraProjectRelease]:
        dated_releases = [release for release in releases if release.release_date]
        undated_releases = [release for release in releases if not release.release_date]
        return [*reversed(dated_releases), *undated_releases]

    def _filtered_loaded_releases(self) -> list[JiraProjectRelease]:
        query = self.text_filter.value.strip().casefold()
        if not query:
            return self._loaded_releases

        return [
            release
            for release in self._loaded_releases
            if self._release_matches_text_filter(release, query)
        ]

    @staticmethod
    def _release_matches_text_filter(release: JiraProjectRelease, query: str) -> bool:
        fields = (
            release.name,
            release.status,
            release.start_date or '',
            release.release_date or '',
            release.description or '',
        )
        return any(query in field.casefold() for field in fields)

    def _selected_status_key(self) -> tuple[str, ...]:
        return tuple(sorted(self.status_filter.selected))

    @staticmethod
    def _status_param(status_key: tuple[str, ...]) -> str | None:
        return ','.join(status_key) if status_key else None

    def _start_releases_load(self) -> None:
        self._set_loading(True)
        self.run_worker(
            self._load_releases_for_selected_statuses(),
            exclusive=True,
            group='project-releases',
        )

    @on(SelectionList.SelectedChanged, '#project-release-status-filter')
    def handle_status_filter_changed(self) -> None:
        self._sync_status_filter_button_label()
        self._start_releases_load()

    @on(Input.Changed, '#project-release-text-filter')
    def handle_text_filter_changed(self) -> None:
        self._render_releases()

    async def action_search_release_work_items(self) -> None:
        release = self._selected_release()
        if release is None:
            return

        app = cast('JiraApp', self.app)
        self.dismiss()
        await app.action_run_recent_search(release_work_items_jql(self.project_key, release.name))

    def _selected_release(self) -> JiraProjectRelease | None:
        table = self.table
        if table.row_count == 0:
            return None

        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._rendered_releases):
            return None
        return self._rendered_releases[cursor_row]

    @on(Button.Pressed, '#project-release-status-filter-button')
    def handle_status_filter_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        status_filter = self.status_filter
        status_filter.display = not status_filter.display
        if status_filter.display:
            button_region = self.status_filter_button.region
            status_filter.absolute_offset = Offset(
                button_region.x,
                button_region.y + button_region.height,
            )
            status_filter.focus(scroll_visible=False)
        self._sync_status_filter_button_label()

    async def _on_key(self, event: events.Key) -> None:
        if event.key in {'escape', 'esc'} and self.status_filter.display:
            event.prevent_default()
            event.stop()
            self.status_filter.display = False
            self._sync_status_filter_button_label()
            self.status_filter_button.focus(scroll_visible=False)
            return
        await super()._on_key(event)

    def _sync_status_filter_button_label(self) -> None:
        selected_statuses = set(self.status_filter.selected)
        labels = {
            'released': 'Released',
            'unreleased': 'Unreleased',
            'archived': 'Archived',
        }
        if not selected_statuses or selected_statuses == set(labels):
            label = 'All statuses'
        elif len(selected_statuses) == 1:
            label = labels[next(iter(selected_statuses))]
        else:
            label = f'{len(selected_statuses)} statuses'

        arrow = (
            self.STATUS_FILTER_OPEN_ARROW
            if self.status_filter.display
            else self.STATUS_FILTER_CLOSED_ARROW
        )
        self.status_filter_button.label = f'{label} {arrow}'
