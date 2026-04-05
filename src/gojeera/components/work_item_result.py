import logging
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    VerticalGroup,
    VerticalScroll,
)
from textual.reactive import Reactive, reactive
from textual.widgets import Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, JiraWorkItemSearchResponse
from gojeera.utils.urls import build_external_url_for_work_item

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class WorkItemContainer(Static, can_focus=False):
    """A lightweight, single-widget rendering of a work item card."""

    DEFAULT_CSS = """
    WorkItemContainer {
        height: auto;
        padding: 1 1;
        margin: 0 0 1 0;
        background: $surface;
        color: $foreground;
    }
    
    WorkItemContainer.-selected {
        background: $surface-lighten-1;
        color: $foreground;
    }
    
    WorkItemContainer.-loaded {
        background: $surface-darken-1;
        color: $foreground;
    }
    
    WorkItemContainer.-loaded.-selected {
        background: $primary-muted;
        color: $foreground;
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

    def _render_footer_line(
        self, priority_name: str | None, assignee_name: str | None, meta_style: str
    ) -> Text | None:
        if not priority_name and not assignee_name:
            return None

        footer = Text()
        available_width = self.content_region.width or self.size.width or 0

        if not assignee_name:
            footer.append(priority_name or '', style=meta_style)
            return footer

        if not priority_name:
            if available_width > 0:
                right_padding = max(0, available_width - len(assignee_name))
                footer.append(' ' * right_padding, style=meta_style)
            footer.append(assignee_name, style=meta_style)
            return footer

        if available_width <= 0:
            footer.append(priority_name, style=meta_style)
            footer.append('  ', style=meta_style)
            footer.append(assignee_name, style=meta_style)
            return footer

        minimum_gap = 2
        assignee_width = len(assignee_name)

        if assignee_width >= available_width:
            assignee = Text(assignee_name, style=meta_style)
            assignee.truncate(available_width, overflow='ellipsis')
            return assignee

        available_for_priority = max(0, available_width - assignee_width - minimum_gap)
        priority = Text(priority_name, style=meta_style)
        priority.truncate(available_for_priority, overflow='ellipsis')

        footer.append_text(priority)
        gap = max(minimum_gap, available_width - priority.cell_len - assignee_width)
        footer.append(' ' * gap, style=meta_style)
        footer.append(assignee_name, style=meta_style)
        return footer

    def render(self) -> Text:
        work_item_summary = self.work_item.cleaned_summary(
            CONFIGURATION.get().search_results_truncate_work_item_summary
        )
        work_item_type = self.work_item.work_item_type_name
        priority_name = self.work_item.priority_name
        assignee_name = self.work_item.assignee_display_name

        is_selected = self.has_class('-selected')
        is_loaded = self.has_class('-loaded')

        summary_style = 'bold white' if is_selected or is_loaded else 'white'
        meta_style = 'bold white' if is_selected and is_loaded else 'bright_black'

        rendered = Text()
        rendered.append(f'[{work_item_type}] ', style=meta_style)
        rendered.append(self.work_item.key, style=meta_style)
        rendered.append('\n')
        rendered.append(work_item_summary, style=summary_style)

        footer_line = self._render_footer_line(priority_name, assignee_name, meta_style)
        if footer_line is not None:
            rendered.append('\n')
            rendered.append_text(footer_line)

        return rendered


class WorkItemSearchResultsScroll(VerticalScroll):
    """A VerticalScroll widget that displays work item search results."""

    jump_mode: ClassVar[str | None] = 'focus'
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
            key='p',
            action='previous_work_items_page',
            description='Previous Page',
            show=False,
        ),
        Binding(
            key='n',
            action='next_work_items_page',
            description='Next Page',
            show=False,
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
            key='ctrl+y',
            action='copy_work_item_key',
            description='Copy Key',
            show=True,
            tooltip='Copy the work item key',
        ),
        Binding(
            key='ctrl+u',
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
        self.pending_page: int | None = None
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
            container.refresh(layout=False)

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

    async def clear_results(self) -> None:
        await self.remove_children()
        self.display = False
        self.token_by_page = {}
        self.page = 1
        self.pending_page = None
        self.total_pages = 1
        self.current_work_item_key = None
        self._selected_index = 0

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
                await self.remove_children()
                self.display = False

                if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                    self.parent.parent.displayed_count = 0
            return

        if not response.work_items:
            with self.app.batch_update():
                await self.remove_children()
                self.display = False

                if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                    self.parent.parent.displayed_count = 0
            return

        with self.app.batch_update():
            await self.remove_children()

            self.display = True

            if response.next_page_token:
                next_page = self.page + 1
                self.token_by_page[next_page] = response.next_page_token

            items_to_mount: list[WorkItemContainer] = []
            for work_item in response.work_items:
                container = WorkItemContainer(work_item)

                if work_item.key == self.current_work_item_key:
                    container.add_class('-loaded')
                items_to_mount.append(container)

            await self.mount(*items_to_mount)

            if self.parent and isinstance(self.parent.parent, WorkItemsContainer):
                self.parent.parent.displayed_count = len(response.work_items)

            self.reset_selection()

    def mark_loaded_work_item(self, work_item_key: str) -> None:
        for container in self.work_item_containers:
            container.remove_class('-loaded')
            container.refresh(layout=False)

        for container in self.work_item_containers:
            if container.work_item_key == work_item_key:
                container.add_class('-loaded')
                container.refresh(layout=False)
                break

    async def update_work_item_in_list(self, updated_work_item: JiraWorkItem) -> None:
        for container in self.work_item_containers:
            if container.work_item_key == updated_work_item.key:
                container.work_item = updated_work_item
                container.refresh()
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
        if screen.current_loaded_work_item_key == work_item_key:
            return

        self.current_work_item_key = work_item_key

        self.mark_loaded_work_item(work_item_key)

        screen.run_worker(screen.fetch_work_items(work_item_key), exclusive=True, group='work-item')

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
        work_items_container = self.parent.parent if self.parent else None
        is_loading = isinstance(work_items_container, WorkItemsContainer) and (
            work_items_container.is_loading
        )

        if is_loading and action in {'previous_work_items_page', 'next_work_items_page'}:
            return False

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
            requested_page = self.page - 1
            next_page_token = self.token_by_page.get(requested_page)
            self.pending_page = requested_page

            self.scroll_to_top(animate=False)

            from gojeera.app import MainScreen

            screen = cast(MainScreen, self.screen)
            screen.begin_search_request(page_number=requested_page)
            self.run_worker(
                screen.search_work_items(
                    next_page_token,
                    page=requested_page,
                    use_active_search=True,
                ),
                exclusive=True,
                group='search',
            )
            self.refresh_bindings()

    def action_next_work_items_page(self):
        requested_page = self.page + 1
        next_page_token = self.token_by_page.get(requested_page)
        self.pending_page = requested_page

        self.scroll_to_top(animate=False)

        from gojeera.app import MainScreen

        screen = cast(MainScreen, self.screen)
        screen.begin_search_request(page_number=requested_page)
        self.run_worker(
            screen.search_work_items(
                next_page_token,
                page=requested_page,
                use_active_search=True,
            ),
            exclusive=True,
            group='search',
        )
        self.refresh_bindings()


class WorkItemsContainer(Container):
    pagination: Reactive[dict | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False, always_update=True)
    search_active: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = CONFIGURATION.get()
        self._clear_token = 0

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('.tab-content-container', VerticalGroup)

    def compose(self):
        """Compose the search results container."""
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield WorkItemSearchResultsScroll()
        yield Static('', classes='work-items-section-spacer')
        yield Static('', id='work-items-page-footer')

    def on_mount(self) -> None:
        self.content_container.can_focus = False
        self.query_one('#work-items-page-footer', Static).can_focus = False
        self._sync_search_layout()

    def show_loading(self) -> None:
        self._clear_token += 1
        self.search_active = True
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading

    def clear_search_metadata(self) -> None:
        self.query_one('#work-items-page-footer', Static).update('')

    def clear_search(self) -> None:
        self._clear_token += 1
        clear_token = self._clear_token

        self.pagination = None
        self.displayed_count = 0
        self.clear_search_metadata()
        self.search_active = False
        self.call_after_refresh(lambda: self._schedule_deferred_clear(clear_token))

    def watch_search_active(self, _: bool) -> None:
        self._sync_search_layout()

    def _sync_search_layout(self) -> None:
        self.display = self.search_active
        self.can_focus = self.search_active

        layout = self.screen.query_one('#three-split-layout', Horizontal)
        layout.set_class(not self.search_active, '-search-inactive')

    def _schedule_deferred_clear(self, clear_token: int) -> None:
        if clear_token != self._clear_token:
            return
        self.run_worker(self._deferred_clear_results(clear_token), exclusive=False)

    async def _deferred_clear_results(self, clear_token: int) -> None:
        if clear_token != self._clear_token:
            return

        search_results = self.query_one(WorkItemSearchResultsScroll)
        await search_results.clear_results()

    def watch_pagination(self, response: dict) -> None:
        if response:
            current_page_number = max(1, response.get('current_page_number') or 1)
            if (total_results := response.get('total', 0)) is not None:
                if total_results == 0:
                    self.result_subtitle = None
                    if footer := self.query_one('#work-items-page-footer', Static):
                        footer.update('')
                else:
                    total_pages = total_results // self.config.search_results_per_page
                    if (total_results % self.config.search_results_per_page) > 0:
                        total_pages += 1
                    self.result_subtitle = (
                        f'Page {current_page_number} of {total_pages} (total: {total_results})'
                    )
                    if footer := self.query_one('#work-items-page-footer', Static):
                        footer.update(f'{current_page_number}/{total_pages} ({total_results})')
            else:
                self.result_subtitle = f'Page {current_page_number}'
                if footer := self.query_one('#work-items-page-footer', Static):
                    footer.update(f'{current_page_number}/{current_page_number}')
