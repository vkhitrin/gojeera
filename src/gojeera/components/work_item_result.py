import logging
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.binding import Binding
from textual.containers import (
    Center,
    Container,
    Horizontal,
    Vertical,
    VerticalGroup,
    VerticalScroll,
)
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator, Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, JiraWorkItemSearchResponse
from gojeera.utils.urls import build_external_url_for_work_item

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class WorkItemContainer(Vertical, can_focus=False):
    """A container for displaying work items."""

    DEFAULT_CSS = """
    WorkItemContainer {
        height: auto;
        padding: 1 1;
        margin: 0;
        background: $surface;
        color: $foreground;
    }
    
    WorkItemContainer.-selected {
        background: $accent-muted;
        color: $text-accent;
    }
    
    WorkItemContainer.-loaded {
        background: $primary-muted;
        color: $text-primary;
    }
    
    WorkItemContainer.-loaded.-selected {
        background: $primary-darken-3;
        color: $text-muted;
    }
    """

    def __init__(self, work_item: JiraWorkItem):
        super().__init__()
        self.work_item = work_item
        self.work_item_key = work_item.key
        self.work_item_id = work_item.id

    async def on_click(self, event) -> None:
        event.stop()

        parent = self.parent
        if isinstance(parent, WorkItemSearchResultsScroll):
            containers = parent.work_item_containers
            for i, container in enumerate(containers):
                if container.work_item_key == self.work_item_key:
                    parent._selected_index = i
                    parent._update_selection()
                    await parent._select_work_item(self.work_item_key)
                    break

    def compose(self):
        work_item_summary = self.work_item.cleaned_summary(
            CONFIGURATION.get().search_results_truncate_work_item_summary
        )

        priority_name = self.work_item.priority_name

        work_item_type = self.work_item.work_item_type_name

        project_key = self.work_item.key

        assignee_name = self.work_item.assignee_display_name

        with Vertical():
            with Horizontal(classes='work-item-row-1'):
                yield Static(Text(f'[{work_item_type}]'), classes='work-item-type')
                yield Static(Text(project_key), classes='work-item-key')

            yield Static(Text(work_item_summary), classes='work-item-summary')

            with Horizontal(classes='work-item-row-3'):
                if priority_name:
                    yield Static(Text(priority_name), classes='work-item-priority')
                if assignee_name:
                    yield Static(Text(assignee_name), classes='work-item-assignee')


class WorkItemSearchResultsScroll(VerticalScroll):
    """A VerticalScroll widget that displays work item search results."""

    work_item_search_results: Reactive[JiraWorkItemSearchResponse | None] = reactive(
        None, always_update=True
    )

    BINDINGS = [
        Binding('j', 'cursor_down', 'Next item', show=False),
        Binding('k', 'cursor_up', 'Previous item', show=False),
        Binding('down', 'cursor_down', 'Next item', show=False),
        Binding('up', 'cursor_up', 'Previous item', show=False),
        Binding('enter', 'select_work_item', 'Select item', show=False),
        Binding(
            key='h',
            action='previous_work_items_page',
            description='Previous Page',
            show=True,
            tooltip='Previous Page',
        ),
        Binding(
            key='l',
            action='next_work_items_page',
            description='Next Page',
            show=True,
            tooltip='Next Page',
        ),
        Binding(
            key='ctrl+o',
            action='open_work_item_in_browser',
            description='Browse',
            show=True,
            tooltip='Open item in the browser',
        ),
        Binding(
            key='ctrl+b',
            action='clone_work_item',
            description='Clone',
            show=True,
            tooltip='Clone the selected work item',
        ),
        Binding(
            key='ctrl+k',
            action='copy_work_item_key',
            description='Copy Key',
            show=True,
            tooltip='Copy the work item key',
        ),
        Binding(
            key='ctrl+l',
            action='copy_work_item_url',
            description='Copy URL',
            show=True,
            tooltip='Copy the work item URL',
        ),
    ]

    def __init__(self):
        super().__init__(id='work_item_search_results')

        self.token_by_page: dict[int, str] = {}
        self.page = 1
        self.total_pages = 1
        self.current_work_item_key: str | None = None
        self._selected_index: int = 0

        self.display = False

    @property
    def work_item_containers(self) -> list[WorkItemContainer]:
        return list(self.query(WorkItemContainer))

    @property
    def selected_work_item(self) -> WorkItemContainer | None:
        containers = self.work_item_containers
        if containers and 0 <= self._selected_index < len(containers):
            return containers[self._selected_index]
        return None

    def _update_selection(self) -> None:
        containers = self.work_item_containers
        for i, container in enumerate(containers):
            if i == self._selected_index:
                container.add_class('-selected')

                self.current_work_item_key = container.work_item_key
            else:
                container.remove_class('-selected')

    def action_cursor_down(self) -> None:
        containers = self.work_item_containers
        if containers:
            self._selected_index = min(self._selected_index + 1, len(containers) - 1)
            self._update_selection()

            if selected := self.selected_work_item:
                self.scroll_to_widget(selected, animate=False)

    def action_cursor_up(self) -> None:
        containers = self.work_item_containers
        if containers:
            self._selected_index = max(self._selected_index - 1, 0)
            self._update_selection()

            if selected := self.selected_work_item:
                self.scroll_to_widget(selected, animate=False)

    def reset_selection(self) -> None:
        self._selected_index = 0
        self._update_selection()

    def scroll_to_top(self, animate: bool = False) -> None:
        self.scroll_home(animate=animate)

    async def action_select_work_item(self) -> None:
        if selected := self.selected_work_item:
            await self._select_work_item(selected.work_item_key)
        else:
            self.notify('No work item selected', severity='warning', title='Search Results')

    async def watch_work_item_search_results(
        self, response: JiraWorkItemSearchResponse | None = None
    ) -> None:
        if response is None:
            with self.app.batch_update():
                for container in self.query(WorkItemContainer):
                    await container.remove()
                self.display = False

                if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                    self.parent.parent.displayed_count = 0
            return

        if not response.work_items:
            with self.app.batch_update():
                for container in self.query(WorkItemContainer):
                    await container.remove()
                self.display = False

                if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                    self.parent.parent.displayed_count = 0
            return

        with self.app.batch_update():
            old_containers = list(self.query(WorkItemContainer))
            for container in old_containers:
                await container.remove()

            self.display = True

            if response.next_page_token:
                self.token_by_page[self.page + 1] = response.next_page_token

            for work_item in response.work_items:
                container = WorkItemContainer(work_item)

                if work_item.key == self.current_work_item_key:
                    container.add_class('-loaded')
                await self.mount(container)

            if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                self.parent.parent.displayed_count = len(response.work_items)

            self.reset_selection()

    def mark_loaded_work_item(self, work_item_key: str) -> None:
        for container in self.work_item_containers:
            container.remove_class('-loaded')

        for container in self.work_item_containers:
            if container.work_item_key == work_item_key:
                container.add_class('-loaded')
                break

    async def update_work_item_in_list(self, updated_work_item: JiraWorkItem) -> None:
        for container in self.work_item_containers:
            if container.work_item_key == updated_work_item.key:
                container.work_item = updated_work_item

                try:
                    summary_widgets = container.query('.work-item-summary')
                    if summary_widgets:
                        summary_widget = summary_widgets.first(Static)
                        work_item_summary = updated_work_item.cleaned_summary(
                            CONFIGURATION.get().search_results_truncate_work_item_summary
                        )
                        summary_widget.update(Text(work_item_summary))

                    row3_containers = container.query('.work-item-row-3')
                    if row3_containers:
                        priority_widgets = container.query('.work-item-priority')
                        assignee_widgets = container.query('.work-item-assignee')

                        priority_name = updated_work_item.priority_name
                        assignee_name = updated_work_item.assignee_display_name

                        priority_exists = len(priority_widgets) > 0
                        assignee_exists = len(assignee_widgets) > 0

                        structure_changed = (
                            (priority_exists and not priority_name)
                            or (not priority_exists and priority_name)
                            or (assignee_exists and not assignee_name)
                            or (not assignee_exists and assignee_name)
                        )

                        if structure_changed:
                            await container.remove_children()
                            await container.recompose()
                        else:
                            if priority_widgets and priority_name:
                                priority_widget = priority_widgets.first(Static)
                                priority_widget.update(Text(priority_name))

                            if assignee_widgets and assignee_name:
                                assignee_widget = assignee_widgets.first(Static)
                                assignee_widget.update(Text(assignee_name))

                except Exception:
                    await container.remove_children()
                    await container.recompose()

                break

    async def on_click(self, event) -> None:
        for i, container in enumerate(self.work_item_containers):
            if container.region and container.region.contains(event.x, event.y):
                self._selected_index = i
                self._update_selection()

                await self._select_work_item(container.work_item_key)
                break

    async def _select_work_item(self, work_item_key: str) -> None:
        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        self.current_work_item_key = work_item_key

        self.mark_loaded_work_item(work_item_key)

        self.run_worker(screen.fetch_work_items(work_item_key), exclusive=True)

    def action_open_work_item_in_browser(self) -> None:
        if self.current_work_item_key:
            if url := build_external_url_for_work_item(
                self.current_work_item_key,
                cast('JiraApp', self.app),  # noqa: F821
            ):
                self.notify('Opening Work Item in the browser...', title='Search Results')
                self.app.open_url(url)

    def action_clone_work_item(self) -> None:
        if not self.current_work_item_key:
            self.notify('No work item selected', severity='warning', title='Search Results')
            return

        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        self.run_worker(screen.clone_work_item(self.current_work_item_key))

    def action_copy_work_item_key(self) -> None:
        if self.current_work_item_key:
            self.app.copy_to_clipboard(self.current_work_item_key)
            self.notify('Key copied to clipboard', title=self.current_work_item_key)

    def action_copy_work_item_url(self) -> None:
        if self.current_work_item_key:
            if url := build_external_url_for_work_item(
                self.current_work_item_key,
                cast('JiraApp', self.app),  # noqa: F821
            ):
                self.app.copy_to_clipboard(url)
                self.notify('URL copied to clipboard', title=self.current_work_item_key)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'previous_work_items_page':
            if self.page > 1:
                return True
            return False
        if action == 'next_work_items_page':
            if self.token_by_page.get(self.page + 1):
                return True
            if self.page < self.total_pages:
                return True
            return False
        return True

    def action_previous_work_items_page(self):
        if self.page > 1:
            next_page_token = self.token_by_page.get(self.page - 1)
            self.page -= 1

            self.scroll_to_top(animate=False)

            from gojeera.app import MainScreen

            screen = cast(MainScreen, self.screen)
            self.run_worker(
                screen.search_work_items(
                    next_page_token,
                    page=self.page,
                    use_active_search=True,
                ),
                exclusive=True,
            )
            self.refresh_bindings()

    def action_next_work_items_page(self):
        next_page_token = self.token_by_page.get(self.page + 1)
        self.page += 1

        self.scroll_to_top(animate=False)

        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        self.run_worker(
            screen.search_work_items(next_page_token, page=self.page, use_active_search=True),
            exclusive=True,
        )
        self.refresh_bindings()


class WorkItemsContainer(Container):
    pagination: Reactive[dict | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = CONFIGURATION.get()

    @property
    def loading_container(self) -> Center:
        return self.query_one('.tab-loading-container', Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    def compose(self):
        """Compose the search results container with loading indicator."""
        yield Static('', id='work-items-total-header')
        with Center(classes='tab-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield WorkItemSearchResultsScroll()
        yield Static('', id='work-items-page-footer')

    def on_mount(self) -> None:
        self.loading_container.can_focus = False
        self.content_container.can_focus = False
        self.query_one('#work-items-total-header', Static).can_focus = False
        self.query_one('#work-items-page-footer', Static).can_focus = False

        if CONFIGURATION.get().jumper.enabled:
            self.query_one(WorkItemSearchResultsScroll).jump_mode = 'focus'  # type: ignore[attr-defined]

    def show_loading(self) -> None:
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        self.loading_container.display = False
        self.content_container.display = True

    def clear_search_metadata(self) -> None:
        self.query_one('#work-items-total-header', Static).update('')
        self.query_one('#work-items-page-footer', Static).update('')

    def watch_pagination(self, response: dict) -> None:
        if response:
            current_page_number = max(1, response.get('current_page_number') or 1)
            if (total_results := response.get('total', 0)) is not None:
                if total_results == 0:
                    self.result_subtitle = None
                    if header := self.query_one('#work-items-total-header', Static):
                        header.update('No items found')
                    if footer := self.query_one('#work-items-page-footer', Static):
                        footer.update('')
                else:
                    total_pages = total_results // self.config.search_results_per_page
                    if (total_results % self.config.search_results_per_page) > 0:
                        total_pages += 1
                    self.result_subtitle = (
                        f'Page {current_page_number} of {total_pages} (total: {total_results})'
                    )
                    if header := self.query_one('#work-items-total-header', Static):
                        header.update(f'{total_results} Work Items')
                    if footer := self.query_one('#work-items-page-footer', Static):
                        footer.update(f'Page {current_page_number} of {total_pages}')
            else:
                self.result_subtitle = f'Page {current_page_number}'
                if header := self.query_one('#work-items-total-header', Static):
                    header.update('')
                if footer := self.query_one('#work-items-page-footer', Static):
                    footer.update(f'Page {current_page_number}')
