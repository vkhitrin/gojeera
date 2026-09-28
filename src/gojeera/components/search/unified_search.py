from __future__ import annotations

import asyncio
import logging
from threading import Event
from typing import TYPE_CHECKING, Any, cast

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Input, Select
from textual.worker import Worker, WorkerCancelled, get_current_worker

from gojeera.internal.models.jira import JiraFilterDict
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.jira.jql import text_search_jql
from gojeera.utils.jira.urls import extract_work_item_key
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.selection.lazy_select import LazySelect
from gojeera.widgets.selection.popup_menu import PopupMenu, PopupMenuItem
from gojeera.widgets.selection.vim_select import VimSelect

if TYPE_CHECKING:
    from gojeera.app import JiraApp
    from gojeera.internal.jira.controller import APIController
    from gojeera.internal.models.jira import WorkItemStatus
    from gojeera.widgets.search.search_autocomplete import SearchAutoComplete

logger = logging.getLogger('gojeera')
EMPTY_REMOTE_FILTER_CACHE_TTL_SECONDS = 120


class UnifiedSearchBar(Container):
    """Unified search bar widget with mode selection and dynamic content based on mode."""

    class ProfileIsReady(Message):
        def __init__(self, account_id: str) -> None:
            self.account_id = account_id
            super().__init__()

    search_mode: reactive[str] = reactive('basic')
    projects: reactive[dict | None] = reactive(None)
    users: reactive[dict | None] = reactive(None)
    statuses: reactive[list[tuple[str, str]] | None] = reactive(None)
    types: reactive[list[tuple[str, str]] | None] = reactive(None)
    search_in_progress: reactive[bool] = reactive(False)

    def __init__(self, api: APIController, **kwargs):
        classes = kwargs.pop('classes', None)
        initial_classes = f'{classes} mode-basic' if classes else 'mode-basic'
        super().__init__(classes=initial_classes, **kwargs)
        self.api = api
        self.search_modes = [
            ('Basic', 'basic'),
            ('Text', 'text'),
            ('JQL', 'jql'),
        ]

        self._selected_project_key: str | None = None

        self._users_fetched_for_project: str | None = None
        self._statuses_fetched_for_project: str | None = None
        self._types_fetched_for_project: str | None = None

        self._cache = get_cache()

        self._jql_autocomplete: SearchAutoComplete | None = None
        self._search_history_autocomplete: SearchAutoComplete | None = None
        self._work_item_key: str | None = None
        self._account_id: str | None = None
        self._remote_filters: list[JiraFilterDict] | None = None
        self._remote_filters_fetch_requested = False
        self._remote_filters_generation = 0
        self._remote_filters_context: tuple[str, str | None, bool, bool, bool] | None = None
        self._remote_filters_worker: Worker[Any] | None = None
        self._remote_filters_cache_write_failed = False
        self.remote_filter_revision = 0
        self._remote_filters_fetched = not CONFIGURATION.get().fetch_remote_filters.enabled
        self._create_work_item_menu: PopupMenu | None = None
        self._last_results_controls_state: tuple[str, bool] | None = None

    @staticmethod
    def _set_widget_display(widget, visible: bool) -> None:
        if widget.display != visible:
            widget.display = visible

    @staticmethod
    def _set_invalid_class(widget: Input, invalid: bool) -> None:
        if widget.has_class('-invalid') != invalid:
            widget.set_class(invalid, '-invalid')

    @property
    def mode_selector(self) -> VimSelect:
        return self.query_one('#search-mode-selector', VimSelect)

    @property
    def project_selector(self) -> LazySelect:
        return self.query_one('#basic-project-selector', LazySelect)

    @property
    def assignee_selector(self) -> LazySelect:
        return self.query_one('#basic-assignee-selector', LazySelect)

    @property
    def type_selector(self) -> LazySelect:
        return self.query_one('#basic-type-selector', LazySelect)

    @property
    def status_selector(self) -> LazySelect:
        return self.query_one('#basic-status-selector', LazySelect)

    @property
    def unified_input(self) -> Input:
        return self.query_one('#unified-search-input', Input)

    @property
    def create_work_item_button(self) -> Button:
        return self.query_one('#unified-search-new-work-item-button', Button)

    @property
    def search_button(self) -> Button:
        return self.query_one('#unified-search-button', Button)

    def compose(self) -> ComposeResult:
        yield VimSelect(
            options=[(label, value) for label, value in self.search_modes],
            prompt='',
            id='search-mode-selector',
            value='basic',
            allow_blank=False,
            compact=True,
        )

        with Container(id='unified-search-new-work-item-menu-anchor'):
            yield Button(
                '+',
                id='unified-search-new-work-item-button',
                classes='action-button-chrome icon-action-button',
                compact=True,
            )
            menu = self._build_create_work_item_menu()
            self._create_work_item_menu = menu
            yield menu

        yield LazySelect(
            lazy_load_callback=lambda: self.fetch_projects(),
            options=[],
            prompt='Project',
            id='basic-project-selector',
            type_to_search=True,
            compact=True,
        )
        yield LazySelect(
            lazy_load_callback=lambda: self._lazy_load_assignees(),
            options=[],
            prompt='Assignee',
            id='basic-assignee-selector',
            type_to_search=True,
            compact=True,
            disabled=True,
        )
        yield LazySelect(
            lazy_load_callback=lambda: self._lazy_load_types(),
            options=[],
            prompt='Type',
            id='basic-type-selector',
            type_to_search=True,
            compact=True,
            disabled=True,
        )
        yield LazySelect(
            lazy_load_callback=lambda: self._lazy_load_statuses(),
            options=[],
            prompt='Status',
            id='basic-status-selector',
            type_to_search=True,
            compact=True,
            disabled=True,
        )

        unified_input = ExtendedInput(
            placeholder='',
            id='unified-search-input',
            compact=True,
        )
        unified_input.display = False
        yield unified_input

        yield Button(
            'Search',
            id='unified-search-button',
            compact=True,
        )

    def on_mount(self) -> None:
        set_jump_mode(self.mode_selector, 'focus')
        set_jump_mode(self.project_selector, 'focus')
        set_jump_mode(self.assignee_selector, 'focus')
        set_jump_mode(self.type_selector, 'focus')
        set_jump_mode(self.status_selector, 'focus')
        set_jump_mode(self.unified_input, 'focus')
        set_jump_mode(self.create_work_item_button, 'click')
        set_jump_mode(self.search_button, 'click')

        self._sync_basic_filter_jump_modes()
        self._sync_search_button_state()

    def _sync_basic_filter_jump_modes(self) -> None:
        for selector_id in (
            self.project_selector,
            self.assignee_selector,
            self.type_selector,
            self.status_selector,
        ):
            selector = selector_id
            set_jump_mode(selector, None if selector.disabled else 'focus')

    def _is_query_valid(self) -> bool:
        if self.search_mode == 'basic':
            return True

        if self.search_mode in ('text', 'jql'):
            return bool(self.unified_input.value.strip())

        return True

    def _sync_search_button_state(self) -> None:
        self.search_button.disabled = self.search_in_progress or not self._is_query_valid()
        set_jump_mode(self.search_button, None if self.search_button.disabled else 'click')

    def _sync_results_controls_state(self) -> None:
        mode = self.search_mode
        query_available = mode != 'jql' or bool(self.unified_input.value.strip())
        state = (mode, query_available)
        if state == self._last_results_controls_state:
            return

        self._last_results_controls_state = state
        cast('JiraApp', self.app).search_results_container.set_search_mode(
            mode,
            self.get_search_data(),
        )

    def action_switch_search_mode(self, mode: str) -> None:
        available_modes = {value for _label, value in self.search_modes}
        if mode in available_modes:
            self.mode_selector.value = mode

    @staticmethod
    def _normalized_input_value(value: str | None) -> str:
        return value.strip() if value else ''

    def _sync_unified_input_invalid_state(self, value: str | None) -> str:
        normalized_value = self._normalized_input_value(value)
        self._set_invalid_class(self.unified_input, not normalized_value)
        return normalized_value

    def watch_search_in_progress(self, _search_in_progress: bool) -> None:
        self._sync_search_button_state()

    async def _handle_create_work_item_menu_item(self, item: PopupMenuItem) -> None:
        if item.id == 'new-work-item':
            await cast('JiraApp', self.app).action_create_work_item()
            return

        if item.id == 'new-work-item-from-template':
            await cast('JiraApp', self.app).action_create_work_item_from_template()

    @on(PopupMenu.Selected, '#unified-search-new-work-item-menu')
    async def handle_create_work_item_menu_selected(self, event: PopupMenu.Selected) -> None:
        event.stop()
        await self._handle_create_work_item_menu_item(event.item)

    @on(PopupMenu.Dismissed, '#unified-search-new-work-item-menu')
    def handle_create_work_item_menu_dismissed(self, event: PopupMenu.Dismissed) -> None:
        event.stop()

    def _build_create_work_item_menu(self) -> PopupMenu:
        return PopupMenu(
            [
                PopupMenuItem(
                    id='new-work-item',
                    title='Work Item',
                    description='Create a Jira work item from scratch',
                    icon='✎',
                ),
                PopupMenuItem(
                    id='new-work-item-from-template',
                    title='Work Item From Template',
                    description='Create a Jira work item from a template',
                    icon='◫',
                ),
            ],
            id='unified-search-new-work-item-menu',
            anchor=lambda: self.create_work_item_button,
        )

    @on(Button.Pressed, '#unified-search-new-work-item-button')
    async def handle_create_work_item_button(self, event: Button.Pressed) -> None:
        event.stop()
        if self._create_work_item_menu is not None:
            self._create_work_item_menu.toggle()

    @work(exclusive=False, group='store-search-history')
    async def _store_search_history(self, mode: str, query: str) -> None:
        if mode not in ('text', 'jql'):
            return

        normalized_query = query.strip()
        if not normalized_query:
            return

        try:
            await run_cache_io(lambda: self._cache.add_search_history(mode, normalized_query))
            self._refresh_search_history_autocomplete(mode)
        except Exception:
            logger.debug('Failed to store search history', exc_info=True)

    def record_current_search_history(self) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        query = self.unified_input.value.strip()
        if not query:
            return

        if (
            self.search_mode == 'jql'
            and self._jql_autocomplete
            and self._jql_autocomplete.has_filter_expression(query)
        ):
            return

        self._store_search_history(self.search_mode, query)

    def _init_search_history_autocomplete(self) -> None:
        if self._search_history_autocomplete is not None:
            return

        from gojeera.widgets.search.search_autocomplete import SearchAutoComplete

        self._search_history_autocomplete = SearchAutoComplete(
            target=self.unified_input,
            show_on_empty_input=False,
            hide_exact_single_match=True,
            disabled=True,
        )
        self.app.mount(self._search_history_autocomplete)

    @work(exclusive=True, group='search-history')
    async def _refresh_search_history_autocomplete(self, mode: str) -> None:
        if mode == 'text':
            autocomplete = self._search_history_autocomplete
        elif mode == 'jql':
            autocomplete = self._jql_autocomplete
        else:
            return

        if autocomplete is None:
            return

        try:
            queries = await run_cache_io(lambda: self._cache.get_search_history(mode))
        except Exception:
            logger.debug('Failed to load search history', exc_info=True)
            return

        if mode == 'jql':
            autocomplete.update_history_queries(queries)
        else:
            autocomplete.update_queries(queries)

    def _init_jql_autocomplete(self) -> None:
        if self._jql_autocomplete is not None:
            return

        from gojeera.internal.store.config import CONFIGURATION
        from gojeera.widgets.search.search_autocomplete import SearchAutoComplete

        jql_filters = CONFIGURATION.get().jql_filters or []
        if self._remote_filters:
            jql_filters = jql_filters + self._remote_filters

        self._jql_autocomplete = SearchAutoComplete(
            target=self.unified_input,
            jql_filters=jql_filters,
            show_on_empty_input=True,
            disabled=True,
        )

        self.app.mount(self._jql_autocomplete)

    def _ensure_autocomplete_for_mode(self, mode: str) -> None:
        if mode == 'text':
            self._init_search_history_autocomplete()
        elif mode == 'jql':
            self._init_jql_autocomplete()

    @on(ProfileIsReady)
    def _handle_account_id_ready(self, message: ProfileIsReady) -> None:
        self._account_id = message.account_id
        self._ensure_remote_filters_loaded()

    def _ensure_remote_filters_loaded(self) -> None:
        config = CONFIGURATION.get()
        context = (
            self._cache.profile_key,
            self._account_id,
            config.fetch_remote_filters.enabled,
            config.fetch_remote_filters.starred_only,
            config.fetch_remote_filters.include_shared,
        )
        if context != self._remote_filters_context:
            self._remote_filters_context = context
            self._remote_filters_generation += 1
            self._merge_remote_filters([])
            self._remote_filters = None
            if self._remote_filters_worker is not None:
                self._remote_filters_worker.cancel()
            self._remote_filters_worker = None
            self._remote_filters_cache_write_failed = False
            self._remote_filters_fetch_requested = False
            self._remote_filters_fetched = not config.fetch_remote_filters.enabled

        if config.fetch_remote_filters.enabled and not self._remote_filters_fetch_requested:
            if not self._account_id:
                return
            self._remote_filters_generation += 1
            self._remote_filters_fetch_requested = True
            self._remote_filters_worker = self._fetch_remote_filters(
                account_id=self._account_id,
                generation=self._remote_filters_generation,
                starred_only=config.fetch_remote_filters.starred_only,
                cache_ttl=config.fetch_remote_filters.cache_ttl,
                include_shared=config.fetch_remote_filters.include_shared,
            )

    async def get_remote_filter_suggestions(self, account_id: str) -> list[JiraFilterDict]:
        """Share refreshes with the palette, returning loaded/stale filters promptly."""
        self._account_id = account_id
        self._ensure_remote_filters_loaded()
        config = CONFIGURATION.get().fetch_remote_filters
        if not config.enabled:
            return []
        generation = self._remote_filters_generation
        worker = self._remote_filters_worker
        if self._remote_filters is None:
            try:
                cached = await run_cache_io(
                    lambda: self._cache.get_remote_filters(
                        account_id,
                        starred_only=config.starred_only,
                        include_shared=config.include_shared,
                        allow_stale=True,
                    )
                )
                if generation != self._remote_filters_generation:
                    return []
                if cached is not None and self._remote_filters is None:
                    self._merge_remote_filters([item.as_filter_dict() for item in cached])
            except Exception:
                logger.debug('Palette cache lookup failed; using shared fetch', exc_info=True)
        if self._remote_filters is None and worker is not None:
            try:
                # Cancelling a palette query must not cancel the shared refresh.
                await asyncio.shield(worker.wait())
            except WorkerCancelled:
                return []
        if generation != self._remote_filters_generation:
            return []
        return list(self._remote_filters or [])

    @work(exclusive=True, group='remote-filters')
    async def _fetch_remote_filters(
        self,
        account_id: str,
        generation: int,
        starred_only: bool,
        cache_ttl: int,
        include_shared: bool = False,
    ) -> None:
        """Fetch remote filters from Jira and merge with local filters.

        Args:
            account_id: User's Jira account ID
            generation: Unique generation of this scheduled request
            starred_only: Whether to fetch only starred (favorite) filters
            cache_ttl: Cache TTL in seconds
            include_shared: If True, include shared filters (default: False, personal only)
        """
        if generation != self._remote_filters_generation:
            return

        write_allowed = Event()
        write_allowed.set()
        cache_profile = self._cache.profile_key
        try:
            cached_filters = None
            stale_filters = None
            try:
                if not self._remote_filters_cache_write_failed:
                    cached_filters = await run_cache_io(
                        lambda: self._cache.get_remote_filters(
                            account_id, starred_only=starred_only, include_shared=include_shared
                        )
                    )
                if (
                    not self._remote_filters_cache_write_failed
                    and cached_filters is None
                    and self._remote_filters is None
                    and generation == self._remote_filters_generation
                ):
                    stale_filters = await run_cache_io(
                        lambda: self._cache.get_remote_filters(
                            account_id,
                            starred_only=starred_only,
                            include_shared=include_shared,
                            allow_stale=True,
                        )
                    )
            except Exception:
                logger.warning(
                    'Failed to read remote filter cache; fetching from Jira', exc_info=True
                )

            if generation != self._remote_filters_generation:
                return
            if cached_filters is not None:
                self._merge_remote_filters(
                    [filter_data.as_filter_dict() for filter_data in cached_filters]
                )
                self._remote_filters_fetched = True
                return
            if stale_filters is not None and self._remote_filters is None:
                self._merge_remote_filters(
                    [filter_data.as_filter_dict() for filter_data in stale_filters]
                )
                self._update_jql_placeholder()

            remote_filters = cast(
                'list[JiraFilterDict]',
                await self.api.client.fetch_user_filters(
                    account_id=account_id,
                    starred_only=starred_only,
                    max_results=50,
                    include_shared=include_shared,
                ),
            )
            if generation != self._remote_filters_generation:
                return

            # Successful Jira results remain usable even if persistence is slow or fails.
            self._merge_remote_filters(remote_filters)
            self._remote_filters_fetched = True
            self._update_jql_placeholder()
            result_ttl = (
                cache_ttl
                if remote_filters
                else min(cache_ttl, EMPTY_REMOTE_FILTER_CACHE_TTL_SECONDS)
            )
            try:
                await run_cache_io(
                    lambda: self._cache.set_remote_filters(
                        account_id,
                        remote_filters,
                        ttl_seconds=result_ttl,
                        starred_only=starred_only,
                        include_shared=include_shared,
                        can_write=lambda: (
                            write_allowed.is_set()
                            and generation == self._remote_filters_generation
                            and cache_profile == self._cache.profile_key
                        ),
                    )
                )
                if generation == self._remote_filters_generation:
                    self._remote_filters_cache_write_failed = False
            except Exception:
                if generation == self._remote_filters_generation:
                    self._remote_filters_cache_write_failed = True
                logger.warning(
                    'Failed to persist remote filters; using fetched results', exc_info=True
                )
        except Exception:
            logger.warning(
                'Failed to load remote filters; retaining existing filters', exc_info=True
            )
        finally:
            # Cancelling the coroutine cannot stop a running cache thread. Revoke its
            # permission here; the cache checks it atomically before writing.
            write_allowed.clear()
            if generation == self._remote_filters_generation:
                self._remote_filters_fetch_requested = False
                self._update_jql_placeholder()

    def _update_jql_placeholder(self) -> None:
        if self.search_mode == 'jql':
            try:
                self.unified_input.placeholder = (
                    'Enter JQL query or click for filter suggestions...'
                )
            except Exception:
                logger.debug('Failed to update unified input placeholder', exc_info=True)

    def _merge_remote_filters(self, remote_filters: list[JiraFilterDict]) -> None:
        from gojeera.internal.store.config import CONFIGURATION

        if self._remote_filters != remote_filters:
            self.remote_filter_revision += 1
        self._remote_filters = remote_filters

        if not self._jql_autocomplete:
            return

        local_filters = CONFIGURATION.get().jql_filters or []

        all_filters = local_filters + remote_filters

        self._jql_autocomplete.update_filters(all_filters)

    @on(Input.Changed, '#unified-search-input')
    def handle_unified_input_changed(self, event: Input.Changed) -> None:
        self._sync_results_controls_state()

        self._sync_search_button_state()

        if self.search_mode not in ('text', 'jql'):
            return

        self._sync_unified_input_invalid_state(event.value)

    @on(Input.Submitted, '#unified-search-input')
    def handle_unified_input_submitted(self, event: Input.Submitted) -> None:
        if self.search_in_progress:
            return

        if self.search_mode not in ('text', 'jql'):
            return

        if not self._sync_unified_input_invalid_state(event.value):
            return

        self.search_button.press()

    @on(Input.Blurred, '#unified-search-input')
    def handle_unified_input_blurred(self, event: Input.Blurred) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        self._sync_unified_input_invalid_state(event.value)

    def _lazy_load_assignees(self) -> None:
        if self._selected_project_key:
            if self._users_fetched_for_project != self._selected_project_key:
                self.fetch_users()
            else:
                self.assignee_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            self.assignee_selector._stop_spinner()

    def _lazy_load_types(self) -> None:
        if self._selected_project_key:
            if self._types_fetched_for_project != self._selected_project_key:
                self.fetch_work_item_types()
            else:
                self.type_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            self.type_selector._stop_spinner()

    def _lazy_load_statuses(self) -> None:
        if self._selected_project_key:
            if self._statuses_fetched_for_project != self._selected_project_key:
                self.fetch_statuses()
            else:
                self.status_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            self.status_selector._stop_spinner()

    @on(Select.Changed, '#search-mode-selector')
    def handle_mode_change(self, event: Select.Changed) -> None:
        if event.value and isinstance(event.value, str):
            mode_str = str(event.value)
            if mode_str != 'basic':
                self._clear_work_item_key()
            self.search_mode = mode_str
            self._update_mode_display(mode_str)
            self._sync_search_button_state()
            self._sync_results_controls_state()

    @on(Select.Changed, '#basic-project-selector')
    def handle_project_changed(self, event: Select.Changed) -> None:
        self._clear_work_item_key()
        if event.value and isinstance(event.value, str):
            self._selected_project_key = str(event.value)

            self._users_fetched_for_project = None
            self._types_fetched_for_project = None
            self._statuses_fetched_for_project = None

            self.assignee_selector.clear()
            self.type_selector.clear()
            self.status_selector.clear()

            self.assignee_selector._has_loaded = False
            self.type_selector._has_loaded = False
            self.status_selector._has_loaded = False

            self.assignee_selector.disabled = False
            self.type_selector.disabled = False
            self.status_selector.disabled = False
            self._sync_basic_filter_jump_modes()
        else:
            self._selected_project_key = None
            self.assignee_selector.disabled = True
            self.type_selector.disabled = True
            self.status_selector.disabled = True
            self._sync_basic_filter_jump_modes()
        self._sync_search_button_state()

    @on(Select.Changed, '#basic-assignee-selector')
    @on(Select.Changed, '#basic-type-selector')
    @on(Select.Changed, '#basic-status-selector')
    def handle_basic_filter_changed(self) -> None:
        self._clear_work_item_key()
        self._sync_search_button_state()

    def _update_mode_display(self, mode: str) -> None:
        self._ensure_autocomplete_for_mode(mode)

        with self.app.batch_update():
            mode_class = f'mode-{mode}'
            if not self.has_class(mode_class):
                self.remove_class('mode-basic', 'mode-text', 'mode-jql')
                self.add_class(mode_class)

            if self._jql_autocomplete:
                autocomplete_disabled = mode != 'jql'
                if self._jql_autocomplete.disabled != autocomplete_disabled:
                    self._jql_autocomplete.disabled = autocomplete_disabled

            if self._search_history_autocomplete:
                history_disabled = mode != 'text'
                if self._search_history_autocomplete.disabled != history_disabled:
                    self._search_history_autocomplete.disabled = history_disabled

            if mode in ('text', 'jql'):
                self._refresh_search_history_autocomplete(mode)

            if mode == 'basic':
                self._set_widget_display(self.project_selector, True)
                self._set_widget_display(self.assignee_selector, True)
                self._set_widget_display(self.type_selector, True)
                self._set_widget_display(self.status_selector, True)
                self._set_widget_display(self.unified_input, False)
                if self.unified_input.placeholder != '':
                    self.unified_input.placeholder = ''
                self._set_invalid_class(self.unified_input, False)
            elif mode == 'text':
                self._set_widget_display(self.project_selector, False)
                self._set_widget_display(self.assignee_selector, False)
                self._set_widget_display(self.type_selector, False)
                self._set_widget_display(self.status_selector, False)
                self._set_widget_display(self.unified_input, True)
                placeholder = 'Enter text to search in summaries...'
                if self.unified_input.placeholder != placeholder:
                    self.unified_input.placeholder = placeholder
                self._set_invalid_class(self.unified_input, not self.unified_input.value.strip())
            elif mode == 'jql':
                self._ensure_remote_filters_loaded()
                self._set_widget_display(self.project_selector, False)
                self._set_widget_display(self.assignee_selector, False)
                self._set_widget_display(self.type_selector, False)
                self._set_widget_display(self.status_selector, False)
                self._set_widget_display(self.unified_input, True)

                if self._remote_filters_fetched:
                    placeholder = 'Enter JQL query or click for filter suggestions...'
                else:
                    placeholder = 'Loading filters... (Enter JQL query or wait)'
                if self.unified_input.placeholder != placeholder:
                    self.unified_input.placeholder = placeholder
                self._set_invalid_class(self.unified_input, not self.unified_input.value.strip())

    def watch_projects(self, projects: dict | None) -> None:
        if projects and 'projects' in projects:
            if self.project_selector._has_loaded:
                self.project_selector.set_options(projects['projects'])
            else:
                if self.project_selector._is_loading:
                    self.project_selector._stop_spinner()

    def watch_users(self, users: dict | None) -> None:
        if users and 'users' in users:
            if self.assignee_selector._has_loaded:
                self.assignee_selector.set_options(users['users'])
            else:
                if self.assignee_selector._is_loading:
                    self.assignee_selector._stop_spinner()

    def watch_types(self, types: list[tuple[str, str]] | None) -> None:
        if types:
            if self.type_selector._has_loaded:
                self.type_selector.set_options(types)
            else:
                if self.type_selector._is_loading:
                    self.type_selector._stop_spinner()

    def watch_statuses(self, statuses: list[tuple[str, str]] | None) -> None:
        if statuses:
            if self.status_selector._has_loaded:
                self.status_selector.set_options(statuses)
            else:
                if self.status_selector._is_loading:
                    self.status_selector._stop_spinner()

    def _store_fetched_statuses(
        self,
        *,
        statuses: list[tuple[str, str]],
        project_key: str | None,
    ) -> None:
        self.statuses = statuses
        self._statuses_fetched_for_project = project_key

    def _store_sorted_status_options(
        self,
        *,
        statuses: list[WorkItemStatus],
        project_key: str | None,
    ) -> None:
        self._store_fetched_statuses(
            statuses=[
                (status.name, status.id)
                for status in sorted(statuses, key=lambda status: status.name)
            ],
            project_key=project_key,
        )

    def _handle_status_fetch_failure(self, error: str | None) -> None:
        self.notify(
            f'Failed to fetch statuses: {error}',
            severity='error',
            title='Search',
        )
        self.status_selector._stop_spinner()

    @staticmethod
    def _unique_project_statuses(
        project_statuses: dict[str, dict[str, Any]],
    ) -> list[WorkItemStatus]:
        seen = set()
        unique_statuses = []
        for work_item_type_data in project_statuses.values():
            for status in work_item_type_data.get('work_item_type_statuses', []):
                if status.id not in seen:
                    seen.add(status.id)
                    unique_statuses.append(status)
        return unique_statuses

    @work(exclusive=False, group='fetch-projects')
    async def fetch_projects(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            if self.projects and 'projects' in self.projects:
                self.project_selector.set_options(self.projects['projects'])
                self.project_selector._stop_spinner()
                return

            published_project_keys: tuple[str, ...] = ()

            def publish_projects_page(projects_result) -> None:
                nonlocal published_project_keys
                if worker.is_cancelled:
                    return
                project_keys = tuple(project.key for project in projects_result)
                if project_keys == published_project_keys:
                    return
                published_project_keys = project_keys
                projects_list = [(f'{p.name} ({p.key})', p.key) for p in projects_result]
                self.projects = {'projects': projects_list, 'selection': None}

            response = await self.api.search_projects(on_page=publish_projects_page)
            if response.success and response.result:
                projects_result = response.result
                publish_projects_page(projects_result)

            else:
                self.notify(
                    f'Failed to fetch projects: {response.error}', severity='error', title='Search'
                )

                self.project_selector._stop_spinner()

    @work(exclusive=False, group='fetch-users')
    async def fetch_users(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if (
                    self.users
                    and 'users' in self.users
                    and self._users_fetched_for_project == project_key
                ):
                    self.assignee_selector.set_options(self.users['users'])
                    self.assignee_selector._stop_spinner()
                    return

                if project_key:
                    response = await self.api.search_users_assignable_to_projects(
                        project_keys=[project_key]
                    )
                else:
                    response = await self.api.search_users('')

                if response.success:
                    result = response.result or []
                    users = [(user.display_name, user.account_id) for user in result]
                    self.users = {'users': users, 'selection': None}
                    self._users_fetched_for_project = project_key
                    return

                error = (
                    response.error
                    or 'You may not have permission to view assignable users for this project.'
                )
                self.notify(f'Failed to fetch users: {error}', severity='warning', title='Search')
                self.users = {'users': [], 'selection': None}
                self._users_fetched_for_project = project_key
                self.assignee_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching users: {e!s}', severity='error', title='Search')
                self.assignee_selector._stop_spinner()
        else:
            self.assignee_selector._stop_spinner()

    @work(exclusive=False, group='fetch-types')
    async def fetch_work_item_types(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if self.types and self._types_fetched_for_project == project_key:
                    self.type_selector.set_options(self.types)
                    self.type_selector._stop_spinner()
                    return

                if project_key:
                    response = await self.api.get_work_item_types_for_project(project_key)
                else:
                    response = await self.api.get_work_item_types()

                if response.success and response.result:
                    work_item_types = response.result
                    types_list = sorted(work_item_types, key=lambda x: x.name)
                    types = [(t.name, t.id) for t in types_list]

                    self.types = types
                    self._types_fetched_for_project = project_key

                else:
                    self.notify(
                        f'Failed to fetch issue types: {response.error}',
                        severity='error',
                        title='Search',
                    )
                    self.type_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching issue types: {e!s}', severity='error', title='Search')
                self.type_selector._stop_spinner()
        else:
            self.type_selector._stop_spinner()

    @work(exclusive=False, group='fetch-statuses')
    async def fetch_statuses(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if self.statuses and self._statuses_fetched_for_project == project_key:
                    self.status_selector.set_options(self.statuses)
                    self.status_selector._stop_spinner()
                    return

                if project_key:
                    response = await self.api.get_project_statuses(project_key)
                    if response.success and response.result:
                        self._store_sorted_status_options(
                            statuses=self._unique_project_statuses(response.result),
                            project_key=project_key,
                        )
                    else:
                        self._handle_status_fetch_failure(response.error)
                else:
                    response = await self.api.status()
                    if response.success and response.result:
                        self._store_sorted_status_options(
                            statuses=response.result,
                            project_key=project_key,
                        )
                    else:
                        self._handle_status_fetch_failure(response.error)
            except Exception as e:
                self.notify(f'Error fetching statuses: {e!s}', severity='error', title='Search')
                self.status_selector._stop_spinner()
        else:
            self.status_selector._stop_spinner()

    def get_search_data(self) -> dict:
        mode = self.search_mode

        if mode == 'basic':
            return {
                'mode': 'basic',
                'work_item_key': self._work_item_key or '',
                'project': self.project_selector.value,
                'assignee': self.assignee_selector.value,
                'type': self.type_selector.value,
                'status': self.status_selector.value,
            }
        elif mode == 'text':
            text = self.unified_input.value

            return {
                'mode': 'text',
                'jql': text_search_jql(text),
            }
        elif mode == 'jql':
            return {
                'mode': 'jql',
                'jql': self.unified_input.value,
            }

        return {'mode': mode}

    def set_initial_work_item_key(self, value: str) -> bool:
        work_item_key = self.extract_work_item_key(value)
        if work_item_key is None:
            return False

        self._work_item_key = work_item_key

        self.mode_selector.value = 'basic'
        self.search_mode = 'basic'
        self._update_mode_display('basic')
        return True

    def _clear_work_item_key(self) -> None:
        self._work_item_key = None

    @staticmethod
    def extract_work_item_key(value: str) -> str | None:
        return extract_work_item_key(value)

    async def set_initial_jql_filter(self, filter_label: str) -> None:
        jql_filters = CONFIGURATION.get().jql_filters
        if not jql_filters:
            self.notify('No JQL filters defined in config', severity='warning', title='Search')
            return

        filter_expression = None
        for filter_data in jql_filters:
            if filter_data.get('label') == filter_label:
                filter_expression = filter_data.get('expression')
                break

        if not filter_expression:
            self.notify(
                f'JQL filter with label "{filter_label}" not found in config', severity='warning'
            )
            return

        self.mode_selector.value = 'jql'
        self.search_mode = 'jql'
        self._update_mode_display('jql')

        cleaned_expression = filter_expression.replace('\n', ' ').replace('\t', ' ').strip()
        self.unified_input.value = cleaned_expression
