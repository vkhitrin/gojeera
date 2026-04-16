from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Button, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_log_screen import LogWorkScreen
from gojeera.config import CONFIGURATION
from gojeera.utils.focus import focus_first_available
from gojeera.utils.urls import build_external_url_for_work_item
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown
from gojeera.widgets.spacer import Spacer
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkLogListView(VerticalScroll):
    """Scrollable worklog list with vim-style navigation and card selection."""

    DEFAULT_CSS = """
    WorkLogListView {
        width: 100%;
        height: auto;
        background: $surface;
        max-height: 15;
        margin: 0 1;
        padding: 0 1 1 1;
        scrollbar-size-vertical: 1;
    }

    WorkLogListView > .worklog-empty-state {
        width: 100%;
        color: $text-muted;
        content-align: center middle;
        text-align: center;
        padding: 2 1;
    }
    """

    can_focus = True
    jump_mode: ClassVar[str | None] = 'focus'
    index = reactive(-1)

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next worklog', show=False),
        Binding('k', 'cursor_up', 'Previous worklog', show=False),
        Binding('ctrl+o', 'open_worklog_in_browser', 'Open in browser'),
        Binding('ctrl+e', 'edit_worklog', 'Edit worklog'),
        Binding('ctrl+d', 'delete_worklog', 'Delete worklog'),
    ]

    @property
    def items(self) -> list['WorkLogListItem']:
        return list(self.query(WorkLogListItem))

    @property
    def highlighted_child(self) -> 'WorkLogListItem | None':
        items = self.items
        if 0 <= self.index < len(items):
            return items[self.index]
        return None

    async def clear(self) -> None:
        self.index = -1
        await self.remove_children()

    async def append(self, item: 'WorkLogListItem') -> None:
        await self.mount(item)
        if self.index == -1:
            self.index = 0

    def action_cursor_down(self) -> None:
        items = self.items
        if not items:
            return
        self.index = min(self.index + 1, len(items) - 1) if self.index >= 0 else 0

    def action_cursor_up(self) -> None:
        items = self.items
        if not items:
            return
        self.index = max(self.index - 1, 0) if self.index >= 0 else 0

    def watch_index(self, index: int) -> None:
        items = self.items
        for idx, item in enumerate(items):
            if idx == index:
                item.add_class('-highlight')
            else:
                item.remove_class('-highlight')

        highlighted = self.highlighted_child
        if highlighted is not None:
            self.scroll_to_widget(highlighted, animate=False)

    def action_open_worklog_in_browser(self) -> None:
        if self.highlighted_child and isinstance(self.highlighted_child, WorkLogListItem):
            self.highlighted_child.action_open_worklog_in_browser()
        else:
            self.notify('No worklog selected', severity='warning', title='Worklog')

    def action_edit_worklog(self) -> None:
        if self.highlighted_child and isinstance(self.highlighted_child, WorkLogListItem):
            self.highlighted_child.action_edit_worklog()
        else:
            self.notify('No worklog selected', severity='warning', title='Worklog')

    def action_delete_worklog(self) -> None:
        if self.highlighted_child and isinstance(self.highlighted_child, WorkLogListItem):
            self.highlighted_child.action_delete_worklog()
        else:
            self.notify('No worklog selected', severity='warning', title='Worklog')


class WorkLogListItem(Vertical):
    """A card representing a single worklog entry."""

    DEFAULT_CSS = """
    WorkLogListItem {
        background: transparent;
        border: none;
        height: auto;
        padding: 0;
        margin: 0 1 0 0;
        min-height: 0;
        opacity: 0.6;
    }

    WorkLogListItem:hover {
        opacity: 1;
    }

    WorkLogListItem.-highlight {
        opacity: 1;
    }

    WorkLogListItem > .worklog-item-container {
        background: transparent;
        padding: 0;
        margin: 0;
        height: auto;
        min-height: 0;
    }

    WorkLogListItem:hover > .worklog-item-container > .worklog-header-row,
    WorkLogListItem:hover > .worklog-item-container > .worklog-metadata,
    WorkLogListItem:hover > .worklog-item-container > .worklog-error {
        background: $surface-lighten-1;
    }

    WorkLogListItem:hover > .worklog-item-container > .worklog-body {
        background: $surface-lighten-1;
    }

    WorkLogListItem.-highlight > .worklog-item-container > .worklog-header-row,
    WorkLogListItem.-highlight > .worklog-item-container > .worklog-metadata,
    WorkLogListItem.-highlight > .worklog-item-container > .worklog-error {
        background: $primary-muted;
    }

    WorkLogListItem.-highlight > .worklog-item-container > .worklog-body {
        background: $primary-muted;
    }

    WorkLogListItem > .worklog-item-container > * {
        margin-bottom: 0;
        padding-bottom: 0;
    }

    WorkLogListItem .worklog-header-row {
        width: 100%;
        height: auto;
        min-height: 0;
        margin: 0;
        padding: 0 1;
    }

    WorkLogListItem .worklog-author {
        width: 100%;
        color: $accent;
        text-style: bold;
        margin: 0;
        padding: 0;
        height: auto;
        min-height: 0;
    }

    WorkLogListItem .worklog-metadata {
        width: 100%;
        color: $text-muted;
        margin: 0;
        padding: 0 1;
        height: auto;
        min-height: 0;
    }

    WorkLogListItem .worklog-body {
        width: 100%;
        background: transparent;
        padding: 0 1;
        margin: 0;
        height: auto;
        min-height: 0;
    }

    WorkLogListItem .worklog-body > * {
        margin-bottom: 0;
        padding-bottom: 0;
    }

    WorkLogListItem .worklog-body Link {
        color: $accent;
        text-style: underline;
    }

    WorkLogListItem .worklog-body Link:focus {
        background: $accent-darken-2;
        text-style: bold underline;
    }

    WorkLogListItem .worklog-error {
        width: 100%;
        color: $warning;
    }
    """

    def __init__(self, *args, **kwargs):
        self._work_item_key: str | None = kwargs.pop('work_item_key', None)
        self._worklog_id: str | None = kwargs.pop('worklog_id', None)
        self._url: str | None = kwargs.pop('url', None)
        self._time_spent: str | None = kwargs.pop('time_spent', None)
        self._started: str | None = kwargs.pop('started', None)
        self._comment: str | None = kwargs.pop('comment', None)
        super().__init__(*args, **kwargs)

    def action_open_worklog_in_browser(self) -> None:
        if self._url:
            self.app.open_url(self._url)
            if self._work_item_key:
                self.notify('Opening worklog in browser', title=self._work_item_key)
        else:
            if self._work_item_key:
                self.notify(
                    'Unable to build worklog URL', severity='warning', title=self._work_item_key
                )

    def action_edit_worklog(self) -> None:
        if self._work_item_key and self._worklog_id:
            self.run_worker(self._do_edit_worklog())
        else:
            if self._work_item_key:
                self.notify(
                    'Worklog information not available',
                    severity='warning',
                    title=self._work_item_key,
                )

    async def _do_edit_worklog(self) -> None:
        if not self._work_item_key or not self._worklog_id:
            if self._work_item_key:
                self.notify(
                    'Worklog information not available',
                    severity='warning',
                    title=self._work_item_key,
                )
            return

        parent_screen = None
        current_remaining_estimate = None
        parent = self.parent
        while parent is not None:
            if isinstance(parent, WorkItemWorkLogScreen):
                parent_screen = parent
                current_remaining_estimate = parent._current_remaining_estimate
                break
            parent = parent.parent

        if not parent_screen:
            if self._work_item_key:
                self.notify(
                    'Could not find parent screen', severity='error', title=self._work_item_key
                )
            return

        result = await self.app.push_screen_wait(
            LogWorkScreen(
                work_item_key=self._work_item_key,
                mode='edit',
                current_remaining_estimate=current_remaining_estimate,
                worklog_id=self._worklog_id,
                time_spent=self._time_spent,
                started=self._started,
                description=self._comment,
            )
        )

        if result and result.get('mode') == 'edit':
            parent_screen.run_worker(parent_screen._handle_worklog_update(result))

    def action_delete_worklog(self) -> None:
        if self._work_item_key and self._worklog_id:
            self.run_worker(self._do_delete_worklog())
        else:
            if self._work_item_key:
                self.notify(
                    'Worklog information not available',
                    severity='warning',
                    title=self._work_item_key,
                )

    async def _do_delete_worklog(self) -> None:
        parent_screen = None
        parent = self.parent
        while parent is not None:
            if isinstance(parent, WorkItemWorkLogScreen):
                parent_screen = parent
                break
            parent = parent.parent

        if not parent_screen:
            if self._work_item_key:
                self.notify(
                    'Could not find parent screen', severity='error', title=self._work_item_key
                )
            return

        result = await self.app.push_screen_wait(
            ConfirmationScreen('Are you sure you want to delete this worklog?')
        )

        if result and self._work_item_key and self._worklog_id:
            parent_screen.run_worker(
                parent_screen._handle_worklog_deletion(self._work_item_key, self._worklog_id)
            )


class WorkItemWorkLogScreen(ExtendedModalScreen[dict]):
    """A modal screen that displays the work logs of a work item using ListView with pagination."""

    DEFAULT_CSS = """
    WorkItemWorkLogScreen #modal_outer {
        width: 68%;
        max-width: 96;
        height: auto;
        max-height: 24;
    }
    """

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'close_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]
    TITLE = 'Worklog'
    PAGE_SIZE = 5000

    def __init__(self, work_item_key: str, current_remaining_estimate: str | None = None):
        super().__init__()
        self._work_item_key = work_item_key
        self._current_remaining_estimate = current_remaining_estimate
        self._is_loading = False

    @property
    def help_anchor(self) -> str:
        return '#worklogs'

    @property
    def worklog_list_view(self) -> WorkLogListView:
        return self.query_one('#worklogs-list-view', WorkLogListView)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(f'{self.TITLE} - {self._work_item_key}', id='modal_title')
            yield WorkLogListView(id='worklogs-list-view')
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Close',
                    variant='primary',
                    id='worklog-button-close',
                    classes='dialog-button dialog-button--secondary',
                    compact=True,
                )
        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        if self._work_item_key:
            await self.fetch_work_log()
        self.call_after_refresh(lambda: focus_first_available(self.worklog_list_view))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def _handle_worklog_update(self, data: dict) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        worklog_id = data.get('worklog_id')

        if not worklog_id:
            self.notify('Worklog ID not found', severity='error', title='Worklog')
            return

        started_dt = None
        if started_str := data.get('started'):
            try:
                started_dt = datetime.fromisoformat(started_str).replace(tzinfo=timezone.utc)
            except (ValueError, TypeError) as e:
                self.notify(f'Invalid started date format: {e}', severity='error', title='Worklog')
                return

        response: APIControllerResponse = await application.api.update_worklog(
            self._work_item_key,
            worklog_id,
            time_spent=data.get('time_spent'),
            started=started_dt,
            comment=data.get('description'),
        )

        if response.success:
            self.notify('Worklog updated', title='Worklog')

            await self.reload_worklogs()
        else:
            self.notify(
                f'Failed to update the worklog: {response.error}',
                title='Worklog',
                severity='error',
            )

    async def _handle_worklog_deletion(self, work_item_key: str, worklog_id: str) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.remove_worklog(
            work_item_key, worklog_id
        )

        if response.success:
            self.notify('Worklog deleted', title='Worklog')

            await self.reload_worklogs()
        else:
            self.notify(
                f'Failed to delete the worklog: {response.error}',
                title='Worklog',
                severity='error',
            )

    def dismiss_on_backdrop_click(self) -> None:
        self.dismiss()

    def action_close_screen(self) -> None:
        self.dismiss()

    @on(Button.Pressed, '#worklog-button-close')
    def handle_close(self) -> None:
        self.dismiss()

    async def reload_worklogs(self) -> None:
        list_view = self.worklog_list_view
        await list_view.clear()

        await self.fetch_work_log(offset=0, append=False)

    async def fetch_work_log(self, offset: int = 0, append: bool = False) -> None:
        if self._is_loading:
            return

        self._is_loading = True

        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.get_work_item_worklog(
            self._work_item_key, offset=offset, limit=self.PAGE_SIZE
        )

        if response.success and (result := response.result):
            list_view = self.worklog_list_view
            if not result.logs:
                await list_view.mount(
                    Static('No worklogs found for this work item.', classes='worklog-empty-state')
                )
                return

            for index, worklog in enumerate(result.logs):
                worklog_container = Vertical(classes='worklog-item-container')

                header_row = Horizontal(classes='worklog-header-row')
                author_name = worklog.author.display_name if worklog.author else 'Unknown'
                time_spent_display = worklog.time_spent or 'N/A'
                title_text = Text(f'{author_name} - {time_spent_display}', style='bold')
                header_row.compose_add_child(Static(title_text, classes='worklog-author'))
                worklog_container.compose_add_child(header_row)

                started_date = worklog.created_on() if worklog.started else 'Unknown date'
                metadata_parts = [f'Started: {started_date}']

                if worklog.updated and worklog.started and worklog.updated != worklog.started:
                    updated_text = f'(updated {worklog.updated_on()})'
                    metadata_parts.append(updated_text)

                metadata = ' '.join(metadata_parts)
                metadata_text = Text(metadata, style='dim')
                worklog_container.compose_add_child(
                    Static(metadata_text, classes='worklog-metadata')
                )

                if worklog.comment:
                    base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)
                    if content := worklog.get_comment(base_url=base_url):
                        content = content.strip()
                        worklog_container.compose_add_child(
                            GojeeraMarkdown(content, classes='worklog-body')
                        )
                    else:
                        worklog_container.compose_add_child(
                            Static(
                                Text(
                                    'Unable to display the description.',
                                    style='bold orange',
                                ),
                                classes='worklog-error',
                            )
                        )

                url = build_external_url_for_work_item(
                    self._work_item_key,
                    cast('JiraApp', self.app),  # noqa: F821
                    focused_work_log_id=worklog.id,
                )

                started_formatted = None
                if worklog.started:
                    started_formatted = worklog.started.strftime('%Y-%m-%d %H:%M')

                list_item = WorkLogListItem(
                    worklog_container,
                    work_item_key=self._work_item_key,
                    worklog_id=worklog.id,
                    url=url,
                    time_spent=worklog.time_spent,
                    started=started_formatted,
                    comment=content if worklog.comment else None,
                    id=f'worklog-{worklog.id}',
                )

                await list_view.append(list_item)
                if index < len(result.logs) - 1:
                    await list_view.mount(Spacer())

            if not append and list_view.items:
                list_view.index = 0

        self._is_loading = False
