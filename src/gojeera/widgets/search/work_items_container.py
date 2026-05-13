from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalGroup
from textual.events import Key
from textual.reactive import Reactive, reactive
from textual.widgets import Button, Input, Static

from gojeera.internal.store.config import CONFIGURATION
from gojeera.widgets.inputs.extended_input import ExtendedInput, allow_digit_only_key_input
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.search.work_item_search_results_controls import WorkItemSearchResultsControls
from gojeera.widgets.search.work_item_search_results_scroll import WorkItemSearchResultsScroll

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class SearchResultsPageInput(ExtendedInput):
    def __init__(self) -> None:
        super().__init__(
            id='work-items-page-input',
            classes='surface-input',
            compact=True,
            type='integer',
            value='1',
        )

    def on_key(self, event: Key) -> None:
        if allow_digit_only_key_input(event):
            return
        event.prevent_default()

    def _watch_selection(self, selection) -> None:
        super()._watch_selection(selection)
        self.set_scroll(0, 0)

    def _watch_value(self, value: str) -> None:
        super()._watch_value(value)
        self.set_scroll(0, 0)


class WorkItemsContainer(Container):
    DEFAULT_CSS = """
    WorkItemsContainer > #work-items-page-footer-row {
        height: auto;
        width: 100%;
        layout: grid;
        grid-size: 4;
        grid-columns: 3 auto auto 3;
        grid-gutter: 1;
        align: center middle;
        padding: 0;
        margin: 0;
    }

    WorkItemsContainer > #work-items-page-footer-row > Button {
        min-width: 3;
        width: 3;
        padding: 0;
        margin: 0;
    }

    WorkItemsContainer > #work-items-page-footer-row > #work-items-page-footer {
        width: auto;
        min-width: 0;
        content-align: center middle;
        text-align: left;
        padding: 0;
    }

    WorkItemsContainer > #work-items-page-footer-row > #work-items-page-input {
        width: auto;
        min-width: 1;
        height: 1;
        text-align: right;
        padding: 0;
    }
    """

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
        self._footer_row: Horizontal | None = None
        self._previous_page_button: Button | None = None
        self._next_page_button: Button | None = None
        self._page_input: SearchResultsPageInput | None = None
        self._search_results: WorkItemSearchResultsScroll | None = None
        self._three_split_layout: Horizontal | None = None
        self._pending_footer_suffix_text: str = ''
        self._last_valid_page_input_value: str = '1'
        self._page_input_width: int | None = None
        self._current_page_number: int = 1
        self._total_pages: int = 1

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
    def page_input(self) -> SearchResultsPageInput:
        if self._page_input is None:
            self._page_input = self.query_one('#work-items-page-input', SearchResultsPageInput)
        return self._page_input

    @property
    def footer_row(self) -> Horizontal:
        if self._footer_row is None:
            self._footer_row = self.query_one('#work-items-page-footer-row', Horizontal)
        return self._footer_row

    @property
    def previous_page_button(self) -> Button:
        if self._previous_page_button is None:
            self._previous_page_button = self.query_one('#work-items-previous-page-button', Button)
        return self._previous_page_button

    @property
    def next_page_button(self) -> Button:
        if self._next_page_button is None:
            self._next_page_button = self.query_one('#work-items-next-page-button', Button)
        return self._next_page_button

    @property
    def search_results(self) -> WorkItemSearchResultsScroll:
        if self._search_results is None:
            self._search_results = self.query_one(WorkItemSearchResultsScroll)
        return self._search_results

    @property
    def three_split_layout(self) -> Horizontal:
        if self._three_split_layout is None:
            self._three_split_layout = self.screen.query_one('#three-split-layout', Horizontal)
        return self._three_split_layout

    def compose(self) -> ComposeResult:
        yield WorkItemSearchResultsControls()
        with VerticalGroup(classes='tab-content-container') as content:
            content.display = True
            yield WorkItemSearchResultsScroll()
        yield Static('', classes='work-items-section-spacer')
        with Horizontal(id='work-items-page-footer-row') as footer_row:
            footer_row.display = False
            yield Button(
                '←',
                id='work-items-previous-page-button',
                classes='search-results-action-button',
                compact=True,
            )
            yield SearchResultsPageInput()
            yield Static('', id='work-items-page-footer')
            yield Button(
                '→',
                id='work-items-next-page-button',
                classes='search-results-action-button',
                compact=True,
            )

    def on_mount(self) -> None:
        self.content_container.can_focus = False
        self.footer.can_focus = False
        self.footer_row.can_focus = False
        self.page_input.can_focus = True
        set_jump_mode(self.previous_page_button, 'click')
        set_jump_mode(self.page_input, 'focus')
        set_jump_mode(self.next_page_button, 'click')
        self._apply_search_active_layout()
        self._apply_controls_visibility()
        self._update_pagination_buttons()

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

    def clear_search_metadata(self) -> None:
        self._pending_footer_suffix_text = ''
        self._last_valid_page_input_value = '1'
        self._page_input_width = None
        self._current_page_number = 1
        self._total_pages = 1
        self.page_input.value = '1'
        self.footer.update('')
        self._update_pagination_buttons()

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
        if self.footer_row.display != controls_visible:
            self.footer_row.display = controls_visible

    def watch_results_loaded(self, _: bool) -> None:
        self._apply_controls_visibility()
        self._apply_footer_text()
        self._update_pagination_buttons()

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading
        unified_search_bar = cast('JiraApp', self.app).unified_search_bar
        if unified_search_bar.search_in_progress != loading:
            unified_search_bar.search_in_progress = loading
        self._update_pagination_buttons()

    def _apply_footer_text(self) -> None:
        if self.results_loaded:
            self._last_valid_page_input_value = str(self._current_page_number)
            self.page_input.value = self._last_valid_page_input_value
            self.footer.update(self._pending_footer_suffix_text)
        else:
            self._last_valid_page_input_value = '1'
            self.page_input.value = '1'
            self.footer.update('')

    def _update_pagination_buttons(self) -> None:
        has_results = self.search_active and self.results_loaded
        disable_previous = not has_results or self.is_loading or self._current_page_number <= 1
        disable_next = (
            not has_results or self.is_loading or self._current_page_number >= self._total_pages
        )

        self.previous_page_button.disabled = disable_previous
        self.next_page_button.disabled = disable_next
        self.page_input.disabled = not has_results or self.is_loading
        page_input_width = max(1, len(str(self._total_pages)))
        if self._page_input_width != page_input_width:
            self.page_input.set_styles(
                f'width: {page_input_width}; min-width: {page_input_width}; max-width: {page_input_width};'
            )
            self._page_input_width = page_input_width

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
            total_pages = current_page_number
            if (total_results := response.get('total', 0)) is not None:
                if total_results == 0:
                    self.result_subtitle = None
                    self._pending_footer_suffix_text = ''
                    total_pages = 1
                else:
                    total_pages = total_results // self.config.search_results_per_page
                    if (total_results % self.config.search_results_per_page) > 0:
                        total_pages += 1
                    self.result_subtitle = (
                        f'Page {current_page_number} of {total_pages} (total: {total_results})'
                    )
                    self._pending_footer_suffix_text = f'/{total_pages} ({total_results})'
            else:
                self.result_subtitle = f'Page {current_page_number}'
                self._pending_footer_suffix_text = f'/{current_page_number}'
            self._current_page_number = current_page_number
            self._total_pages = max(1, total_pages)
        else:
            self._pending_footer_suffix_text = ''
            self._current_page_number = 1
            self._total_pages = 1
        self._apply_footer_text()
        self._update_pagination_buttons()

    @on(Input.Submitted, '#work-items-page-input')
    def handle_page_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.disabled:
            return
        requested_page = self._validated_requested_page(event.value)
        self.page_input.value = str(self._current_page_number)
        if requested_page is None or requested_page == self._current_page_number:
            return
        self.search_results._request_work_items_page(requested_page)

    @on(Input.Changed, '#work-items-page-input')
    def handle_page_input_changed(self, event: Input.Changed) -> None:
        if event.input.disabled:
            return
        stripped = event.value.strip()
        if not stripped:
            return
        try:
            requested_page = int(stripped)
        except ValueError:
            with self.prevent(Input.Changed):
                self.page_input.value = self._last_valid_page_input_value
            self.page_input.cursor_position = len(self.page_input.value)
            return
        if requested_page < 1 or requested_page > self._total_pages:
            with self.prevent(Input.Changed):
                self.page_input.value = self._last_valid_page_input_value
            self.page_input.cursor_position = len(self.page_input.value)
            return
        self._last_valid_page_input_value = stripped

    def _validated_requested_page(self, value: str) -> int | None:
        stripped = value.strip()
        if not stripped:
            return None
        try:
            requested_page = int(stripped)
        except ValueError:
            return None
        if requested_page < 1 or requested_page > self._total_pages:
            return None
        return requested_page

    @on(Button.Pressed, '#work-items-previous-page-button')
    def handle_previous_page_pressed(self) -> None:
        self.search_results.action_previous_page()

    @on(Button.Pressed, '#work-items-next-page-button')
    def handle_next_page_pressed(self) -> None:
        self.search_results.action_next_page()
