from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.containers import Container, Horizontal, VerticalGroup
from textual.reactive import Reactive, reactive
from textual.widgets import Static

from gojeera.internal.store.config import CONFIGURATION
from gojeera.widgets.search.work_item_search_results_controls import WorkItemSearchResultsControls
from gojeera.widgets.search.work_item_search_results_scroll import WorkItemSearchResultsScroll

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class WorkItemsContainer(Container):
    pagination: Reactive[dict | None] = reactive(None, always_update=True)
    displayed_count: Reactive[int] = reactive(0)
    is_loading: Reactive[bool] = reactive(False)
    search_active: Reactive[bool] = reactive(False)
    results_loaded: Reactive[bool] = reactive(False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = CONFIGURATION.get()
        self._clear_token = 0
        self._content_container: VerticalGroup | None = None
        self._controls: WorkItemSearchResultsControls | None = None
        self._footer: Static | None = None
        self._three_split_layout: Horizontal | None = None
        self._pending_footer_text: str = ''

    @property
    def content_container(self) -> VerticalGroup:
        if self._content_container is None:
            self._content_container = self.query_one('.tab-content-container', VerticalGroup)
        return self._content_container

    @property
    def controls(self) -> WorkItemSearchResultsControls:
        if self._controls is None:
            self._controls = self.query_one(WorkItemSearchResultsControls)
        return self._controls

    @property
    def footer(self) -> Static:
        if self._footer is None:
            self._footer = self.query_one('#work-items-page-footer', Static)
        return self._footer

    @property
    def three_split_layout(self) -> Horizontal:
        if self._three_split_layout is None:
            self._three_split_layout = self.screen.query_one('#three-split-layout', Horizontal)
        return self._three_split_layout

    def compose(self):
        yield WorkItemSearchResultsControls()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield WorkItemSearchResultsScroll()
        yield Static('', classes='work-items-section-spacer')
        yield Static('', id='work-items-page-footer')

    def on_mount(self) -> None:
        self.content_container.can_focus = False
        self.footer.can_focus = False
        self._apply_search_active_layout()
        self._apply_controls_visibility()

    def set_search_mode(self, mode: str, search_data: dict | None = None) -> None:
        self.controls.set_search_mode(mode, search_data)

    def show_loading(self) -> None:
        if self.search_active and self.is_loading:
            return
        self._clear_token += 1
        with self.app.batch_update():
            self.search_active = True
            self.is_loading = True

    def hide_loading(self) -> None:
        if not self.is_loading:
            return
        self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading
        unified_search_bar = cast('JiraApp', self.app).unified_search_bar
        if unified_search_bar.search_in_progress != loading:
            unified_search_bar.search_in_progress = loading

    def clear_search_metadata(self) -> None:
        self._pending_footer_text = ''
        self.footer.update('')

    def clear_search(self) -> None:
        self._clear_token += 1
        clear_token = self._clear_token

        with self.app.batch_update():
            self.pagination = None
            self.displayed_count = 0
            self.results_loaded = False
            self.search_active = False
        self.clear_search_metadata()
        self.call_after_refresh(lambda: self._schedule_deferred_clear(clear_token))

    def watch_search_active(self, _: bool) -> None:
        self._apply_search_active_layout()
        self._apply_controls_visibility()

    def _apply_search_active_layout(self) -> None:
        is_search_active = self.search_active

        if self.display != is_search_active:
            self.display = is_search_active
        if self.can_focus != is_search_active:
            self.can_focus = is_search_active

        is_search_inactive = not is_search_active
        if self.three_split_layout.has_class('-search-inactive') != is_search_inactive:
            self.three_split_layout.set_class(is_search_inactive, '-search-inactive')

    def _apply_controls_visibility(self) -> None:
        controls_visible = self.search_active and self.results_loaded
        if self.controls.display != controls_visible:
            self.controls.display = controls_visible

    def watch_results_loaded(self, _: bool) -> None:
        self._apply_controls_visibility()
        self._apply_footer_text()

    def _apply_footer_text(self) -> None:
        footer_text = self._pending_footer_text if self.results_loaded else ''
        self.footer.update(footer_text)

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
                    self._pending_footer_text = ''
                else:
                    total_pages = total_results // self.config.search_results_per_page
                    if (total_results % self.config.search_results_per_page) > 0:
                        total_pages += 1
                    self.result_subtitle = (
                        f'Page {current_page_number} of {total_pages} (total: {total_results})'
                    )
                    self._pending_footer_text = (
                        f'{current_page_number}/{total_pages} ({total_results})'
                    )
            else:
                self.result_subtitle = f'Page {current_page_number}'
                self._pending_footer_text = f'{current_page_number}/{current_page_number}'
        else:
            self._pending_footer_text = ''
        self._apply_footer_text()
