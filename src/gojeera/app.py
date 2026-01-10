import asyncio
from datetime import date
import logging
import os
from pathlib import Path
import sys
from typing import cast

from pythonjsonlogger.json import JsonFormatter
from rich.console import Console
from textual import on
from textual.app import App, ComposeResult, InvalidThemeError
from textual.binding import Binding
from textual.command import CommandPalette
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, LoadingIndicator, Select
from textual.worker import Worker

from gojeera.api_controller.controller import APIController, APIControllerResponse
from gojeera.commands.decision_provider import DecisionCommandProvider
from gojeera.commands.panel_provider import PanelCommandProvider
from gojeera.commands.user_mention_provider import UserMentionCommandProvider
from gojeera.components.debug_screen import DebugInfoScreen
from gojeera.components.new_work_item_screen import AddWorkItemScreen
from gojeera.components.quit_screen import QuitScreen
from gojeera.components.unified_search import UnifiedSearchBar
from gojeera.components.work_item_attachments import WorkItemAttachmentsWidget
from gojeera.components.work_item_comments import WorkItemCommentsWidget
from gojeera.components.work_item_fields import WorkItemFields, WorkItemUpdated
from gojeera.components.work_item_information import WorkItemInformation
from gojeera.components.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.components.work_item_result import (
    WorkItemContainer,
    WorkItemsContainer,
    WorkItemSearchResultsScroll,
)
from gojeera.components.work_item_subtasks import WorkItemChildWorkItemsWidget
from gojeera.components.work_item_summary import WorkItemInfoContainer
from gojeera.components.work_item_web_links import WorkItemRemoteLinksWidget
from gojeera.config import CONFIGURATION, ApplicationConfiguration
from gojeera.constants import (
    CSS_PATH,
    DEFAULT_THEME,
    LOGGER_NAME,
    TITLE,
)
from gojeera.files import get_log_file, get_themes_directory
from gojeera.models import (
    JiraMyselfInfo,
    JiraServerInfo,
    JiraWorkItem,
    JiraWorkItemSearchResponse,
    WorkItemSearchResult,
)
from gojeera.themes import load_themes_from_directory
from gojeera.utils.obfuscation import obfuscate_account_id
from gojeera.widgets.app_header import AppHeader
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.extended_tabbed_content import ExtendedTabbedContent


class MainScreen(Screen):
    """The main screen of the application."""

    BINDINGS = [
        Binding(
            key='ctrl+j',
            action='search',
            description='Search',
            tooltip='Search items by search criteria',
        ),
        Binding(
            key='ctrl+backslash',
            action='show_overlay',
            description='Jump',
            tooltip='Jump between widgets',
        ),
        Binding(
            key='ctrl+n',
            action='new_work_item',
            description='New Work Item',
            show=True,
        ),
        Binding(
            key='[',
            action='focus_previous',
            description='Previous Tab',
            show=False,
        ),
        Binding(
            key=']',
            action='focus_next',
            description='Next Tab',
            show=False,
        ),
    ]

    def __init__(
        self,
        api: APIController | None = None,
        project_key: str | None = None,
        assignee: str | None = None,
        jql_filter_label: str | None = None,
        work_item_key: str | None = None,
        focus_item_on_startup: int | None = None,
        user_info: JiraMyselfInfo | None = None,
    ):
        super().__init__()
        self.api = APIController() if not api else api
        self.user_info = user_info
        self.available_users: list[tuple[str, str]] = []
        self.initial_work_item_key = work_item_key
        self.initial_assignee = assignee
        self.initial_jql_filter_label: str | None = jql_filter_label
        self.focus_item_on_startup = focus_item_on_startup
        self.logger = logging.getLogger(LOGGER_NAME)
        self.current_loaded_work_item_key: str | None = None

    @property
    def tabs(self) -> ExtendedTabbedContent:
        return self.query_one('#tabs-information', ExtendedTabbedContent)

    @property
    def information_panel(self) -> WorkItemInformation:
        return self.query_one(WorkItemInformation)

    @property
    def fields_panel(self) -> WorkItemFields:
        return self.query_one(WorkItemFields)

    @property
    def search_results_list(self) -> WorkItemSearchResultsScroll:
        return self.query_one(WorkItemSearchResultsScroll)

    @property
    def search_results_container(self) -> WorkItemsContainer:
        return self.query_one(WorkItemsContainer)

    @property
    def work_item_fields_widget(self) -> WorkItemFields:
        return self.query_one(WorkItemFields)

    @property
    def work_item_comments_widget(self) -> WorkItemCommentsWidget:
        return self.query_one(WorkItemCommentsWidget)

    @property
    def related_work_items_widget(self) -> RelatedWorkItemsWidget:
        return self.query_one(RelatedWorkItemsWidget)

    @property
    def work_item_info_container(self) -> WorkItemInfoContainer:
        return self.query_one(WorkItemInfoContainer)

    @property
    def work_item_remote_links_widget(self) -> WorkItemRemoteLinksWidget:
        return self.query_one(WorkItemRemoteLinksWidget)

    @property
    def work_item_child_work_items_widget(self) -> WorkItemChildWorkItemsWidget:
        return self.query_one(WorkItemChildWorkItemsWidget)

    @property
    def work_item_attachments_widget(self) -> WorkItemAttachmentsWidget:
        return self.query_one(WorkItemAttachmentsWidget)

    @property
    def unified_search_bar(self) -> UnifiedSearchBar:
        return self.query_one(UnifiedSearchBar)

    @property
    def unified_search_mode_selector(self) -> Select:
        return self.query_one('#search-mode-selector', expect_type=Select)

    @property
    def unified_search_input(self) -> Input:
        return self.query_one('#unified-search-input', expect_type=Input)

    @property
    def unified_search_button(self) -> Button:
        return self.query_one('#unified-search-button', expect_type=Button)

    @property
    def work_item_loading_container(self) -> Center:
        return self.query_one('#work-item-loading-container', expect_type=Center)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        yield AppHeader(id='app-header')
        with Vertical(id='main-container'):
            yield UnifiedSearchBar(api=self.api, id='unified-search-bar')
            with Horizontal(id='three-split-layout'):
                yield WorkItemsContainer(id='search-results-container')

                with Center(id='work-item-loading-container'):
                    yield LoadingIndicator(id='work-item-loading-indicator')

                yield WorkItemInformation()

                yield WorkItemFields()
        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        if self.user_info:
            account_id = self.user_info.account_id
            self.logger.info(
                f'Using pre-authenticated account ID: {obfuscate_account_id(account_id)}'
            )
            search_bar = self.query_one('#unified-search-bar', UnifiedSearchBar)
            search_bar.post_message(search_bar.AccountIdReady(account_id))
        else:
            self.run_worker(self.fetch_and_cache_account_id(), name='fetch_account_id')

        if CONFIGURATION.get().jumper.enabled:
            self.query_one('#unified-search-bar', UnifiedSearchBar).jump_mode = 'focus'  # type: ignore[attr-defined]
            self.query_one('#search-results-container', WorkItemsContainer).jump_mode = 'focus'  # type: ignore[attr-defined]

        from textual.widgets import TabPane
        from textual.widgets._content_switcher import ContentSwitcher
        from textual.widgets._tabbed_content import ContentTab

        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)

        tab_panes = list(tabs.query(TabPane))
        for tab_pane in tab_panes:
            tab_pane.can_focus = False

        switchers = list(tabs.query(ContentSwitcher))
        for switcher in switchers:
            switcher.can_focus = False

        content_tabs = list(tabs.query(ContentTab))
        for content_tab in content_tabs:
            content_tab.can_focus = False
            if CONFIGURATION.get().jumper.enabled:
                content_tab.jump_mode = 'click'

        work_item_container = self.query_one(
            '#work-item-fields-container', expect_type=WorkItemFields
        )
        work_item_container.can_focus = False

        work_item_middle_container = self.query_one(
            '#work-item-middle-container', expect_type=Vertical
        )
        work_item_middle_container.can_focus = False

        self.tabs.disabled = True
        self.tabs.display = False
        self.fields_panel.disabled = True
        self.fields_panel.display = False

        search_bar = self.query_one('#unified-search-bar', UnifiedSearchBar)

        workers: list[Worker] = []

        if self.initial_work_item_key:
            search_bar.set_initial_work_item_key(self.initial_work_item_key)

        if self.initial_jql_filter_label:
            await search_bar.set_initial_jql_filter(self.initial_jql_filter_label)

        if CONFIGURATION.get().search_on_startup:
            if not self.initial_jql_filter_label:
                await self.app.workers.wait_for_complete(workers)
            search_worker = self.run_worker(self.action_search(), exclusive=True)

            if self.focus_item_on_startup:
                await self.app.workers.wait_for_complete([search_worker])
                self.run_worker(self._focus_item_after_startup(self.focus_item_on_startup))

        self.watch(
            self.work_item_attachments_widget, 'displayed_count', self._update_attachments_tab_title
        )
        self.watch(
            self.work_item_child_work_items_widget,
            'displayed_count',
            self._update_subtasks_tab_title,
        )
        self.watch(
            self.related_work_items_widget, 'displayed_count', self._update_related_tab_title
        )
        self.watch(
            self.work_item_remote_links_widget, 'displayed_count', self._update_links_tab_title
        )
        self.watch(
            self.work_item_comments_widget, 'displayed_count', self._update_comments_tab_title
        )

    async def fetch_and_cache_account_id(self) -> None:
        try:
            response = await self.api.myself()
            if response.success and response.result:
                from gojeera.models import JiraMyselfInfo

                myself_info: JiraMyselfInfo = response.result
                account_id = myself_info.account_id

                app = cast('JiraApp', self.app)  # noqa: F821
                app.user_info = myself_info

                self.logger.info(
                    f'Auto-detected and cached Jira account ID: {obfuscate_account_id(account_id)}'
                )

                search_bar = self.query_one('#unified-search-bar', UnifiedSearchBar)
                search_bar.post_message(search_bar.AccountIdReady(account_id))
            else:
                self.logger.warning(
                    f'Failed to auto-detect Jira account ID: {response.error}. '
                    'Comment edit/delete features may not work correctly.'
                )
        except Exception as e:
            self.logger.error(
                f'Error fetching current user account ID: {e}. '
                'Comment edit/delete features may not work correctly.'
            )

    def _update_attachments_tab_title(self, count: int) -> None:
        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)
        tab = tabs.get_tab('tab-attachments')
        if count > 0:
            tab.label = f'Attachments [bold $background on $primary] {count} [/]'
        else:
            tab.label = 'Attachments'

    def _update_subtasks_tab_title(self, count: int) -> None:
        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)
        tab = tabs.get_tab('tab-subtasks')
        if count > 0:
            tab.label = f'Subtasks [bold $background on $primary] {count} [/]'
        else:
            tab.label = 'Subtasks'

    def _update_related_tab_title(self, count: int) -> None:
        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)
        tab = tabs.get_tab('tab-related')
        if count > 0:
            tab.label = f'Related Items [bold $background on $primary] {count} [/]'
        else:
            tab.label = 'Related Items'

    def _update_links_tab_title(self, count: int) -> None:
        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)
        tab = tabs.get_tab('tab-links')
        if count > 0:
            tab.label = f'Web Links [bold $background on $primary] {count} [/]'
        else:
            tab.label = 'Web Links'

    def _update_comments_tab_title(self, count: int) -> None:
        tabs = self.query_one('#tabs-information', ExtendedTabbedContent)
        tab = tabs.get_tab('tab-comments')
        if count > 0:
            tab.label = f'Comments [bold $background on $primary] {count} [/]'
        else:
            tab.label = 'Comments'

    async def on_work_item_updated(self, message: WorkItemUpdated) -> None:
        await self.search_results_list.update_work_item_in_list(message.work_item)

    async def _search_work_items(
        self,
        next_page_token: str | None = None,
        calculate_total: bool = True,
        search_term: str | None = None,
        page: int | None = None,
    ) -> WorkItemSearchResult:
        search_data = self.unified_search_bar.get_search_data()
        mode = search_data.get('mode', 'basic')

        search_field_status: int | None = None
        search_field_created_from: date | None = None
        search_field_created_until: date | None = None
        search_field_assignee: str | None = None
        search_field_work_item_type: int | None = None
        project_key: str | None = None
        jql_expression: str | None = None

        if mode == 'basic':
            project_key = search_data.get('project')
            search_field_assignee = search_data.get('assignee')

            work_item_type_str = search_data.get('type')
            search_field_work_item_type = (
                int(work_item_type_str)
                if work_item_type_str and work_item_type_str != Select.BLANK
                else None
            )
            status_str = search_data.get('status')
            search_field_status = (
                int(status_str) if status_str and status_str != Select.BLANK else None
            )

            if project_key == Select.BLANK:
                project_key = None
            if search_field_assignee == Select.BLANK:
                search_field_assignee = None
        elif mode in ('text', 'jql'):
            jql_expression = search_data.get('jql')

        jql_query: str | None = self._build_jql_query(
            search_term=search_term,
            jql_expression=jql_expression,
            use_advance_search=CONFIGURATION.get().enable_advanced_full_text_search,
        )

        if (
            mode == 'basic'
            and not jql_query
            and not any(
                [
                    project_key,
                    search_field_assignee,
                    search_field_work_item_type,
                    search_field_status,
                ]
            )
        ):
            jql_query = 'created >= -30d order by created DESC'

        response: APIControllerResponse
        response = await self.api.search_work_items(
            project_key=project_key,
            created_from=search_field_created_from,
            created_until=search_field_created_until,
            status=search_field_status,
            assignee=search_field_assignee,
            work_item_type=search_field_work_item_type,
            search_in_active_sprint=False,
            jql_query=jql_query,
            next_page_token=next_page_token,
            limit=CONFIGURATION.get().search_results_per_page,
        )

        if not response.success or response.result is None:
            error_message = (
                response.error
                if response.error
                else 'There was an error while performing the search'
            )
            self.notify(
                error_message,
                severity='warning',
                title='Work Item Search',
            )
            return WorkItemSearchResult(total=0, start=0, end=0, response=None)

        result: JiraWorkItemSearchResponse = response.result
        estimated_total_work_items: int = 0
        if calculate_total:
            counting: APIControllerResponse = await self.api.count_work_items(
                project_key=project_key,
                created_from=search_field_created_from,
                created_until=search_field_created_until,
                status=search_field_status,
                assignee=search_field_assignee,
                work_item_type=search_field_work_item_type,
                jql_query=jql_query,
            )
            if counting.success and counting.result is not None:
                estimated_total_work_items = counting.result
            else:
                estimated_total_work_items = 0

                count_error = (
                    counting.error
                    if counting.error
                    else 'Failed to calculate the number of work items'
                )
                self.notify(
                    count_error,
                    title='Work Items Search',
                    severity='warning',
                )

        work_item_count = len(result.work_items)
        return WorkItemSearchResult(
            response=result,
            total=estimated_total_work_items if estimated_total_work_items else 0,
            start=1 if work_item_count else 0,
            end=work_item_count,
        )

    @staticmethod
    def _build_jql_query(
        search_term: str | None = None,
        jql_expression: str | None = None,
        use_advance_search: bool = False,
    ) -> str | None:
        if search_term:
            if use_advance_search:
                return f'text ~ "{search_term}"'
            return f'summary ~ "{search_term}" OR description ~ "{search_term}"'
        elif jql_expression:
            return jql_expression
        return None

    async def _search_single_work_item(self, work_item_key: str) -> WorkItemSearchResult:
        response: APIControllerResponse = await self.api.get_work_item(
            work_item_id_or_key=work_item_key, fields=['summary', 'status', 'issuetype', 'parent']
        )
        if not response.success:
            self.notify(
                response.error or 'Unable to fetch the given work item',
                title='Work Items Search',
                severity='error',
            )
            return WorkItemSearchResult(total=0, start=0, end=0, response=None)
        if not response.result:
            self.notify(
                f'The selected work item {work_item_key} was not found',
                title='Work Items Search',
                severity='error',
            )
            return WorkItemSearchResult(total=0, start=0, end=0, response=None)
        total = len(response.result.work_items or [])
        return WorkItemSearchResult(response=response.result, total=total, start=total, end=total)

    async def search_work_items(
        self,
        next_page_token: str | None = None,
        search_term: str | None = None,
        page: int | None = None,
    ) -> None:
        self.search_results_container.show_loading()
        results: WorkItemSearchResult

        search_data = self.unified_search_bar.get_search_data()
        mode = search_data.get('mode')
        work_item_key = search_data.get('work_item_key', '').strip() if mode == 'basic' else ''

        if mode in ('text', 'jql'):
            jql = search_data.get('jql', '').strip()
            if not jql:
                self.search_results_container.hide_loading()
                self.notify(
                    'Please enter a search term or JQL query',
                    severity='warning',
                    title='Search Warning',
                )
                return

            if mode == 'jql':
                validation_result = await self.api.validate_jql_query(jql)
                if not validation_result.success:
                    self.search_results_container.hide_loading()

                    self.search_results_list.work_item_search_results = None
                    self.notify(
                        validation_result.error or 'JQL validation failed',
                        severity='warning',
                        title='JQL Validation Error',
                    )
                    return

        if work_item_key:
            results = await self._search_single_work_item(work_item_key)
        else:
            results = await self._search_work_items(
                next_page_token=next_page_token, search_term=search_term, page=page
            )

        list_view = self.search_results_list

        list_view.work_item_search_results = results.response
        list_view.focus()

        total_pages = 1
        if results.total > 0:
            total_pages = results.total // CONFIGURATION.get().search_results_per_page
            if (results.total % CONFIGURATION.get().search_results_per_page) > 0:
                total_pages += 1

        list_view.total_pages = total_pages

        self.search_results_container.pagination = {
            'total': results.total,
            'current_page_number': self.search_results_list.page,
        }
        self.search_results_container.hide_loading()

    @on(Button.Pressed, '#unified-search-button')
    async def handle_unified_search_button(self) -> None:
        self.run_worker(self.action_search())

    def _is_any_select_expanded(self) -> bool:
        for select in self.query(Select):
            if select.expanded:
                return True
        return False

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return

        if self._is_any_select_expanded():
            return

        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def action_search(self, search_term: str | None = None) -> None:
        if self._is_any_select_expanded():
            return

        search_data = self.unified_search_bar.get_search_data()
        mode = search_data.get('mode')

        if mode == 'basic':
            if not self.unified_search_bar.is_work_item_key_valid():
                self.notify(
                    'Invalid work item key format. Expected format: PROJECT-123',
                    severity='warning',
                    title='Validation Error',
                )
                return

        self.information_panel.work_item = None

        self.tabs.disabled = True
        self.tabs.display = False
        self.fields_panel.disabled = True
        self.fields_panel.display = False

        self.work_item_info_container.clear_information = True

        self.work_item_fields_widget.work_item = None

        self.current_loaded_work_item_key = None

        self.work_item_comments_widget.comments = None
        self.work_item_comments_widget.work_item_key = None

        self.related_work_items_widget.work_item_key = None
        self.related_work_items_widget.work_items = None

        self.work_item_remote_links_widget.work_item_key = None

        self.work_item_attachments_widget.attachments = None
        self.work_item_attachments_widget.work_item_key = None

        self.work_item_child_work_items_widget.work_items = None
        self.work_item_child_work_items_widget.work_item_key = None

        self.search_results_list.page = 1

        self.search_results_list.token_by_page = {}

        next_page_token: str | None = self.search_results_list.token_by_page.get(
            self.search_results_list.page
        )

        self.run_worker(
            self.search_work_items(
                next_page_token=next_page_token,
                search_term=search_term,
                page=self.search_results_list.page,
            ),
            exclusive=True,
        )

    async def action_new_work_item(self) -> None:
        await self.app.push_screen(
            AddWorkItemScreen(
                project_key=None,
                reporter_account_id=self.user_info.account_id if self.user_info else None,
            ),
            callback=self.new_work_item,
        )

    async def new_work_item(self, data: dict | None) -> None:
        if data:
            base_fields = {
                'project_key',
                'parent_key',
                'work_item_type_id',
                'assignee_account_id',
                'reporter_account_id',
                'summary',
                'description',
                'duedate',
                'priority',
            }

            base_data = {k: v for k, v in data.items() if k in base_fields}
            dynamic_fields = {k: v for k, v in data.items() if k not in base_fields}

            self.logger.info(
                'Creating work item with split fields',
                extra={
                    'base_data': base_data,
                    'dynamic_fields': dynamic_fields,
                    'all_data_keys': list(data.keys()),
                    'dynamic_field_types': {k: type(v).__name__ for k, v in dynamic_fields.items()},
                },
            )

            response: APIControllerResponse = await self.api.new_work_item(
                base_data, **dynamic_fields
            )
            if response.success and response.result:
                self.notify(
                    f'Work item {response.result.key} created successfully',
                    title='Create Work Item',
                )

                if 'parent_key' in base_data and base_data['parent_key']:
                    parent_key = base_data['parent_key']

                    await self.retrieve_work_item_subtasks(parent_key)
            else:
                self.logger.error('Failed to create the work item', extra={'error': response.error})
                self.notify(
                    f'Failed to create the work item: {response.error}',
                    severity='error',
                    title='Create Work Item',
                )

    async def retrieve_work_item_subtasks(self, work_item_key: str) -> None:
        if work_item_key:
            self.work_item_child_work_items_widget.work_items = None
            self.work_item_child_work_items_widget.show_loading()
            self.work_item_child_work_items_widget.work_item_key = work_item_key
            response: APIControllerResponse = await self.api.search_work_items(
                jql_query=f'parent={work_item_key}',
                fields=['id', 'key', 'status', 'summary', 'issuetype', 'assignee'],
            )
            if not response.success:
                self.logger.error(
                    'Unable to retrieve the sub tasks of the work item',
                    extra={'error': response.error, 'work_item_key': work_item_key},
                )
                self.notify(
                    'Unable to retrieve the sub tasks of the work item',
                    severity='warning',
                    title='Work Item Search',
                )
                self.work_item_child_work_items_widget.work_items = None
            else:
                if response.result:
                    self.work_item_child_work_items_widget.work_items = response.result.work_items
                else:
                    self.work_item_child_work_items_widget.work_items = None

            self.work_item_child_work_items_widget.hide_loading()

    async def fetch_work_items(self, selected_work_item_key: str) -> None:
        if not selected_work_item_key:
            self.notify(
                'You need to select a work item before fetching its details.',
                title='Find Work Item',
                severity='error',
            )
            return

        if self.current_loaded_work_item_key == selected_work_item_key:
            return

        self.work_item_loading_container.display = True

        self.information_panel.display = False
        self.fields_panel.display = False

        self.work_item_info_container.show_loading()
        self.work_item_comments_widget.show_loading()
        self.related_work_items_widget.show_loading()
        self.work_item_attachments_widget.show_loading()
        self.work_item_child_work_items_widget.show_loading()
        if CONFIGURATION.get().show_work_item_web_links:
            self.work_item_remote_links_widget.show_loading()

        self.work_item_fields_widget.work_item = None

        self.work_item_fields_widget.content_container.display = False

        async def fetch_main_work_item() -> tuple[bool, APIControllerResponse]:
            response = await self.api.get_work_item(
                work_item_id_or_key=selected_work_item_key,
            )
            return response.success, response

        async def fetch_subtasks() -> tuple[bool, APIControllerResponse]:
            response = await self.api.search_work_items(
                jql_query=f'parent={selected_work_item_key}',
                fields=['id', 'key', 'status', 'summary', 'issuetype', 'assignee'],
            )
            return response.success, response

        (main_success, main_response), (subtasks_success, subtasks_response) = await asyncio.gather(
            fetch_main_work_item(),
            fetch_subtasks(),
        )

        if not main_success or not main_response.result:
            self.work_item_loading_container.display = False

            self.work_item_info_container.hide_loading()
            self.work_item_comments_widget.hide_loading()
            self.related_work_items_widget.hide_loading()
            self.work_item_attachments_widget.hide_loading()
            self.work_item_child_work_items_widget.hide_loading()
            if CONFIGURATION.get().show_work_item_web_links:
                self.work_item_remote_links_widget.hide_loading()
            self.notify(
                'Unable to find the selected work item', title='Find Work Item', severity='error'
            )
            return

        result: JiraWorkItemSearchResponse = main_response.result
        work_item: JiraWorkItem = result.work_items[0]

        self.information_panel.work_item = work_item

        self.tabs.disabled = False

        self.fields_panel.disabled = False
        self.fields_panel.display = True

        if work_item.work_item_type and work_item.work_item_type.subtask:
            self.tabs.hide_tab('tab-subtasks')
        else:
            self.tabs.show_tab('tab-subtasks')

        self.work_item_info_container.work_item = work_item
        self.work_item_fields_widget.available_users = self.available_users
        self.work_item_fields_widget.work_item = work_item

        self.current_loaded_work_item_key = selected_work_item_key

        self.related_work_items_widget.work_item_key = work_item.key
        self.related_work_items_widget.work_items = work_item.related_work_items
        self.related_work_items_widget.hide_loading()

        self.work_item_comments_widget.work_item_key = work_item.key
        self.work_item_comments_widget.comments = work_item.comments
        self.work_item_comments_widget.hide_loading()

        self.work_item_attachments_widget.work_item_key = work_item.key
        self.work_item_attachments_widget.attachments = work_item.attachments
        self.work_item_attachments_widget.hide_loading()

        self.work_item_child_work_items_widget.work_item_key = work_item.key
        if subtasks_success and subtasks_response.result:
            self.work_item_child_work_items_widget.work_items = subtasks_response.result.work_items
        else:
            if not subtasks_success:
                self.logger.error(
                    'Unable to retrieve the sub tasks of the work item',
                    extra={'error': subtasks_response.error, 'work_item_key': work_item.key},
                )
            self.work_item_child_work_items_widget.work_items = None
        self.work_item_child_work_items_widget.hide_loading()

        if CONFIGURATION.get().show_work_item_web_links:
            self.work_item_remote_links_widget.work_item_key = work_item.key

    def _try_hide_loading_coordinated(self) -> None:
        info_container = self.work_item_info_container

        if info_container._content_ready and info_container._fields_widget_ready:
            info_container.hide_loading()

            info_container._content_ready = False
            info_container._fields_widget_ready = False

            try:
                work_item_info = self.information_panel

                if work_item_info.work_item is not None:
                    work_item_info.breadcrumb_widget.display = True
                    tabs_widget = self.tabs
                    tabs_widget.display = True
                    tabs_widget.disabled = False

                    self.work_item_loading_container.display = False

                    self.information_panel.display = True
                    self.fields_panel.display = True
            except Exception as e:
                self.logger.error(f'Failed to signal WorkItemInformation: {e}')

                self.work_item_loading_container.display = False

    async def clone_work_item(self, work_item_key: str) -> None:
        if not work_item_key:
            self.notify(
                'No work item selected to clone', severity='warning', title='Clone Work Item'
            )
            return

        response: APIControllerResponse = await self.api.get_work_item(
            work_item_id_or_key=work_item_key,
        )

        if not response.success or not response.result:
            self.notify(
                f'Unable to fetch work item {work_item_key} for cloning',
                title='Clone Work Item',
                severity='error',
            )
            return

        result: JiraWorkItemSearchResponse = response.result
        work_item: JiraWorkItem = result.work_items[0]

        from gojeera.components.clone_work_item_screen import CloneWorkItemScreen

        clone_config = await self.app.push_screen_wait(
            CloneWorkItemScreen(
                work_item_key=work_item.key,
                original_summary=work_item.summary,
            )
        )

        if not clone_config or not clone_config.get('clone'):
            return

        custom_summary = clone_config.get('summary')

        self.notify(f'Cloning work item {work_item_key}...', title=work_item_key)

        clone_response: APIControllerResponse = await self.api.clone_work_item(
            work_item=work_item,
            link_to_original=True,
            custom_summary=custom_summary,
        )

        if clone_response.success and clone_response.result:
            cloned_key = clone_response.result.get('key')
            self.notify(
                f'Work item cloned successfully as {cloned_key}',
                title=work_item_key,
            )

            await self.fetch_work_items(cloned_key)
        else:
            error_msg = clone_response.error if clone_response.error else 'Unknown error'
            self.notify(
                f'Failed to clone work item: {error_msg}',
                severity='error',
                title=work_item_key,
            )

    def action_focus_next(self) -> None:
        if not self.tabs.disabled and self.tabs.tab_count > 0:
            from textual.widgets._tabbed_content import ContentTab

            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active

            content_tabs = {
                tab.id.removeprefix('--content-tab-'): tab
                for tab in self.tabs.query(ContentTab)
                if tab.id
            }

            tab_ids = [
                pane.id
                for pane in tab_panes
                if pane.id and content_tabs.get(pane.id) and content_tabs[pane.id].display
            ]

            if current_active in tab_ids:
                current_index = tab_ids.index(current_active)
                if current_index < len(tab_ids) - 1:
                    next_id = tab_ids[current_index + 1]
                    self.tabs.active = next_id

    def action_focus_previous(self) -> None:
        if not self.tabs.disabled and self.tabs.tab_count > 0:
            from textual.widgets._tabbed_content import ContentTab

            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active

            content_tabs = {
                tab.id.removeprefix('--content-tab-'): tab
                for tab in self.tabs.query(ContentTab)
                if tab.id
            }

            tab_ids = [
                pane.id
                for pane in tab_panes
                if pane.id and content_tabs.get(pane.id) and content_tabs[pane.id].display
            ]

            if current_active in tab_ids:
                current_index = tab_ids.index(current_active)
                if current_index > 0:
                    prev_id = tab_ids[current_index - 1]
                    self.tabs.active = prev_id

    async def _focus_item_after_startup(self, position: int) -> None:
        scroll_view = self.search_results_list

        max_attempts = 50
        attempt = 0
        item_count = 0

        while attempt < max_attempts:
            await self.app.animator.wait_for_idle()
            await asyncio.sleep(0.1)
            item_count = len(scroll_view.work_item_containers)
            if item_count > 0:
                break
            attempt += 1

        if item_count == 0:
            self.notify(
                'Search results are empty or still loading.',
                severity='warning',
                title='Focus Work Item',
            )
            return

        if position < 1 or position > item_count:
            self.notify(
                f'Position {position} is out of range. Search results contain {item_count} item(s).',
                severity='warning',
                title='Focus Work Item',
            )
            return

        item_index = position - 1

        containers = scroll_view.work_item_containers
        if item_index >= len(containers):
            return

        work_item_container = containers[item_index]
        if not isinstance(work_item_container, WorkItemContainer):
            return

        scroll_view._selected_index = item_index
        scroll_view._update_selection()

        scroll_view.scroll_to_widget(work_item_container, animate=False)

        await asyncio.sleep(0.1)
        await self.app.animator.wait_for_idle()

        await scroll_view._select_work_item(work_item_container.work_item_key)

        await asyncio.sleep(0.3)
        await self.app.animator.wait_for_idle()

        self.work_item_info_container.focus()


class JiraApp(App):
    CSS_PATH = CSS_PATH

    TITLE = TITLE
    BINDINGS = [
        Binding(
            key='ctrl+c',
            action='quit',
            description='Quit',
            tooltip='Quit',
            show=True,
        ),
        Binding(key='ctrl+q', action='', description=''),
        Binding(key='question_mark', action='help', description='Help'),
        Binding(
            key='f12',
            action='debug_info',
            description='Debug',
            tooltip='Show debug information (config, server, user)',
        ),
    ]
    DEFAULT_THEME = DEFAULT_THEME

    COMMANDS = App.COMMANDS | {
        PanelCommandProvider,
        DecisionCommandProvider,
        UserMentionCommandProvider,
    }

    def __init__(
        self,
        settings: ApplicationConfiguration,
        user_info: JiraMyselfInfo | None = None,
        project_key: str | None = None,
        assignee: str | None = None,
        jql_filter: str | None = None,
        work_item_key: str | None = None,
        user_theme: str | None = None,
        focus_item_on_startup: int | None = None,
    ):
        super().__init__()
        self.config = settings
        CONFIGURATION.set(settings)
        self.api = APIController()
        self.user_info = user_info

        self.initial_work_item_key: str | None = None
        if work_item_key and (cleaned_work_item_key := work_item_key.strip()):
            self.initial_work_item_key = cleaned_work_item_key

        self.initial_assignee: str | None = None

        if assignee and (cleaned_assignee := assignee.strip()):
            self.initial_assignee = cleaned_assignee

        self.initial_jql_filter_label: str | None = jql_filter

        self.focus_item_on_startup: int | None = focus_item_on_startup

        self.server_info: JiraServerInfo | None = None
        self._setup_logging()
        self._register_custom_themes()
        self._setup_theme(user_theme)

    def _register_custom_themes(self) -> None:
        try:
            themes_dir = get_themes_directory()
            directory_themes = load_themes_from_directory(themes_dir)
            for theme in directory_themes:
                self.register_theme(theme)
                self.logger.info(f'Registered custom theme from directory: {theme.name}')
        except Exception as e:
            self.logger.warning(f'Error loading themes from directory: {str(e)}')

    def _setup_theme(self, user_theme: str | None = None) -> None:
        if input_theme := (user_theme or CONFIGURATION.get().theme):
            try:
                self.theme = input_theme
            except InvalidThemeError:
                self.logger.warning(
                    f'Unknown theme {input_theme}. Using the default theme: {self.DEFAULT_THEME}'
                )
                self.theme = self.DEFAULT_THEME
        else:
            self.theme = self.DEFAULT_THEME

    async def on_mount(self) -> None:
        try:
            response = await self.api.server_info()
            if response.success and response.result:
                server_info = response.result
                self.server_info = server_info
                self.logger.info(f'Fetched server info: {server_info.base_url}')
            else:
                self.logger.warning(f'Failed to fetch server info: {response.error}')
        except Exception as e:
            self.logger.warning(f'Failed to fetch server info: {e}')

        await self.push_screen(
            MainScreen(
                self.api,
                None,
                self.initial_assignee,
                self.initial_jql_filter_label,
                self.initial_work_item_key,
                self.focus_item_on_startup,
                self.user_info,
            )
        )

    async def action_help(self) -> None:
        from gojeera.components.help_screen import HelpScreen

        focused = self.focused

        def restore_focus(response) -> None:
            if focused:
                self.screen.set_focus(focused)

        self.set_focus(None)
        anchor: str | None = None
        if focused and hasattr(focused, 'help_anchor'):
            anchor = str(getattr(focused, 'help_anchor', None))
        await self.push_screen(HelpScreen(anchor), restore_focus)

    async def action_debug_info(self) -> None:
        await self.push_screen(DebugInfoScreen())

    async def action_quit(self) -> None:
        if CONFIGURATION.get().confirm_before_quit:
            await self.push_screen(QuitScreen())
        else:
            await self.api.api.client.close_async_client()
            await self.api.api.async_http_client.close_async_client()
            self.app.exit()

    def action_command_palette(self) -> None:
        if isinstance(self.screen, CommandPalette):
            self.pop_screen()
        else:
            super().action_command_palette()

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger(LOGGER_NAME)
        self.logger.setLevel(CONFIGURATION.get().log_level or logging.WARNING)

        if jira_tui_log_file := os.getenv('GOJEERA_LOG_FILE'):
            log_file = Path(jira_tui_log_file).resolve()
        elif config_log_file := CONFIGURATION.get().log_file:
            log_file = Path(config_log_file).resolve()
        else:
            log_file = get_log_file()

        try:
            fh = logging.FileHandler(log_file)
        except Exception as e:
            self.logger.warning(f'Failed to create log file handler: {e}')
        else:
            fh.setLevel(CONFIGURATION.get().log_level or logging.WARNING)
            fh.setFormatter(
                JsonFormatter(
                    '%(asctime)s %(levelname)s %(message)s %(lineno)s %(module)s %(pathname)s '
                )
            )
            self.logger.addHandler(fh)


if __name__ == '__main__':
    console = Console()

    try:
        settings = ApplicationConfiguration()

        async def check_auth() -> tuple[bool, str | None, JiraMyselfInfo | None]:
            from gojeera.api_controller.controller import APIController

            try:
                api = APIController(configuration=settings)
                response = await api.myself()

                try:
                    await api.api.client.close_async_client()
                    await api.api.async_http_client.close_async_client()
                except Exception:  # nosec B110
                    # Silently ignore errors when closing clients at module level
                    pass

                if not response.success:
                    if response.error:
                        error = str(response.error)
                        error_msg = error.lower()

                        if 'contextvar' in error_msg or ('<' in error_msg and '0x' in error_msg):
                            return False, 'Please check your credentials.', None
                        elif 'unauthorized' in error_msg or '401' in error_msg:
                            return False, 'Please check your credentials.', None
                        elif 'forbidden' in error_msg or '403' in error_msg:
                            return False, 'Access forbidden. Please check your permissions.', None
                        else:
                            return False, error, None
                    return False, 'Please check your credentials.', None

                if response.result is None:
                    return False, 'Authentication succeeded but no user info received.', None

                user_info: JiraMyselfInfo = response.result
                return True, None, user_info

            except Exception as e:
                error = str(e)
                error_msg = error.lower()

                if 'contextvar' in error_msg or ('<' in error_msg and '0x' in error_msg):
                    return False, 'Please check your credentials.', None
                elif 'certificate' in error_msg or 'ssl' in error_msg:
                    return False, 'SSL certificate error.', None
                elif 'connection' in error_msg:
                    return (
                        False,
                        'Connection error. Please check your network and Jira instance URL.',
                        None,
                    )
                elif 'timeout' in error_msg:
                    return False, 'Connection timed out.', None
                else:
                    return False, error, None

        success, error_message, user_info = asyncio.run(check_auth())

        if not success:
            console.print(f'[bold red]Authentication failed:[/bold red] {error_message}')
            sys.exit(1)

        JiraApp(settings, user_info=user_info).run()
    except Exception as e:
        console.print(f'[bold red]Error:[/bold red] {str(e)}')
        sys.exit(1)
