from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import Reactive, reactive
from textual.widgets import Button, Static
from textual.worker import Worker

from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.work_log_screen import LogWorkScreen
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.work_items import JiraWorklog, PaginatedJiraWorklog
from gojeera.utils.jira.urls import build_external_url_for_work_item
from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.record_list import Record, RecordList
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemWorkLogScreen(ExtendedModalScreen[dict]):
    """A modal screen that displays the work logs of a work item using ListView with pagination."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+o', 'open_worklog_in_browser', 'Open in browser'),
        Binding('ctrl+e', 'edit_worklog', 'Edit worklog'),
        Binding('ctrl+d', 'delete_worklog', 'Delete worklog'),
    ]
    TITLE = 'Worklog'
    PAGE_SIZE = 100
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(
        self,
        work_item_key: str,
        current_remaining_estimate: str | None = None,
        initial_page: PaginatedJiraWorklog | None = None,
    ):
        super().__init__()
        self._work_item_key = work_item_key
        self._current_remaining_estimate = current_remaining_estimate
        self._worklogs = list(initial_page.logs) if initial_page is not None else []
        self._worklog_ids = {worklog.id for worklog in self._worklogs}
        self._next_offset = (
            initial_page.start_at + len(initial_page.logs) if initial_page is not None else 0
        )
        self._pagination_complete = initial_page is not None and (
            not initial_page.logs or self._next_offset >= initial_page.total
        )
        self._loading_worker: Worker | None = None
        self.is_loading = bool(work_item_key and initial_page is None)

    @property
    def help_anchor(self) -> str:
        return '#worklogs'

    @property
    def worklog_list_view(self) -> RecordList:
        return self.query_one('#worklogs-list-view', RecordList)

    @property
    def content_container(self) -> Container:
        return self.query_one('#worklogs-content-container', Container)

    @property
    def modal_outer(self) -> VerticalSuppressClicks:
        return self.query_one('#modal_outer', VerticalSuppressClicks)

    @property
    def loading_label(self) -> Static:
        return self.query_one('#worklogs-loading', Static)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(f'{self.TITLE} - {self._work_item_key}', id='modal_title')
            with Container(id='worklogs-content-container'):
                yield RecordList(widget_id='worklogs-list-view')
                loading_label = Static('Loading more…', id='worklogs-loading')
                loading_label.display = False
                yield loading_label
            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Close',
                    variant='primary',
                    id='worklog-button-close',
                    classes='dialog-button dialog-button--secondary',
                    compact=True,
                )
        yield ExtendedFooter(show_command_palette=False)

    def watch_is_loading(self, loading: bool) -> None:
        if not self.is_mounted:
            return
        has_records = bool(self.worklog_list_view._records)
        self.modal_outer.loading = loading and not has_records
        self.loading_label.display = loading and has_records

    async def on_mount(self) -> None:
        self.content_container.can_focus = False
        if self._worklogs:
            self.worklog_list_view.set_records(self._records_for_worklogs(self._worklogs))
            self.is_loading = False
        self.watch_is_loading(self.is_loading)
        if self._work_item_key and not self._pagination_complete:
            self.call_after_refresh(self._start_next_page_load)
        self.call_after_refresh(lambda: focus_first_available(self.worklog_list_view))

    def _start_next_page_load(self) -> None:
        if self._pagination_complete or not self._work_item_key:
            return
        if self._loading_worker is not None and not self._loading_worker.is_finished:
            return
        self._loading_worker = self.run_worker(
            self._fetch_next_worklog_page(),
            exclusive=True,
            group='worklog-pages',
        )

    def _load_next_page_if_viewport_needs_it(self) -> None:
        if self._pagination_complete or self.is_loading:
            return
        viewport_height = max(1, self.worklog_list_view.scrollable_content_region.height)
        if self.worklog_list_view.max_scroll_y - self.worklog_list_view.scroll_y <= viewport_height:
            self._start_next_page_load()

    @on(RecordList.NearEnd)
    def on_record_list_near_end(self, event: RecordList.NearEnd) -> None:
        if event.control is self.worklog_list_view:
            self._start_next_page_load()

    async def _handle_worklog_update(self, data: dict) -> None:
        application = cast('JiraApp', self.app)
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
        application = cast('JiraApp', self.app)
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
        self._reset_worklog_pagination()
        await self._fetch_next_worklog_page()

    def _reset_worklog_pagination(self) -> None:
        self._worklogs = []
        self._worklog_ids = set()
        self._next_offset = 0
        self._pagination_complete = False
        if self.is_mounted:
            self.worklog_list_view.clear_records()

    def _records_for_worklogs(self, worklogs: list[JiraWorklog]) -> list[Record]:
        records: list[Record] = []
        for worklog in worklogs:
            author_name = worklog.author.display_name if worklog.author else 'Unknown'
            time_spent_display = worklog.time_spent or 'N/A'
            meta = f'{author_name} - {time_spent_display}'

            started_date = worklog.created_on() if worklog.started else 'Unknown date'
            metadata_parts = [f'Started: {started_date}']

            if worklog.updated and worklog.started and worklog.updated != worklog.started:
                metadata_parts.append(f'(updated {worklog.updated_on()})')

            content = ''
            if worklog.comment:
                base_url = getattr(
                    getattr(getattr(self.app, 'atlassian_context', None), 'server_info', None),
                    'base_url',
                    None,
                )
                if converted_content := worklog.get_comment(base_url=base_url):
                    content = converted_content.strip()

            started_formatted = (
                worklog.started.strftime('%Y-%m-%d %H:%M') if worklog.started else None
            )
            records.append(
                Record(
                    key=worklog.id,
                    meta=meta,
                    title=content or 'No description',
                    footer=' '.join(metadata_parts),
                    payload={
                        'worklog': worklog,
                        'url': build_external_url_for_work_item(
                            self._work_item_key,
                            cast('JiraApp', self.app),
                            focused_work_log_id=worklog.id,
                        ),
                        'time_spent': worklog.time_spent,
                        'started': started_formatted,
                        'comment': content if worklog.comment else None,
                    },
                )
            )
        return records

    async def _fetch_next_worklog_page(self) -> None:
        if self._pagination_complete:
            return
        self.is_loading = True
        try:
            application = cast('JiraApp', self.app)
            response: APIControllerResponse = await application.api.get_work_item_worklog(
                self._work_item_key,
                offset=self._next_offset,
                limit=self.PAGE_SIZE,
            )

            if not response.success or not isinstance(response.result, PaginatedJiraWorklog):
                self._pagination_complete = True
                self.notify(
                    response.error or 'Unable to load work logs',
                    severity='warning',
                    title=self._work_item_key,
                )
                return

            page = response.result
            new_worklogs = [worklog for worklog in page.logs if worklog.id not in self._worklog_ids]
            self._worklogs.extend(new_worklogs)
            self._worklog_ids.update(worklog.id for worklog in new_worklogs)
            previous_offset = self._next_offset
            self._next_offset = page.start_at + len(page.logs)
            self._pagination_complete = (
                not page.logs
                or self._next_offset <= previous_offset
                or self._next_offset >= page.total
            )

            if not new_worklogs and not self._worklogs:
                self.worklog_list_view.clear_records()
            elif new_worklogs:
                records = self._records_for_worklogs(new_worklogs)
                if len(self._worklogs) == len(new_worklogs):
                    self.worklog_list_view.set_records(records)
                else:
                    self.worklog_list_view.append_records(records)
        finally:
            self.is_loading = False
            if self.is_mounted and not self._pagination_complete:
                self.call_after_refresh(self._load_next_page_if_viewport_needs_it)

    @property
    def selected_worklog_payload(self) -> dict | None:
        payload = self.worklog_list_view.selected_payload
        return payload if isinstance(payload, dict) else None

    def _require_selected_worklog_payload(self) -> dict | None:
        payload = self.selected_worklog_payload
        if payload is None:
            self.notify('No worklog selected', severity='warning', title='Worklog')
            return None
        return payload

    def action_open_worklog_in_browser(self) -> None:
        payload = self._require_selected_worklog_payload()
        if payload is None:
            return
        url = payload.get('url')
        if isinstance(url, str) and url:
            self.app.open_url(url)
            self.notify('Opening worklog in browser', title=self._work_item_key)
            return
        self.notify('Unable to build worklog URL', severity='warning', title=self._work_item_key)

    def action_edit_worklog(self) -> None:
        payload = self._require_selected_worklog_payload()
        if payload is None:
            return
        self.run_worker(self._do_edit_worklog(payload))

    async def _do_edit_worklog(self, payload: dict) -> None:
        worklog_id = self._selected_worklog_id(payload)
        if worklog_id is None:
            self.notify('Worklog information not available', severity='warning', title='Worklog')
            return

        result = await self.app.push_screen_wait(
            LogWorkScreen(
                work_item_key=self._work_item_key,
                mode='edit',
                current_remaining_estimate=self._current_remaining_estimate,
                worklog_id=worklog_id,
                time_spent=payload.get('time_spent'),
                started=payload.get('started'),
                description=payload.get('comment'),
            )
        )

        if result and result.get('mode') == 'edit':
            self.run_worker(self._handle_worklog_update(result))

    def action_delete_worklog(self) -> None:
        payload = self._require_selected_worklog_payload()
        if payload is None:
            return
        self.run_worker(self._do_delete_worklog(payload))

    @staticmethod
    def _selected_worklog_id(payload: dict) -> str | None:
        worklog = payload.get('worklog')
        worklog_id = getattr(worklog, 'id', None)
        if isinstance(worklog_id, str) and worklog_id:
            return worklog_id
        return None

    async def _do_delete_worklog(self, payload: dict) -> None:
        worklog_id = self._selected_worklog_id(payload)
        if worklog_id is None:
            self.notify('Worklog information not available', severity='warning', title='Worklog')
            return

        result = await self.app.push_screen_wait(
            ConfirmationScreen('Are you sure you want to delete this worklog?')
        )

        if result:
            self.run_worker(self._handle_worklog_deletion(self._work_item_key, worklog_id))

    @on(RecordList.RowInvoked)
    def on_row_invoked(self, event: RecordList.RowInvoked) -> None:
        if event.control is self.worklog_list_view:
            self.action_edit_worklog()
