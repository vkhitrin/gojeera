from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Input, Select
from textual.worker import get_current_worker

from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION
from gojeera.utils.urls import extract_work_item_key
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import set_jump_mode
from gojeera.widgets.jql_autocomplete import JQLAutoComplete
from gojeera.widgets.lazy_select import LazySelect
from gojeera.widgets.vim_select import VimSelect

if TYPE_CHECKING:
    from gojeera.api_controller.controller import APIController
    from gojeera.app import MainScreen

logger = logging.getLogger('gojeera')


class UnifiedSearchBar(Container):
    """Unified search bar widget with mode selection and dynamic content based on mode."""

    class AccountIdReady(Message):
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
        super().__init__(**kwargs)
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

        self._jql_autocomplete: JQLAutoComplete | None = None
        self._work_item_key: str | None = None

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
    def new_work_item_button(self) -> Button:
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

        yield Button(
            '+',
            id='unified-search-new-work-item-button',
            compact=True,
        )

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
        )
        yield LazySelect(
            lazy_load_callback=lambda: self._lazy_load_types(),
            options=[],
            prompt='Type',
            id='basic-type-selector',
            type_to_search=True,
            compact=True,
        )
        yield LazySelect(
            lazy_load_callback=lambda: self._lazy_load_statuses(),
            options=[],
            prompt='Status',
            id='basic-status-selector',
            type_to_search=True,
            compact=True,
        )

        yield ExtendedInput(
            placeholder='Enter search term...',
            id='unified-search-input',
            compact=True,
        )

        yield Button(
            'Search',
            id='unified-search-button',
            compact=True,
        )

    def on_mount(self) -> None:
        self._update_mode_display('basic')

        set_jump_mode(self.mode_selector, 'focus')
        set_jump_mode(self.project_selector, 'focus')
        set_jump_mode(self.assignee_selector, 'focus')
        set_jump_mode(self.type_selector, 'focus')
        set_jump_mode(self.status_selector, 'focus')
        set_jump_mode(self.unified_input, 'focus')
        set_jump_mode(self.new_work_item_button, 'click')
        set_jump_mode(self.search_button, 'click')

        self.assignee_selector.disabled = True
        self.type_selector.disabled = True
        self.status_selector.disabled = True
        self._sync_basic_filter_jump_modes()
        self._sync_search_button_state()

        self._init_jql_autocomplete()

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

    def watch_search_in_progress(self, search_in_progress: bool) -> None:
        self._sync_search_button_state()

    @on(Button.Pressed, '#unified-search-new-work-item-button')
    async def handle_new_work_item_button(self) -> None:
        await cast('MainScreen', self.screen).action_new_work_item()

    def _init_jql_autocomplete(self) -> None:
        from gojeera.config import CONFIGURATION

        jql_filters = CONFIGURATION.get().jql_filters or []

        self._jql_autocomplete = JQLAutoComplete(
            target=self.unified_input,
            jql_filters=jql_filters,
        )

        self.screen.mount(self._jql_autocomplete)

        self._jql_autocomplete.disabled = True

    @on(AccountIdReady)
    def _handle_account_id_ready(self, message: AccountIdReady) -> None:
        config = CONFIGURATION.get()

        if config.fetch_remote_filters.enabled:
            self._account_id = message.account_id

            self._fetch_remote_filters(
                account_id=self._account_id,
                starred_only=config.fetch_remote_filters.starred_only,
                cache_ttl=config.fetch_remote_filters.cache_ttl,
                include_shared=config.fetch_remote_filters.include_shared,
            )

    @work(exclusive=False)
    async def _fetch_remote_filters(
        self,
        account_id: str | None,
        starred_only: bool,
        cache_ttl: int,
        include_shared: bool = False,
    ) -> None:
        """Fetch remote filters from Jira and merge with local filters.

        Args:
            account_id: User's Jira account ID
            starred_only: Whether to fetch only starred (favorite) filters
            cache_ttl: Cache TTL in seconds
            include_shared: If True, include shared filters (default: False, personal only)
        """
        if not account_id:
            return

        cached_filters = self._cache.get('remote_filters', account_id)

        if cached_filters:
            self._merge_remote_filters(cached_filters)

            self._remote_filters_fetched = True

            self._update_jql_placeholder()
            return

        try:
            remote_filters = await self.api.api.fetch_user_filters(
                account_id=account_id,
                starred_only=starred_only,
                max_results=50,
                include_shared=include_shared,
            )

            if remote_filters:
                self._cache.set(
                    'remote_filters',
                    remote_filters,
                    identifier=account_id,
                    ttl_seconds=cache_ttl,
                )

                self._merge_remote_filters(remote_filters)

                self._remote_filters_fetched = True

                self._update_jql_placeholder()
            else:
                self._remote_filters_fetched = True

                self._update_jql_placeholder()

        except Exception:
            self._remote_filters_fetched = True

            self._update_jql_placeholder()

    def _update_jql_placeholder(self) -> None:
        if self.search_mode == 'jql':
            try:
                self.unified_input.placeholder = (
                    'Enter JQL query or click for filter suggestions...'
                )
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    def _merge_remote_filters(self, remote_filters: list[dict[str, str]]) -> None:
        from gojeera.config import CONFIGURATION

        if not self._jql_autocomplete:
            return

        local_filters = CONFIGURATION.get().jql_filters or []

        all_filters = local_filters + remote_filters

        self._jql_autocomplete.update_filters(all_filters)

    @on(Input.Changed, '#unified-search-input')
    def handle_unified_input_changed(self, event: Input.Changed) -> None:
        cast('MainScreen', self.screen).search_results_container.set_search_mode(
            self.search_mode,
            self.get_search_data(),
        )

        self._sync_search_button_state()

        if self.search_mode not in ('text', 'jql'):
            return

        value = event.value.strip() if event.value else ''

        if not value:
            self.unified_input.add_class('-invalid')
        else:
            self.unified_input.remove_class('-invalid')

    @on(Input.Submitted, '#unified-search-input')
    def handle_unified_input_submitted(self, event: Input.Submitted) -> None:
        if self.search_in_progress:
            return

        if self.search_mode not in ('text', 'jql'):
            return

        value = event.value.strip() if event.value else ''

        if not value:
            self.unified_input.add_class('-invalid')
            return

        self.unified_input.remove_class('-invalid')
        self.search_button.press()

    @on(Input.Blurred, '#unified-search-input')
    def handle_unified_input_blurred(self, event: Input.Blurred) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        value = event.value.strip() if event.value else ''

        if not value:
            self.unified_input.add_class('-invalid')
        else:
            self.unified_input.remove_class('-invalid')

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
            cast('MainScreen', self.screen).search_results_container.set_search_mode(
                mode_str,
                self.get_search_data(),
            )

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
        with self.app.batch_update():
            self.remove_class('mode-basic', 'mode-text', 'mode-jql')
            self.add_class(f'mode-{mode}')

            if self._jql_autocomplete:
                self._jql_autocomplete.disabled = mode != 'jql'

            if mode == 'basic':
                self.project_selector.display = True
                self.assignee_selector.display = True
                self.type_selector.display = True
                self.status_selector.display = True
                self.unified_input.display = False
                self.unified_input.placeholder = ''

                self.unified_input.remove_class('-invalid')
            elif mode == 'text':
                self.project_selector.display = False
                self.assignee_selector.display = False
                self.type_selector.display = False
                self.status_selector.display = False
                self.unified_input.display = True
                self.unified_input.placeholder = 'Enter text to search in summaries...'

                if not self.unified_input.value.strip():
                    self.unified_input.add_class('-invalid')
                else:
                    self.unified_input.remove_class('-invalid')
            elif mode == 'jql':
                self.project_selector.display = False
                self.assignee_selector.display = False
                self.type_selector.display = False
                self.status_selector.display = False
                self.unified_input.display = True

                if hasattr(self, '_remote_filters_fetched') and self._remote_filters_fetched:
                    self.unified_input.placeholder = (
                        'Enter JQL query or click for filter suggestions...'
                    )
                else:
                    self.unified_input.placeholder = 'Loading filters... (Enter JQL query or wait)'

                if not self.unified_input.value.strip():
                    self.unified_input.add_class('-invalid')
                else:
                    self.unified_input.remove_class('-invalid')

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

    @work(exclusive=False, group='fetch-projects')
    async def fetch_projects(self) -> None:
        worker = get_current_worker()
        if not worker.is_cancelled:
            if self.projects and 'projects' in self.projects:
                self.project_selector.set_options(self.projects['projects'])
                self.project_selector._stop_spinner()
                return

            cached_projects = self._cache.get('projects')
            if cached_projects is not None:
                projects_list = [(f'{p.name} ({p.key})', p.key) for p in cached_projects]
                self.projects = {'projects': projects_list, 'selection': None}
                return

            response = await self.api.search_projects()
            if response.success and response.result:
                self._cache.set('projects', response.result)

                projects_list = [(f'{p.name} ({p.key})', p.key) for p in response.result]
                self.projects = {'projects': projects_list, 'selection': None}

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

                cache_key = project_key if project_key else 'global'
                cached_users = self._cache.get('project_users', cache_key)
                if cached_users is not None:
                    users_tuples = [(user.display_name, user.account_id) for user in cached_users]
                    self.users = {'users': users_tuples, 'selection': None}
                    self._users_fetched_for_project = project_key

                    return

                if project_key:
                    response = await self.api.search_users_assignable_to_projects(
                        project_keys=[project_key]
                    )
                else:
                    response = await self.api.search_users('')

                if response.success and response.result:
                    self._cache.set('project_users', response.result, cache_key)

                    users = [(user.display_name, user.account_id) for user in response.result]
                    self.users = {'users': users, 'selection': None}
                    self._users_fetched_for_project = project_key

                else:
                    self.notify(
                        f'Failed to fetch users: {response.error}', severity='error', title='Search'
                    )
                    self.assignee_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching users: {str(e)}', severity='error', title='Search')
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

                cache_key = project_key if project_key else 'global'
                cached_types = self._cache.get('project_types', cache_key)
                if cached_types is not None:
                    self.types = cached_types
                    self._types_fetched_for_project = project_key

                    return

                if project_key:
                    response = await self.api.get_work_item_types_for_project(project_key)
                else:
                    response = await self.api.get_work_item_types()

                if response.success and response.result:
                    types_list = sorted(response.result, key=lambda x: x.name)
                    types = [(t.name, t.id) for t in types_list]

                    self._cache.set('project_types', types, cache_key)

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
                self.notify(
                    f'Error fetching issue types: {str(e)}', severity='error', title='Search'
                )
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

                cache_key = project_key if project_key else 'global'
                cached_statuses = self._cache.get('project_statuses', cache_key)
                if cached_statuses is not None:
                    self.statuses = cached_statuses
                    self._statuses_fetched_for_project = project_key

                    return

                if project_key:
                    response = await self.api.get_project_statuses(project_key)
                    if response.success and response.result:
                        seen = set()
                        unique_statuses = []
                        for _work_item_type_id, work_item_type_data in response.result.items():
                            statuses_list = work_item_type_data.get('work_item_type_statuses', [])
                            for status in statuses_list:
                                if status.id not in seen:
                                    seen.add(status.id)
                                    unique_statuses.append(status)
                        statuses_list = sorted(unique_statuses, key=lambda x: x.name)
                        statuses = [(s.name, s.id) for s in statuses_list]

                        self._cache.set('project_statuses', statuses, cache_key)

                        self.statuses = statuses
                        self._statuses_fetched_for_project = project_key

                    else:
                        self.notify(
                            f'Failed to fetch statuses: {response.error}',
                            severity='error',
                            title='Search',
                        )
                        self.status_selector._stop_spinner()
                else:
                    response = await self.api.status()
                    if response.success and response.result:
                        statuses_list = sorted(response.result, key=lambda x: x.name)
                        statuses = [(s.name, s.id) for s in statuses_list]

                        self._cache.set('project_statuses', statuses, cache_key)

                        self.statuses = statuses
                        self._statuses_fetched_for_project = project_key

                    else:
                        self.notify(
                            f'Failed to fetch statuses: {response.error}',
                            severity='error',
                            title='Search',
                        )
                        self.status_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching statuses: {str(e)}', severity='error', title='Search')
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
                'jql': f'textfields ~ "{text}"' if text else '',
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
