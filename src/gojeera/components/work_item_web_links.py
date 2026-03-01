from typing import TYPE_CHECKING, cast
from uuid import uuid4

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.web_link_screen import RemoteLinkScreen
from gojeera.models import WorkItemRemoteLink
from gojeera.widgets.extended_data_table import ExtendedDataTable

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class RemoteLinksDataTable(ExtendedDataTable):
    """A data table to list remote links associated to a work item."""

    BINDINGS = [
        Binding(
            key='d',
            action='delete_remote_link',
            description='Delete',
            tooltip='Deletes the remote link',
        ),
        Binding(
            key='e',
            action='edit_remote_link',
            description='Edit',
            tooltip='Edit the remote link',
        ),
        Binding(
            key='ctrl+o',
            action='open_link',
            description='Browse',
            show=True,
            tooltip='Open link in the browser',
        ),
    ]

    def __init__(self, work_item_key: str):
        super().__init__(cursor_type='row')
        self._selected_link_id: str | None = None
        self._selected_link_url: str | None = None
        self._selected_link_title: str | None = None
        self._work_item_key: str | None = work_item_key

    def _get_remote_links_widget(self) -> 'WorkItemRemoteLinksWidget | None':
        current = self.parent
        while current is not None:
            if isinstance(current, WorkItemRemoteLinksWidget):
                return current
            current = current.parent
        return None

    async def _resolve_selected_link_id(self) -> bool:
        if not self._selected_link_id or not self._selected_link_id.startswith('local-'):
            return True
        if not self._work_item_key:
            return False

        widget = self._get_remote_links_widget()
        if not widget:
            return False

        await widget.fetch_remote_links(self._work_item_key)

        selected_url = self._selected_link_url
        selected_title = self._selected_link_title
        if not selected_url:
            return False

        for link in widget.remote_links or []:
            if link.url == selected_url and link.title == selected_title:
                self._selected_link_id = link.id
                return True
        return False

    @on(ExtendedDataTable.RowHighlighted)
    def highlighted(self, event: ExtendedDataTable.RowHighlighted) -> None:
        if event.row_key.value is not None:
            self._selected_link_id = str(event.row_key.value)
            if (row := event.data_table.get_row(event.row_key.value)) and len(row) > 0:
                self._selected_link_title = str(row[0]) if len(row) > 0 else None
                self._selected_link_url = str(row[1]) if len(row) > 1 else None

    @on(ExtendedDataTable.RowSelected)
    def selected(self, event: ExtendedDataTable.RowSelected) -> None:
        if event.row_key.value:
            self._selected_link_id = str(event.row_key.value)
            if (row := event.data_table.get_row(event.row_key.value)) and len(row) > 1:
                self._selected_link_url = str(row[1])
                if self._selected_link_url:
                    self.run_worker(self.action_open_link())

    async def action_open_link(self) -> None:
        if self._selected_link_url:
            if self._work_item_key:
                self.notify('Opening link in the browser...', title=self._work_item_key)
            self.app.open_url(self._selected_link_url)

    async def action_edit_remote_link(self) -> None:
        if not self._selected_link_id:
            if self._work_item_key:
                self.notify(
                    'Select a row, e.g. by clicking on it, before attempting to edit the link.',
                    severity='error',
                    title=self._work_item_key,
                )
            return

        if not await self._resolve_selected_link_id():
            self.notify(
                'The link is still syncing. Please try again in a moment.', severity='warning'
            )
            return

        await self.app.push_screen(
            RemoteLinkScreen(
                self._work_item_key,
                link_id=self._selected_link_id,
                initial_url=self._selected_link_url,
                initial_title=self._selected_link_title,
            ),
            callback=self.handle_edit_save,
        )

    async def handle_edit_save(self, data: dict | None = None) -> None:
        if data and data.get('link_id'):
            # Validate required fields
            if not self._work_item_key:
                self.notify('Work item key is missing', severity='error')
                return

            link_id = data.get('link_id')
            link_url = data.get('link_url')
            link_title = data.get('link_title')

            if not link_id or not isinstance(link_id, str):
                self.notify('Missing or invalid link ID', severity='error')
                return
            if not link_url or not isinstance(link_url, str):
                self.notify('Missing or invalid link URL', severity='error')
                return
            if not link_title or not isinstance(link_title, str):
                self.notify('Missing or invalid link title', severity='error')
                return

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

                widget = self._get_remote_links_widget()
                if not widget:
                    return

                updated_links: list[WorkItemRemoteLink] = []
                for link in getattr(widget, 'remote_links', None) or []:
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
                cast('WorkItemRemoteLinksWidget', widget).remote_links = updated_links

    async def action_delete_remote_link(self) -> None:
        if not self._selected_link_id:
            if self._work_item_key:
                self.notify(
                    'Select a row, e.g. by clicking on it, before attempting to delete the link.',
                    severity='error',
                    title=self._work_item_key,
                )
        else:
            await self.app.push_screen(
                ConfirmationScreen('Are you sure you want to delete the link?'),
                callback=self.handle_delete_choice,
            )

    async def handle_delete_choice(self, result: bool | None) -> None:
        if result:
            if not self._work_item_key:
                self.notify('Work item key is missing', severity='error')
                return
            if not self._selected_link_id:
                self.notify('No link selected', severity='error')
                return
            if not await self._resolve_selected_link_id():
                self.notify(
                    'The link is still syncing. Please try again in a moment.', severity='warning'
                )
                return

            application = cast('JiraApp', self.app)  # noqa: F821
            response: APIControllerResponse = await application.api.delete_work_item_remote_link(
                self._work_item_key, self._selected_link_id
            )
            if not response.success:
                self.notify(
                    f'Failed to delete the link: {response.error}',
                    severity='error',
                    title=self._work_item_key,
                )
            else:
                self.notify('Link deleted successfully', title=self._work_item_key)
                widget = self._get_remote_links_widget()
                if not widget:
                    return
                cast('WorkItemRemoteLinksWidget', widget).remote_links = [
                    link
                    for link in (getattr(widget, 'remote_links', None) or [])
                    if link.id != self._selected_link_id
                ]


class WorkItemRemoteLinksWidget(VerticalScroll, can_focus=False):
    """This widget handles adding and updating the list of remote links (aka. web links) associated to a work item."""

    work_item_key: Reactive[str | None] = reactive(None, always_update=True)
    remote_links: Reactive[list[WorkItemRemoteLink] | None] = reactive(None)
    displayed_count: Reactive[int] = reactive(0)

    def __init__(self):
        super().__init__(id='work_item_remote_links')
        self._work_item_key: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#web-links'

    @property
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    @property
    def data_table(self) -> RemoteLinksDataTable | None:
        try:
            return self.query_one(RemoteLinksDataTable)
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True

    def show_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = True
            self.content_container.display = False

    def hide_loading(self) -> None:
        with self.app.batch_update():
            self.loading_container.display = False
            self.content_container.display = True

    async def action_add_remote_link(self) -> None:
        if self.work_item_key:
            await self.app.push_screen(RemoteLinkScreen(self.work_item_key), callback=self.add_link)

    def add_link(self, data: dict | None = None) -> None:
        if data:
            self.run_worker(self.create_link(data))

    async def create_link(self, data: dict) -> None:
        if not self.work_item_key:
            self.notify('Work item key is missing', severity='error')
            return

        link_url = data.get('link_url')
        link_title = data.get('link_title')

        if not link_url or not isinstance(link_url, str):
            self.notify('Missing or invalid link URL', severity='error')
            return
        if not link_title or not isinstance(link_title, str):
            self.notify('Missing or invalid link title', severity='error')
            return

        screen = cast('MainScreen', self.screen)  # noqa: F821
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

    async def fetch_remote_links(self, work_item_key: str) -> None:
        screen = cast('MainScreen', self.screen)  # noqa: F821
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
                if table := self.data_table:
                    await table.remove()
                self.hide_loading()
            return

        self.remote_links = response.result or []

    def watch_remote_links(self, links: list[WorkItemRemoteLink] | None) -> None:
        with self.app.batch_update():
            self.content_container.remove_children()

            if not links:
                self.hide_loading()
                self.displayed_count = 0
                return

            table = RemoteLinksDataTable(self._work_item_key or '')
            table.add_columns('Title', 'URL', 'Relationship', 'Status')

            link_count = 0
            for item in links:
                if not item.url:
                    continue

                if item.status_resolved is True:
                    status = 'Resolved'
                elif item.status_resolved is False:
                    status = 'Not Resolved'
                else:
                    status = ''

                table.add_row(
                    item.title or 'Untitled',
                    item.url,
                    item.relationship or '',
                    status,
                    key=item.id,
                )
                link_count += 1

            self.content_container.mount(table)
            self.hide_loading()
            self.displayed_count = link_count

    def watch_work_item_key(self, work_item_key: str | None = None) -> None:
        self._work_item_key = work_item_key
        self.remote_links = None

        if not work_item_key:
            self.loading_container.display = False
            self.content_container.display = True
            self.displayed_count = 0
            return

        self.show_loading()
        self.run_worker(self.fetch_remote_links(work_item_key))
