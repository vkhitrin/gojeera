from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, ListItem, ListView, Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_log_screen import LogWorkScreen
from gojeera.config import CONFIGURATION
from gojeera.utils.urls import build_external_url_for_work_log
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkLogListView(ListView):
    """Custom ListView for worklogs with vim-style j/k navigation."""

    can_focus = True

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next worklog', show=False),
        Binding('k', 'cursor_up', 'Previous worklog', show=False),
        Binding('ctrl+o', 'open_worklog_in_browser', 'Open in browser'),
        Binding('e', 'edit_worklog', 'Edit worklog'),
        Binding('d', 'delete_worklog', 'Delete worklog'),
    ]

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


class WorkLogListItem(ListItem):
    """A list item representing a single worklog entry."""

    DEFAULT_CSS = """
    WorkLogListItem {
        height: auto;
        padding: 0;
        margin: 0 2;
    }

    WorkLogListItem > Vertical {
        height: auto;
        padding: 0;
        margin: 0;
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


class WorkItemWorkLogScreen(ModalScreen[dict]):
    """A modal screen that displays the work logs of a work item using ListView with pagination."""

    BINDINGS = [
        ('escape', 'close_screen', 'Close'),
        ('n', 'add_worklog', 'New worklog'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]
    TITLE = 'Worklog'
    PAGE_SIZE = 5000

    def __init__(self, work_item_key: str, current_remaining_estimate: str | None = None):
        super().__init__()
        self._work_item_key = work_item_key
        self._current_remaining_estimate = current_remaining_estimate
        self._is_loading = False
        self._work_logs_deleted = False
        self._work_logs_updated = False

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
            with VerticalScroll(id='worklog-scroll-container'):
                yield WorkLogListView(id='worklogs-list-view', initial_index=0)
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        if self._work_item_key:
            await self.fetch_work_log()

        if CONFIGURATION.get().jumper.enabled:
            self.worklog_list_view.jump_mode = 'focus'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def action_add_worklog(self) -> None:
        if self._work_item_key:
            self.run_worker(self._do_add_worklog())
        else:
            self.notify('Work item key not available', severity='error', title='Worklog')

    async def _do_add_worklog(self) -> None:
        result = await self.app.push_screen_wait(
            LogWorkScreen(
                work_item_key=self._work_item_key,
                mode='new',
                current_remaining_estimate=self._current_remaining_estimate,
            )
        )

        if result and result.get('mode') == 'new':
            await self._add_worklog(result)

    async def _add_worklog(self, data: dict) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821

        time_spent = data.get('time_spent')
        started = data.get('started')

        if not time_spent or not started:
            self.notify(
                'Missing required fields for logging work', severity='error', title='Worklog'
            )
            return

        try:
            started_dt = datetime.fromisoformat(started).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError) as e:
            self.notify(f'Invalid started date format: {e}', severity='error', title='Worklog')
            return

        response: APIControllerResponse = await application.api.add_work_item_worklog(
            work_item_key_or_id=self._work_item_key,
            started=started_dt,
            time_spent=time_spent,
            time_remaining=data.get('time_remaining'),
            comment=data.get('description'),
            current_remaining_estimate=data.get('current_remaining_estimate'),
        )

        if response.success:
            self.notify('Worklog added', title='Worklog')

            self._work_logs_updated = True

            await self.reload_worklogs()
        else:
            self.notify(
                f'Failed to add worklog: {response.error}',
                title='Worklog',
                severity='error',
            )

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

            self._work_logs_updated = True

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

            self._work_logs_deleted = True

            await self.reload_worklogs()
        else:
            self.notify(
                f'Failed to delete the worklog: {response.error}',
                title='Worklog',
                severity='error',
            )

    def on_click(self) -> None:
        self.dismiss(
            {
                'work_logs_deleted': self._work_logs_deleted,
                'work_logs_updated': self._work_logs_updated,
            }
        )

    def action_close_screen(self) -> None:
        self.dismiss(
            {
                'work_logs_deleted': self._work_logs_deleted,
                'work_logs_updated': self._work_logs_updated,
            }
        )

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
            for worklog in result.logs:
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

                url = build_external_url_for_work_log(
                    self._work_item_key,
                    worklog.id,
                    cast('JiraApp', self.app),  # noqa: F821
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

                list_view.append(list_item)

            if not append and list_view.children:
                list_view.index = 0

        self._is_loading = False
