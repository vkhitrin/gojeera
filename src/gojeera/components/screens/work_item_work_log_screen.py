from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.reactive import Reactive, reactive
from textual.widgets import Button, Static

from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.work_log_screen import LogWorkScreen
from gojeera.internal.jira.controller import APIControllerResponse
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

    DEFAULT_CSS = """
    WorkItemWorkLogScreen #modal_outer {
        width: 68%;
        max-width: 96;
        height: auto;
        max-height: 24;
    }

    WorkItemWorkLogScreen #worklogs-content-container {
        width: 100%;
        height: auto;
        max-height: 15;
        margin-bottom: 1;
    }

    WorkItemWorkLogScreen #worklogs-list-view {
        width: 100%;
        height: auto;
        max-height: 15;
        margin: 0 1;
        overflow-y: auto;
    }
    """

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+o', 'open_worklog_in_browser', 'Open in browser'),
        Binding('ctrl+e', 'edit_worklog', 'Edit worklog'),
        Binding('ctrl+d', 'delete_worklog', 'Delete worklog'),
    ]
    TITLE = 'Worklog'
    PAGE_SIZE = 5000
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self, work_item_key: str, current_remaining_estimate: str | None = None):
        super().__init__()
        self._work_item_key = work_item_key
        self._current_remaining_estimate = current_remaining_estimate
        self.is_loading = bool(work_item_key)

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

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(f'{self.TITLE} - {self._work_item_key}', id='modal_title')
            with Container(id='worklogs-content-container'):
                yield RecordList(widget_id='worklogs-list-view')
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
        self.modal_outer.loading = loading

    async def on_mount(self) -> None:
        self.content_container.can_focus = False
        self.modal_outer.loading = self.is_loading
        if self._work_item_key:
            self.call_after_refresh(
                lambda: self.run_worker(
                    self._fetch_work_log_impl(offset=0, manage_loading=False),
                    exclusive=True,
                )
            )
        self.call_after_refresh(lambda: focus_first_available(self.worklog_list_view))

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
        await self.fetch_work_log(offset=0)

    async def fetch_work_log(self, offset: int = 0) -> None:
        if self.is_loading:
            return

        self.is_loading = True
        await self._fetch_work_log_impl(offset=offset, manage_loading=False)

    async def _fetch_work_log_impl(self, offset: int = 0, *, manage_loading: bool = True) -> None:
        if manage_loading:
            if self.is_loading:
                return
            self.is_loading = True
        try:
            application = cast('JiraApp', self.app)  # noqa: F821
            response: APIControllerResponse = await application.api.get_work_item_worklog(
                self._work_item_key, offset=offset, limit=self.PAGE_SIZE
            )

            if response.success and (result := response.result):
                list_view = self.worklog_list_view
                if not result.logs:
                    list_view.clear_records()
                    return

                records: list[Record] = []
                for worklog in result.logs:
                    author_name = worklog.author.display_name if worklog.author else 'Unknown'
                    time_spent_display = worklog.time_spent or 'N/A'
                    meta = f'{author_name} - {time_spent_display}'

                    started_date = worklog.created_on() if worklog.started else 'Unknown date'
                    metadata_parts = [f'Started: {started_date}']

                    if worklog.updated and worklog.started and worklog.updated != worklog.started:
                        updated_text = f'(updated {worklog.updated_on()})'
                        metadata_parts.append(updated_text)

                    metadata = ' '.join(metadata_parts)
                    content = ''
                    if worklog.comment:
                        base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)
                        if content := worklog.get_comment(base_url=base_url):
                            content = content.strip()
                    title = content or 'No description'

                    url = build_external_url_for_work_item(
                        self._work_item_key,
                        cast('JiraApp', self.app),  # noqa: F821
                        focused_work_log_id=worklog.id,
                    )

                    started_formatted = None
                    if worklog.started:
                        started_formatted = worklog.started.strftime('%Y-%m-%d %H:%M')

                    records.append(
                        Record(
                            key=worklog.id,
                            meta=meta,
                            title=title,
                            footer=metadata,
                            payload={
                                'worklog': worklog,
                                'url': url,
                                'time_spent': worklog.time_spent,
                                'started': started_formatted,
                                'comment': content if worklog.comment else None,
                            },
                        )
                    )
                list_view.set_records(records)
        finally:
            if not manage_loading or self.is_loading:
                self.is_loading = False

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
