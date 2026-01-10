from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Input, Select
from textual.worker import get_current_worker

from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION
from gojeera.widgets.jql_autocomplete import JQLAutoComplete
from gojeera.widgets.lazy_select import LazySelect
from gojeera.widgets.vim_select import VimSelect

if TYPE_CHECKING:
    from gojeera.api_controller.controller import APIController

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

    def compose(self) -> ComposeResult:
        yield VimSelect(
            options=[(label, value) for label, value in self.search_modes],
            prompt='Search mode',
            id='search-mode-selector',
            value='basic',
            compact=True,
        )

        yield Input(
            placeholder='KEY',
            id='basic-work-item-key',
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

        yield Input(
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

        self.query_one('#search-mode-selector', VimSelect).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#basic-work-item-key', Input).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#basic-project-selector', LazySelect).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#basic-assignee-selector', LazySelect).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#basic-type-selector', LazySelect).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#basic-status-selector', LazySelect).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#unified-search-input', Input).jump_mode = 'focus'  # type: ignore[attr-defined]
        self.query_one('#unified-search-button', Button).jump_mode = 'click'  # type: ignore[attr-defined]

        assignee_selector = self.query_one('#basic-assignee-selector', LazySelect)
        type_selector = self.query_one('#basic-type-selector', LazySelect)
        status_selector = self.query_one('#basic-status-selector', LazySelect)
        assignee_selector.disabled = True
        type_selector.disabled = True
        status_selector.disabled = True

        self._init_jql_autocomplete()

    def _init_jql_autocomplete(self) -> None:
        from gojeera.config import CONFIGURATION

        jql_filters = CONFIGURATION.get().jql_filters or []

        jql_input = self.query_one('#unified-search-input', Input)

        self._jql_autocomplete = JQLAutoComplete(
            target=jql_input,
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
                unified_input = self.query_one('#unified-search-input', Input)
                unified_input.placeholder = 'Enter JQL query or click for filter suggestions...'
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    def _merge_remote_filters(self, remote_filters: list[dict[str, str]]) -> None:
        from gojeera.config import CONFIGURATION

        if not self._jql_autocomplete:
            return

        local_filters = CONFIGURATION.get().jql_filters or []

        all_filters = local_filters + remote_filters

        self._jql_autocomplete.update_filters(all_filters)

    def is_work_item_key_valid(self) -> bool:
        import re

        work_item_input = self.query_one('#basic-work-item-key', Input)
        value = work_item_input.value.strip() if work_item_input.value else ''

        if not value:
            return True

        work_item_pattern = r'^[A-Z][A-Z0-9]+-\d+$'
        return bool(re.match(work_item_pattern, value))

    @on(Input.Changed, '#basic-work-item-key')
    def handle_work_item_key_changed(self, event: Input.Changed) -> None:
        import re

        work_item_input = self.query_one('#basic-work-item-key', Input)
        value = event.value.strip() if event.value else ''

        if not value:
            work_item_input.remove_class('-invalid')
            return

        work_item_pattern = r'^[A-Z][A-Z0-9]+-\d+$'
        if re.match(work_item_pattern, value):
            work_item_input.remove_class('-invalid')
        else:
            work_item_input.add_class('-invalid')

    @on(Input.Submitted, '#basic-work-item-key')
    def handle_work_item_key_submitted(self, event: Input.Submitted) -> None:
        if not self.is_work_item_key_valid():
            work_item_input = self.query_one('#basic-work-item-key', Input)
            work_item_input.add_class('-invalid')
            self.notify(
                'Invalid work item key format. Expected format: PROJECT-123',
                severity='warning',
                title='Validation Error',
            )
            return

        search_button = self.query_one('#unified-search-button', Button)
        search_button.press()

    @on(Input.Blurred, '#basic-work-item-key')
    def handle_work_item_key_blurred(self, event: Input.Blurred) -> None:
        work_item_input = self.query_one('#basic-work-item-key', Input)
        value = event.value.strip() if event.value else ''

        if not value:
            work_item_input.remove_class('-invalid')
            return

        work_item_pattern = r'^[A-Z][A-Z0-9]+-\d+$'
        if re.match(work_item_pattern, value):
            work_item_input.remove_class('-invalid')
        else:
            work_item_input.add_class('-invalid')

    @on(Input.Changed, '#unified-search-input')
    def handle_unified_input_changed(self, event: Input.Changed) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        unified_input = self.query_one('#unified-search-input', Input)
        value = event.value.strip() if event.value else ''

        if not value:
            unified_input.add_class('-invalid')
        else:
            unified_input.remove_class('-invalid')

    @on(Input.Submitted, '#unified-search-input')
    def handle_unified_input_submitted(self, event: Input.Submitted) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        unified_input = self.query_one('#unified-search-input', Input)
        value = event.value.strip() if event.value else ''

        if not value:
            unified_input.add_class('-invalid')
            return

        unified_input.remove_class('-invalid')
        search_button = self.query_one('#unified-search-button', Button)
        search_button.press()

    @on(Input.Blurred, '#unified-search-input')
    def handle_unified_input_blurred(self, event: Input.Blurred) -> None:
        if self.search_mode not in ('text', 'jql'):
            return

        unified_input = self.query_one('#unified-search-input', Input)
        value = event.value.strip() if event.value else ''

        if not value:
            unified_input.add_class('-invalid')
        else:
            unified_input.remove_class('-invalid')

    def _lazy_load_assignees(self) -> None:
        assignee_selector = self.query_one('#basic-assignee-selector', LazySelect)
        if self._selected_project_key:
            if self._users_fetched_for_project != self._selected_project_key:
                self.fetch_users()
            else:
                assignee_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            assignee_selector._stop_spinner()

    def _lazy_load_types(self) -> None:
        type_selector = self.query_one('#basic-type-selector', LazySelect)
        if self._selected_project_key:
            if self._types_fetched_for_project != self._selected_project_key:
                self.fetch_work_item_types()
            else:
                type_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            type_selector._stop_spinner()

    def _lazy_load_statuses(self) -> None:
        status_selector = self.query_one('#basic-status-selector', LazySelect)
        if self._selected_project_key:
            if self._statuses_fetched_for_project != self._selected_project_key:
                self.fetch_statuses()
            else:
                status_selector._stop_spinner()
        else:
            self.notify('Please select a project first', severity='warning', title='Search')

            status_selector._stop_spinner()

    @on(Select.Changed, '#search-mode-selector')
    def handle_mode_change(self, event: Select.Changed) -> None:
        if event.value and isinstance(event.value, str):
            mode_str = str(event.value)
            self.search_mode = mode_str
            self._update_mode_display(mode_str)

    @on(Select.Changed, '#basic-project-selector')
    def handle_project_changed(self, event: Select.Changed) -> None:
        if event.value and isinstance(event.value, str):
            self._selected_project_key = str(event.value)

            self._users_fetched_for_project = None
            self._types_fetched_for_project = None
            self._statuses_fetched_for_project = None

            assignee_sel = self.query_one('#basic-assignee-selector', LazySelect)
            type_sel = self.query_one('#basic-type-selector', LazySelect)
            status_sel = self.query_one('#basic-status-selector', LazySelect)
            assignee_sel.clear()
            type_sel.clear()
            status_sel.clear()

            assignee_sel._has_loaded = False
            type_sel._has_loaded = False
            status_sel._has_loaded = False

            assignee_sel.disabled = False
            type_sel.disabled = False
            status_sel.disabled = False
        else:
            self._selected_project_key = None
            assignee_sel = self.query_one('#basic-assignee-selector', LazySelect)
            type_sel = self.query_one('#basic-type-selector', LazySelect)
            status_sel = self.query_one('#basic-status-selector', LazySelect)
            assignee_sel.disabled = True
            type_sel.disabled = True
            status_sel.disabled = True

    def _update_mode_display(self, mode: str) -> None:
        with self.app.batch_update():
            self.remove_class('mode-basic', 'mode-text', 'mode-jql')
            self.add_class(f'mode-{mode}')

            work_item_input = self.query_one('#basic-work-item-key', Input)
            project_selector = self.query_one('#basic-project-selector', LazySelect)
            user_selector = self.query_one('#basic-assignee-selector', LazySelect)
            type_selector = self.query_one('#basic-type-selector', LazySelect)
            status_selector = self.query_one('#basic-status-selector', LazySelect)
            unified_input = self.query_one('#unified-search-input', Input)

            if self._jql_autocomplete:
                self._jql_autocomplete.disabled = mode != 'jql'

            if mode == 'basic':
                work_item_input.display = True
                project_selector.display = True
                user_selector.display = True
                type_selector.display = True
                status_selector.display = True
                unified_input.display = False
                unified_input.placeholder = ''

                unified_input.remove_class('-invalid')
            elif mode == 'text':
                work_item_input.display = False
                project_selector.display = False
                user_selector.display = False
                type_selector.display = False
                status_selector.display = False
                unified_input.display = True
                unified_input.placeholder = 'Enter text to search in summaries...'

                if not unified_input.value.strip():
                    unified_input.add_class('-invalid')
                else:
                    unified_input.remove_class('-invalid')
            elif mode == 'jql':
                work_item_input.display = False
                project_selector.display = False
                user_selector.display = False
                type_selector.display = False
                status_selector.display = False
                unified_input.display = True

                if hasattr(self, '_remote_filters_fetched') and self._remote_filters_fetched:
                    unified_input.placeholder = 'Enter JQL query or click for filter suggestions...'
                else:
                    unified_input.placeholder = 'Loading filters... (Enter JQL query or wait)'

                if not unified_input.value.strip():
                    unified_input.add_class('-invalid')
                else:
                    unified_input.remove_class('-invalid')

    def watch_projects(self, projects: dict | None) -> None:
        if projects and 'projects' in projects:
            project_selector = self.query_one('#basic-project-selector', LazySelect)

            if project_selector._has_loaded:
                project_selector.set_options(projects['projects'])
            else:
                if project_selector._is_loading:
                    project_selector._stop_spinner()

    def watch_users(self, users: dict | None) -> None:
        if users and 'users' in users:
            user_selector = self.query_one('#basic-assignee-selector', LazySelect)

            if user_selector._has_loaded:
                user_selector.set_options(users['users'])
            else:
                if user_selector._is_loading:
                    user_selector._stop_spinner()

    def watch_types(self, types: list[tuple[str, str]] | None) -> None:
        if types:
            type_selector = self.query_one('#basic-type-selector', LazySelect)

            if type_selector._has_loaded:
                type_selector.set_options(types)
            else:
                if type_selector._is_loading:
                    type_selector._stop_spinner()

    def watch_statuses(self, statuses: list[tuple[str, str]] | None) -> None:
        if statuses:
            status_selector = self.query_one('#basic-status-selector', LazySelect)

            if status_selector._has_loaded:
                status_selector.set_options(statuses)
            else:
                if status_selector._is_loading:
                    status_selector._stop_spinner()

    @work(exclusive=False, group='fetch-projects')
    async def fetch_projects(self) -> None:
        worker = get_current_worker()
        project_selector = self.query_one('#basic-project-selector', LazySelect)

        if not worker.is_cancelled:
            if self.projects and 'projects' in self.projects:
                project_selector.set_options(self.projects['projects'])
                project_selector._stop_spinner()
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

                project_selector._stop_spinner()

    @work(exclusive=False, group='fetch-users')
    async def fetch_users(self) -> None:
        worker = get_current_worker()
        user_selector = self.query_one('#basic-assignee-selector', LazySelect)

        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if (
                    self.users
                    and 'users' in self.users
                    and self._users_fetched_for_project == project_key
                ):
                    user_selector.set_options(self.users['users'])
                    user_selector._stop_spinner()
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
                    user_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching users: {str(e)}', severity='error', title='Search')
                user_selector._stop_spinner()
        else:
            user_selector._stop_spinner()

    @work(exclusive=False, group='fetch-types')
    async def fetch_work_item_types(self) -> None:
        worker = get_current_worker()
        type_selector = self.query_one('#basic-type-selector', LazySelect)

        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if self.types and self._types_fetched_for_project == project_key:
                    type_selector.set_options(self.types)
                    type_selector._stop_spinner()
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
                    type_selector._stop_spinner()
            except Exception as e:
                self.notify(
                    f'Error fetching issue types: {str(e)}', severity='error', title='Search'
                )
                type_selector._stop_spinner()
        else:
            type_selector._stop_spinner()

    @work(exclusive=False, group='fetch-statuses')
    async def fetch_statuses(self) -> None:
        worker = get_current_worker()
        status_selector = self.query_one('#basic-status-selector', LazySelect)

        if not worker.is_cancelled:
            try:
                project_key = self._selected_project_key

                if self.statuses and self._statuses_fetched_for_project == project_key:
                    status_selector.set_options(self.statuses)
                    status_selector._stop_spinner()
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
                        status_selector._stop_spinner()
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
                        status_selector._stop_spinner()
            except Exception as e:
                self.notify(f'Error fetching statuses: {str(e)}', severity='error', title='Search')
                status_selector._stop_spinner()
        else:
            status_selector._stop_spinner()

    def get_search_data(self) -> dict:
        mode = self.search_mode

        if mode == 'basic':
            return {
                'mode': 'basic',
                'work_item_key': self.query_one('#basic-work-item-key', Input).value,
                'project': self.query_one('#basic-project-selector', LazySelect).value,
                'assignee': self.query_one('#basic-assignee-selector', LazySelect).value,
                'type': self.query_one('#basic-type-selector', LazySelect).value,
                'status': self.query_one('#basic-status-selector', LazySelect).value,
            }
        elif mode == 'text':
            text = self.query_one('#unified-search-input', Input).value

            return {
                'mode': 'text',
                'jql': f'textfields ~ "{text}"' if text else '',
            }
        elif mode == 'jql':
            return {
                'mode': 'jql',
                'jql': self.query_one('#unified-search-input', Input).value,
            }

        return {'mode': mode}

    def set_initial_work_item_key(self, work_item_key: str) -> None:
        work_item_pattern = r'^[A-Z][A-Z0-9]+-\d+$'
        if not re.match(work_item_pattern, work_item_key):
            self.notify(
                f'Invalid work item key format: "{work_item_key}". Expected format: PROJECT-123',
                severity='error',
                timeout=10,
            )
            return

        try:
            work_item_input = self.query_one('#basic-work-item-key', Input)
            work_item_input.value = work_item_key
        except Exception as e:
            self.notify(
                f'Failed to set work item key: {str(e)}',
                severity='error',
                timeout=10,
                title='Search',
            )

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

        mode_selector = self.query_one('#search-mode-selector', Select)
        mode_selector.value = 'jql'

        jql_input = self.query_one('#unified-search-input', Input)

        cleaned_expression = filter_expression.replace('\n', ' ').replace('\t', ' ').strip()
        jql_input.value = cleaned_expression
