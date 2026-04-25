from typing import TYPE_CHECKING, cast
from uuid import uuid4

from textual import on
from textual.reactive import Reactive, reactive

from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.web_link_screen import RemoteLinkScreen
from gojeera.components.tabs.record_list_tab import RecordListTabWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import WorkItemRemoteLink
from gojeera.widgets.layout.record_list import Record, RecordList

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemRemoteLinksWidget(RecordListTabWidget):
    """This widget handles adding and updating the list of remote links (aka. web links) associated to a work item."""

    work_item_key: Reactive[str | None] = reactive(None, always_update=True)
    remote_links: Reactive[list[WorkItemRemoteLink] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(widget_id='work_item_remote_links', record_list_id='remote-links-list')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#web-links'

    @property
    def has_records(self) -> bool:
        return bool(self.remote_links)

    @property
    def selected_link(self) -> WorkItemRemoteLink | None:
        return self.selected_payload_as(WorkItemRemoteLink)

    async def _resolve_selected_link_id(self) -> str | None:
        selected = self.selected_link
        if selected is None:
            return None
        if not selected.id.startswith('local-'):
            return selected.id
        if not self._work_item_key:
            return None

        await self.fetch_remote_links(self._work_item_key)
        latest_selected = self.selected_link
        selected_url = latest_selected.url if latest_selected else selected.url
        selected_title = latest_selected.title if latest_selected else selected.title
        if not selected_url:
            return None

        for link in self.remote_links or []:
            if link.url == selected_url and link.title == selected_title:
                self.record_list.focus_record_by_key(link.id)
                return link.id
        return None

    async def action_add_remote_link(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(RemoteLinkScreen(self.work_item_key), callback=self.add_link)

    def add_link(self, data: dict | None = None) -> None:
        if data:
            self.run_worker(self.create_link(data))

    def _extract_link_url_and_title(self, data: dict) -> tuple[str, str] | None:
        link_url = data.get('link_url')
        link_title = data.get('link_title')

        if not link_url or not isinstance(link_url, str):
            self.notify('Missing or invalid link URL', severity='error')
            return None
        if not link_title or not isinstance(link_title, str):
            self.notify('Missing or invalid link title', severity='error')
            return None

        return (link_url, link_title)

    async def create_link(self, data: dict) -> None:
        if not self.work_item_key:
            self.notify('Work item key is missing', severity='error')
            return

        extracted_link_fields = self._extract_link_url_and_title(data)
        if extracted_link_fields is None:
            return
        link_url, link_title = extracted_link_fields

        screen = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await screen.api.create_work_item_remote_link(
            self.work_item_key,
            link_url,
            link_title,
        )
        if not response.success:
            self.notify(
                f'Failed to add link: {response.error}',
                severity='error',
                title=self.work_item_key,
            )
        else:
            self.notify('Link added successfully', title=self.work_item_key)
            current_links = self.remote_links or []
            self.remote_links = [
                *current_links,
                WorkItemRemoteLink(
                    id=f'local-{uuid4().hex}',
                    global_id='',
                    relationship='',
                    title=link_title,
                    summary='',
                    url=link_url,
                    status_resolved=None,
                ),
            ]
            self.run_worker(self.fetch_remote_links(self.work_item_key), exclusive=True)

    async def action_open_link(self) -> None:
        selected = self.selected_link
        if selected and selected.url:
            if self._work_item_key:
                self.notify('Opening link in the browser...', title=self._work_item_key)
            self.app.open_url(selected.url)

    async def action_edit_remote_link(self) -> None:
        selected = self.selected_link
        if selected is None:
            if self._work_item_key:
                self.notify(
                    'Select a row, e.g. by clicking on it, before attempting to edit the link.',
                    severity='error',
                    title=self._work_item_key,
                )
            return

        resolved_link_id = await self._resolve_selected_link_id()
        if not resolved_link_id:
            self.notify(
                'The link is still syncing. Please try again in a moment.', severity='warning'
            )
            return

        await self.app.push_screen(
            RemoteLinkScreen(
                self._work_item_key,
                link_id=resolved_link_id,
                initial_url=selected.url,
                initial_title=selected.title,
            ),
            callback=self.handle_edit_save,
        )

    async def handle_edit_save(self, data: dict | None = None) -> None:
        if data and data.get('link_id'):
            if not self._work_item_key:
                self.notify('Work item key is missing', severity='error')
                return

            link_id = data.get('link_id')
            if not link_id or not isinstance(link_id, str):
                self.notify('Missing or invalid link ID', severity='error')
                return
            extracted_link_fields = self._extract_link_url_and_title(data)
            if extracted_link_fields is None:
                return
            link_url, link_title = extracted_link_fields

            application = cast('JiraApp', self.app)  # noqa: F821
            response: APIControllerResponse = await application.api.update_work_item_remote_link(
                self._work_item_key,
                link_id,
                link_url,
                link_title,
            )
            if not response.success:
                self.notify(
                    f'Failed to update link: {response.error}',
                    severity='error',
                    title=self._work_item_key,
                )
            else:
                self.notify('Link updated successfully', title=self._work_item_key)
                updated_links: list[WorkItemRemoteLink] = []
                for link in self.remote_links or []:
                    if link.id == link_id:
                        updated_links.append(
                            WorkItemRemoteLink(
                                id=link.id,
                                global_id=link.global_id,
                                relationship=link.relationship,
                                title=link_title,
                                summary=link.summary,
                                url=link_url,
                                status_resolved=link.status_resolved,
                            )
                        )
                    else:
                        updated_links.append(link)
                self.remote_links = updated_links

    async def action_delete_remote_link(self) -> None:
        if self.selected_link is None:
            if self._work_item_key:
                self.notify(
                    'Select a row, e.g. by clicking on it, before attempting to delete the link.',
                    severity='error',
                    title=self._work_item_key,
                )
            return
        await self.app.push_screen(
            ConfirmationScreen('Are you sure you want to delete the link?'),
            callback=self.handle_delete_choice,
        )

    async def handle_delete_choice(self, result: bool | None) -> None:
        if not result:
            return
        if not self._work_item_key:
            self.notify('Work item key is missing', severity='error')
            return
        resolved_link_id = await self._resolve_selected_link_id()
        if not resolved_link_id:
            self.notify('No link selected', severity='error')
            return

        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.delete_work_item_remote_link(
            self._work_item_key, resolved_link_id
        )
        if not response.success:
            self.notify(
                f'Failed to delete the link: {response.error}',
                severity='error',
                title=self._work_item_key,
            )
        else:
            self.notify('Link deleted successfully', title=self._work_item_key)
            self.remote_links = [
                link for link in (self.remote_links or []) if link.id != resolved_link_id
            ]

    async def fetch_remote_links(self, work_item_key: str) -> None:
        screen = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await screen.api.get_work_item_remote_links(work_item_key)
        if work_item_key:
            if not response.success:
                self.notify(
                    'Unable to retrieve the remote links associated to the work item.',
                    severity='warning',
                    title=work_item_key,
                )
        if not response.success:
            if work_item_key:
                self.notify(
                    'Unable to retrieve the remote links associated to the work item.',
                    severity='warning',
                    title=work_item_key,
                )

            with self.app.batch_update():
                self.record_list.clear_records()
                self.hide_loading()
            return

        self.remote_links = response.result or []

    def watch_remote_links(self, links: list[WorkItemRemoteLink] | None) -> None:
        with self.app.batch_update():
            if not links:
                self.record_list.clear_records()
                self.hide_loading()
                self.displayed_count = 0
                return

            records: list[Record] = []
            link_count = 0
            for item in links:
                if not item.url:
                    continue

                if item.status_resolved is None:
                    status = ''
                elif item.status_resolved:
                    status = 'Resolved'
                else:
                    status = 'Not Resolved'

                footer_parts = [part for part in (status, item.url) if part]
                records.append(
                    Record(
                        key=item.id,
                        meta=item.relationship or 'Web link',
                        title=item.title or 'Untitled',
                        footer=' • '.join(footer_parts),
                        payload=item,
                    )
                )
                link_count += 1

            self.record_list.set_records(records)
            self.hide_loading()
            self.displayed_count = link_count

    def watch_work_item_key(self, work_item_key: str | None = None) -> None:
        self._work_item_key = work_item_key
        self.remote_links = None

        if not work_item_key:
            self.is_loading = False
            self.displayed_count = 0
            return

        self.show_loading()
        self.run_worker(self.fetch_remote_links(work_item_key))

    @on(RecordList.RowInvoked)
    def on_row_invoked(self, event: RecordList.RowInvoked) -> None:
        if event.control is self.record_list:
            self.run_worker(self.action_open_link())
