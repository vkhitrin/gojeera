from __future__ import annotations

import asyncio
from datetime import date
from inspect import isawaitable
import logging
import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any, cast

from pythonjsonlogger.json import JsonFormatter
from textual import events, on
from textual.app import App, ComposeResult, InvalidThemeError
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import Reactive, reactive
from textual.theme import Theme
from textual.widget import Widget
from textual.widgets import Button, Input, Select, Static, TabPane
from textual.widgets._tabbed_content import ContentTab
from textual.worker import Worker

from gojeera.commands.binding_provider import (
    build_toggle_footer_binding,
    register_binding_in_command_palette,
)
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.components.work_item.work_item_description import (
    WorkItemInfoContainer,
    WorkItemSummary,
)
from gojeera.components.work_item.work_item_fields import WorkItemFields
from gojeera.components.work_item.work_item_information import (
    WORK_ITEM_WORKLOG_BINDINGS,
    WorkItemBreadcrumb,
    WorkItemInformation,
)
from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.components.work_item.work_item_subtasks import WorkItemChildWorkItemsWidget
from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget
from gojeera.internal.jira.controller import APIController
from gojeera.internal.models.jira import Attachment
from gojeera.internal.models.work_items import WorkItemSearchResult
from gojeera.internal.models.atlassian import AtlassianContext
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.config import CONFIGURATION, ApplicationConfiguration
from gojeera.internal.store.files import get_log_file, get_themes_directory
from gojeera.internal.styling.themes import load_themes_from_directory
from gojeera.utils.jira.reference import (
    WorkItemNavigationTarget,
    WorkItemReferenceLoader,
    load_work_item_reference,
)
from gojeera.utils.jira.urls import (
    build_external_url_for_attachment,
    build_external_url_for_work_item,
)
from gojeera.utils.system.logging_utils import build_log_extra
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.markdown.gojeera_markdown import ExtendedMarkdownParagraph
from gojeera.widgets.navigation.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.navigation.extended_palette import ExtendedPalette
from gojeera.widgets.navigation.extended_tabbed_content import ExtendedTabbedContent
from gojeera.widgets.search.work_item_search_results_scroll import (
    WorkItemSearchResultsScroll,
)
from gojeera.widgets.search.work_items_container import WorkItemsContainer

if TYPE_CHECKING:
    from textual.command import Provider

    from gojeera.components.work_item.work_item_attachments import WorkItemAttachmentsWidget
    from gojeera.components.work_item.work_item_comments import WorkItemCommentsWidget
    from gojeera.components.work_item.work_item_fields import WorkItemUpdated
    from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
    from gojeera.internal.jira.controller import APIControllerResponse
    from gojeera.internal.models.jira import JiraMyselfInfo
    from gojeera.internal.models.work_items import (
        JiraWorkItem,
        JiraWorkItemSearchResponse,
    )

CSS_PATH = 'internal/styling/gojeera.tcss'
TITLE = 'gojeera'
DEFAULT_THEME = 'textual-dark'


def get_panel_command_provider() -> type[Provider]:
    from gojeera.commands.providers.panel_provider import PanelCommandProvider

    return PanelCommandProvider


def get_decision_command_provider() -> type[Provider]:
    from gojeera.commands.providers.decision_provider import DecisionCommandProvider

    return DecisionCommandProvider


def get_registered_binding_command_provider() -> type[Provider]:
    from gojeera.commands.binding_provider import RegisteredBindingCommandProvider

    return RegisteredBindingCommandProvider


def get_work_item_command_provider() -> type[Provider]:
    from gojeera.commands.providers.work_item_command_provider import WorkItemCommandProvider

    return WorkItemCommandProvider


def get_create_command_provider() -> type[Provider]:
    from gojeera.commands.providers.create_command_provider import CreateCommandProvider

    return CreateCommandProvider


def get_user_mention_command_provider() -> type[Provider]:
    from gojeera.commands.providers.user_mention_provider import UserMentionCommandProvider

    return UserMentionCommandProvider


def get_search_command_provider() -> type[Provider]:
    from gojeera.commands.providers.search_command_provider import SearchCommandProvider

    return SearchCommandProvider


def get_quick_navigation_provider() -> type[Provider]:
    from gojeera.commands.providers.quick_navigation_provider import QuickNavigationProvider

    return QuickNavigationProvider


def get_recently_viewed_work_items_provider() -> type[Provider]:
    from gojeera.commands.providers.recently_viewed_work_items_provider import (
        RecentlyViewedWorkItemsProvider,
    )

    return RecentlyViewedWorkItemsProvider


class WorkspaceMixin(App):
    """Workspace behavior hosted directly on the application."""

    atlassian_context: AtlassianContext
    is_loading: Reactive[bool] = reactive(False, always_update=True)
    BINDINGS = [
        Binding(
            key='ctrl+j',
            action='search',
            description='Search',
            tooltip='Search items by search criteria',
        ),
        Binding(
            key='ctrl+o',
            action='open_contextual_browser_target',
            description='Browse',
            show=False,
            priority=True,
        ),
        Binding(
            key='ctrl+e',
            action='edit_work_item_info',
            description='Edit Info',
            tooltip='Edit summary and description',
            show=True,
        ),
        Binding(
            key='ctrl+r',
            action='reload_loaded_work_item',
            description='Reload',
            tooltip='Reload the active work item',
            show=True,
        ),
        Binding(
            key='ctrl+s',
            action='apply_changes',
            description='Apply Changes',
            tooltip='Apply pending field changes',
            show=True,
        ),
        Binding(
            key='ctrl+z',
            action='discard_changes',
            description='Discard Changes',
            tooltip='Discard pending field changes',
            show=True,
        ),
        Binding(
            key='ctrl+g',
            action='go_to_parent_work_item',
            description='Go To Parent',
            tooltip='Load the parent work item',
            show=True,
        ),
        *WORK_ITEM_WORKLOG_BINDINGS,
        register_binding_in_command_palette(
            Binding(
                key='ctrl+backslash',
                action='show_overlay',
                description='Jump',
                tooltip='Jump between widgets',
                show=False,
            )
        ),
        Binding(
            key='ctrl+n',
            action='create_work_item',
            description='Create Work Item',
            show=True,
            id='create_work_item',
            tooltip='Create Work Item',
        ),
        Binding(
            key='[',
            action='previous_detail_tab',
            description='Previous Tab',
            show=False,
        ),
        Binding(
            key=']',
            action='next_detail_tab',
            description='Next Tab',
            show=False,
        ),
    ]

    def _init_workspace(
        self,
        api: APIController,
        project_key: str | None = None,
        assignee: str | None = None,
        jql_filter_label: str | None = None,
        work_item_key: str | None = None,
        focus_item_on_startup: int | None = None,
        user_info: JiraMyselfInfo | None = None,
    ) -> None:
        del project_key
        self.api = api
        self.atlassian_context.user_info = user_info
        self.available_users: list[tuple[str, str]] = []
        self.initial_work_item_key = work_item_key
        self.initial_assignee = assignee
        self.initial_jql_filter_label: str | None = jql_filter_label
        self.focus_item_on_startup = focus_item_on_startup
        self.logger = logging.getLogger('gojeera')
        self.current_loaded_work_item_key: str | None = None
        self.active_sub_command_palette_id: str | None = None
        self.focused_work_item_link_key: str | None = None
        self._pending_work_item_navigation_target: WorkItemNavigationTarget | None = None
        self._active_search_data: dict | None = None
        self._active_search_term: str | None = None
        self._active_work_item_load_key: str | None = None
        self._comments_loading_worker: Worker | None = None
        self._subtasks_loading_worker: Worker | None = None
        self._pending_screen_types: set[type[object]] = set()

    def set_focus(
        self,
        widget,
        scroll_visible: bool = True,
        from_app_focus: bool = False,
    ) -> None:
        self.screen.set_focus(widget, scroll_visible, from_app_focus=from_app_focus)
        self._sync_jump_targets()

    def _sync_jump_targets(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        search_results_container = self.query_one('#search-results-container', WorkItemsContainer)
        search_results_list = self.search_results_list
        set_jump_mode(
            search_results_container,
            None if self.focused is search_results_list else 'focus',
        )

    async def _on_key(self, event: events.Key) -> None:
        if event.key == 'ctrl+g' and self.focused_work_item_link_key:
            event.prevent_default()
            event.stop()
            self.run_worker(
                self.load_work_item(self.focused_work_item_link_key),
                exclusive=True,
            )
            return

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
        return cast('WorkItemCommentsWidget', self.query_one('#work_item_comments'))

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
        return cast('WorkItemAttachmentsWidget', self.query_one('#attachments'))

    @property
    def work_item_history_widget(self) -> WorkItemHistoryWidget:
        return cast('WorkItemHistoryWidget', self.query_one('#work_item_history'))

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
    def details_container(self) -> Vertical:
        return self.query_one('#details-container', expect_type=Vertical)

    @property
    def details_breadcrumb_row(self) -> Vertical:
        return self.query_one('#details-breadcrumb-row', Vertical)

    @property
    def details_tabs_row(self) -> Horizontal:
        return self.query_one('#details-tabs-row', Horizontal)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with Vertical(id='main-container'):
            yield UnifiedSearchBar(api=self.api, id='unified-search-bar')
            with Horizontal(id='three-split-layout'):
                yield WorkItemsContainer(id='search-results-container')
                with Vertical(id='details-container'):
                    with Vertical(id='details-breadcrumb-row') as breadcrumb_row:
                        breadcrumb_row.display = False
                        yield WorkItemBreadcrumb()
                        header_summary = WorkItemSummary(widget_id='details-work-item-summary')
                        header_summary.display = False
                        yield header_summary
                    with Horizontal(id='details-tabs-row') as tabs_row:
                        tabs_row.display = False
                        with ExtendedTabbedContent(
                            id='tabs-information',
                            external_content=True,
                        ):
                            with TabPane('Description', id='tab-description'):
                                pass
                            with TabPane('Attachments', id='tab-attachments'):
                                pass
                            with TabPane('Subtasks', id='tab-subtasks'):
                                pass
                            with TabPane('Related Items', id='tab-related'):
                                pass
                            with TabPane('Web Links', id='tab-links'):
                                pass
                            with TabPane('Comments', id='tab-comments'):
                                pass
                            with TabPane('History', id='tab-history'):
                                pass

                    with Horizontal(id='details-content-row'):
                        yield WorkItemInformation()
                        yield WorkItemFields()
                    with Horizontal(id='details-footer-row') as footer_row:
                        footer_row.display = False
                        footer_label = Static(
                            '⚠ Pending changes', id='details-pending-changes-label'
                        )
                        footer_label.display = False
                        yield footer_label
        yield ExtendedFooter(show_command_palette=False)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == 'clear_search':
            return self.search_results_container.search_active
        if action == 'unload_work_item':
            return self.current_loaded_work_item_key is not None
        if action == 'edit_work_item_info':
            return self.current_loaded_work_item_key is not None
        if action == 'reload_loaded_work_item':
            return self.current_loaded_work_item_key is not None
        if action == 'new_comment':
            return (
                self.current_loaded_work_item_key is not None
                and self.work_item_comments_widget.can_add_comment
            )
        if action in ('view_worklog', 'log_work'):
            return self.current_loaded_work_item_key is not None
        if action in ('apply_changes', 'discard_changes'):
            return (
                self.current_loaded_work_item_key is not None
                and self.work_item_fields_widget.has_pending_changes
            )
        if action == 'go_to_parent_work_item':
            work_item = self.information_panel.work_item
            return bool(work_item and work_item.parent_key.strip())
        return super().check_action(action, parameters)

    async def on_mount(self) -> None:
        if self.atlassian_context.user_info:
            self._notify_profile_is_ready(self.atlassian_context.user_info.account_id)

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.unified_search_bar, 'focus')
            set_jump_mode(self.search_results_container, 'focus')

        tabs = self.tabs
        tabs.can_focus = True
        tabs.tabs_widget.can_focus = True
        for tab in tabs.query(ContentTab):
            tab.can_focus = False
            if CONFIGURATION.get().jumper.enabled:
                setattr(tab, 'jump_mode', 'click')  # noqa: B010

        work_item_container = self.query_one(
            '#work-item-fields-container', expect_type=WorkItemFields
        )
        work_item_container.can_focus = False

        work_item_middle_container = self.query_one(
            '#work-item-information-container', expect_type=WorkItemInformation
        )
        work_item_middle_container.can_focus = False

        self.tabs.disabled = True
        self.fields_panel.disabled = True
        self.fields_panel.display = False

        workers: list[Worker] = []

        if self.initial_work_item_key:
            self.run_worker(
                load_work_item_reference(
                    cast(WorkItemReferenceLoader, self),
                    self.initial_work_item_key,
                    title='Quick Navigation',
                ),
                exclusive=True,
                group='work-item',
            )

        if self.initial_jql_filter_label:
            await self.unified_search_bar.set_initial_jql_filter(self.initial_jql_filter_label)

        if CONFIGURATION.get().search_on_startup:
            if not self.initial_jql_filter_label:
                await self.app.workers.wait_for_complete(workers)
            await self.action_search()

            if self.focus_item_on_startup:
                self.call_after_refresh(
                    self.run_worker,
                    self._focus_item_after_startup(self.focus_item_on_startup),
                )

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
        self.watch(self.work_item_history_widget, 'displayed_count', self._update_history_tab_title)

    def set_authenticated_user(self, user_info: JiraMyselfInfo) -> None:
        self.atlassian_context.user_info = user_info
        self._notify_profile_is_ready(user_info.account_id)

    def _notify_profile_is_ready(self, account_id: str) -> None:
        self.unified_search_bar.post_message(self.unified_search_bar.ProfileIsReady(account_id))

    def _update_attachments_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-attachments', count)

    def _update_subtasks_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-subtasks', count)

    def _update_related_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-related', count)

    def _update_links_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-links', count)

    def _update_comments_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-comments', count)

    def _update_history_tab_title(self, count: int) -> None:
        self._update_information_tab_badge('tab-history', count)

    def _update_information_tab_badge(self, tab_id: str, count: int) -> None:
        self.tabs.set_tab_badge(tab_id, count)

    def navigate_to_attachment(self, filename: str) -> None:
        self.tabs.active = 'tab-attachments'
        if not filename:
            return
        found = self.work_item_attachments_widget.focus_attachment_by_filename(filename)
        if not found and self.current_loaded_work_item_key:
            self.notify(
                f'Attachment "{filename}" was not found in the attachments tab.',
                severity='warning',
                title=self.current_loaded_work_item_key,
            )

    def open_attachment_in_browser_by_filename(self, filename: str) -> None:
        attachments = self.work_item_attachments_widget.attachments or []
        attachment = next((item for item in attachments if item.filename == filename), None)
        current_loaded_work_item_key = self.current_loaded_work_item_key or ''
        if attachment is None:
            self.notify(
                f'Attachment "{filename}" was not found.',
                severity='warning',
                title=current_loaded_work_item_key,
            )
            return

        if current_loaded_work_item_key:
            self.notify(
                'Opening attachment in the browser...',
                title=current_loaded_work_item_key,
            )

        app = cast('JiraApp', self.app)
        if url := build_external_url_for_attachment(attachment.id, attachment.filename, app):
            app.open_url(url)

    def _get_hovered_attachment_filename(self) -> str | None:
        for paragraph in self.query(ExtendedMarkdownParagraph):
            filename = getattr(paragraph, '_focused_attachment_filename', None)
            if filename:
                return filename
        return None

    async def action_open_contextual_browser_target(self) -> None:
        attachment_filename = self._get_hovered_attachment_filename()
        if attachment_filename:
            self.open_attachment_in_browser_by_filename(attachment_filename)
            return

        action_names = (
            'action_open_attachment',
            'action_open_link',
            'action_open_comment_in_browser',
            'action_open_worklog_in_browser',
            'action_open_work_item_browser',
            'action_open_work_item_in_browser',
            'action_open_loaded_work_item_in_browser',
        )

        focused = self.focused
        if focused is not None:
            for node in focused.ancestors_with_self:
                for action_name in action_names:
                    action = getattr(node, action_name, None)
                    if not callable(action):
                        continue
                    result = action()
                    if isawaitable(result):
                        await result
                    return

        self.action_open_loaded_work_item_in_browser()

    async def on_work_item_updated(self, message: WorkItemUpdated) -> None:
        await self.search_results_list.update_work_item_in_list(message.work_item)

    async def _search_work_items(
        self,
        next_page_token: str | None = None,
        calculate_total: bool = True,
        search_term: str | None = None,
        page: int | None = None,
        search_data: dict | None = None,
    ) -> WorkItemSearchResult:
        del page
        effective_search_data = search_data or self.unified_search_bar.get_search_data()
        mode = effective_search_data.get('mode', 'basic')

        search_field_status: int | None = None
        search_field_created_from: date | None = None
        search_field_created_until: date | None = None
        search_field_assignee: str | None = None
        search_field_work_item_type: int | None = None
        project_key: str | None = None
        jql_expression: str | None = None
        order_by: str | None = None

        if mode == 'basic':
            project_key = effective_search_data.get('project')
            search_field_assignee = effective_search_data.get('assignee')

            work_item_type_str = effective_search_data.get('type')
            search_field_work_item_type = (
                int(work_item_type_str)
                if work_item_type_str and work_item_type_str != Select.NULL
                else None
            )
            status_str = effective_search_data.get('status')
            search_field_status = (
                int(status_str) if status_str and status_str != Select.NULL else None
            )

            if project_key == Select.NULL:
                project_key = None
            if search_field_assignee == Select.NULL:
                search_field_assignee = None
        elif mode in ('text', 'jql'):
            jql_expression = effective_search_data.get('jql')

        if mode in ('basic', 'text'):
            order_by = self.search_results_container.controls.current_order_by

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
            jql_query = f'created >= -30d order by {order_by or "created DESC"}'
        elif order_by:
            jql_query = self._append_order_by(jql_query, order_by)

        search_api_kwargs: dict[str, Any] = {
            'project_key': project_key,
            'created_from': search_field_created_from,
            'created_until': search_field_created_until,
            'status': search_field_status,
            'assignee': search_field_assignee,
            'work_item_type': search_field_work_item_type,
            'jql_query': jql_query,
        }
        response: APIControllerResponse
        response = await self.api.search_work_items(
            **search_api_kwargs,
            search_in_active_sprint=False,
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
                severity='error',
            )
            return WorkItemSearchResult(total=0, start=0, end=0, response=None)

        result: JiraWorkItemSearchResponse = response.result
        estimated_total_work_items: int = 0
        if calculate_total:
            counting: APIControllerResponse = await self.api.count_work_items(**search_api_kwargs)
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

    @staticmethod
    def _append_order_by(jql_query: str | None, order_by: str) -> str:
        stripped_order_by = order_by.strip()
        if not stripped_order_by:
            return jql_query or ''
        if not jql_query:
            return f'ORDER BY {stripped_order_by}'
        if ' order by ' in f' {jql_query.lower()} ':
            return jql_query
        return f'{jql_query} ORDER BY {stripped_order_by}'

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
        search_data: dict | None = None,
        use_active_search: bool = False,
    ) -> None:
        results: WorkItemSearchResult
        list_view = self.search_results_list

        try:
            effective_search_data = search_data
            if use_active_search:
                effective_search_data = self._active_search_data
                if search_term is None:
                    search_term = self._active_search_term

            if effective_search_data is None:
                effective_search_data = self.unified_search_bar.get_search_data()

            mode = effective_search_data.get('mode')
            work_item_key = (
                effective_search_data.get('work_item_key', '').strip() if mode == 'basic' else ''
            )

            jql = self._freeform_search_query(effective_search_data)
            if jql is not None and not jql:
                self._notify_missing_search_query()
                if use_active_search:
                    self._restore_active_search_pagination(list_view)
                return

            if mode == 'jql' and jql is not None:
                validation_result = await self.api.validate_jql_query(jql)
                if not validation_result.success:
                    list_view.work_item_search_results = None
                    self.notify(
                        validation_result.error or 'JQL validation failed',
                        severity='warning',
                    )
                    if use_active_search:
                        self._restore_active_search_pagination(list_view)
                    return

            if work_item_key and self.current_loaded_work_item_key == work_item_key:
                if self.focused is not list_view and list_view.work_item_search_results is not None:
                    list_view.focus()
                return

            self.begin_search_request(page_number=page, show_pagination=use_active_search)

            if work_item_key:
                results = await self._search_single_work_item(work_item_key)
            else:
                results = await self._search_work_items(
                    next_page_token=next_page_token,
                    search_term=search_term,
                    page=page,
                    search_data=effective_search_data,
                )

            if results.response is None and use_active_search:
                self._restore_active_search_pagination(list_view)

            if not use_active_search and results.response is not None:
                self.unified_search_bar.record_current_search_history()

            if use_active_search and page is not None and results.response is not None:
                list_view.page = page
                list_view.pending_page = None

            if not use_active_search and results.response is not None:
                list_view.clear_loaded_work_item()

            list_view.work_item_search_results = results.response
            if self.focused is not list_view:
                list_view.focus()

            self._active_search_data = effective_search_data
            self._active_search_term = search_term

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
        finally:
            self.end_search_request()

    @on(Button.Pressed, '#unified-search-button')
    async def handle_unified_search_button(self) -> None:
        if self.is_search_request_in_progress:
            return

        await self.action_search()

    def action_clear_search(self) -> None:
        if self.is_search_request_in_progress:
            return

        self._active_search_data = None
        self._active_search_term = None
        self.search_results_container.clear_search()

        if self.focused is self.search_results_list:
            self.query_one('#unified-search-bar', UnifiedSearchBar).focus()

    def action_unload_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        self._clear_loaded_work_item_state()
        if self.search_results_container.search_active:
            self.search_results_list.focus()
        else:
            self.query_one('#unified-search-bar', UnifiedSearchBar).focus()

    def action_focus_search_results_page_input(self) -> None:
        container = self.search_results_container
        if (
            not container.search_active
            or not container.results_loaded
            or container.is_loading
            or not container.page_input.display
            or container.page_input.disabled
        ):
            return
        container.page_input.focus()

    def _is_any_select_expanded(self) -> bool:
        for widget in self.query(Widget):
            if isinstance(widget, Select) and widget.expanded:
                return True
            if getattr(widget, 'blocks_global_actions_when_expanded', False) and getattr(
                widget, 'expanded', False
            ):
                return True
        return False

    @staticmethod
    def _normalize_search_value(value: Any) -> Any:
        if value == Select.NULL:
            return None
        if isinstance(value, str):
            return value.strip()
        return value

    @staticmethod
    def _freeform_search_query(search_data: dict[str, Any]) -> str | None:
        mode = search_data.get('mode')
        if mode not in ('text', 'jql'):
            return None
        return str(search_data.get('jql') or '').strip()

    def _notify_missing_search_query(self) -> None:
        self.notify(
            'Please enter a search term or JQL query',
            severity='warning',
        )

    def _normalize_search_data(self, search_data: dict[str, Any] | None) -> dict[str, Any]:
        if not search_data:
            return {}
        return {key: self._normalize_search_value(value) for key, value in search_data.items()}

    def _is_same_active_search(self, search_term: str | None = None) -> bool:
        if (
            self._active_search_data is None
            or self.search_results_list.work_item_search_results is None
        ):
            return False
        current_search_data = self._normalize_search_data(self.unified_search_bar.get_search_data())
        active_search_data = self._normalize_search_data(self._active_search_data)
        current_search_term = self._normalize_search_value(search_term)
        active_search_term = self._normalize_search_value(self._active_search_term)
        return (
            current_search_data == active_search_data and current_search_term == active_search_term
        )

    def _rerun_active_search(self) -> None:
        requested_page = 1
        self.search_results_list.page = requested_page
        self.search_results_list.pending_page = None
        self.search_results_list.reset_viewport()
        next_page_token = self.search_results_list.token_by_page.get(requested_page)
        self._start_search_page(
            page_number=requested_page,
            next_page_token=next_page_token,
            use_active_search=True,
        )

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return

        if self._is_any_select_expanded():
            return

        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def action_search(self, search_term: str | None = None) -> None:
        if self._is_any_select_expanded() or self.is_search_request_in_progress:
            return

        current_search_data = self.unified_search_bar.get_search_data()
        if (
            current_jql := self._freeform_search_query(current_search_data)
        ) is not None and not current_jql:
            self._notify_missing_search_query()
            return

        if self._is_same_active_search(search_term):
            self._rerun_active_search()
            return

        self.search_results_list.page = 1

        self.search_results_list.token_by_page = {}

        if self.search_results_list.work_item_search_results is not None:
            self.search_results_container.clear_search_metadata()
        self.begin_search_request(
            page_number=self.search_results_list.page,
            show_pagination=False,
        )

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
            group='search',
        )

    def _start_search_page(
        self,
        *,
        page_number: int,
        next_page_token: str | None,
        search_term: str | None = None,
        use_active_search: bool = False,
        show_pagination: bool = True,
    ) -> Worker:
        self.begin_search_request(
            page_number=page_number,
            show_pagination=show_pagination,
        )
        return self.run_worker(
            self.search_work_items(
                next_page_token=next_page_token,
                search_term=search_term,
                page=page_number,
                use_active_search=use_active_search,
            ),
            exclusive=True,
            group='search',
        )

    @property
    def is_search_request_in_progress(self) -> bool:
        return self.search_results_container.is_loading

    def begin_search_request(
        self,
        page_number: int | None = None,
        show_pagination: bool = True,
    ) -> None:
        if show_pagination:
            current_search_data = (
                self._active_search_data or self.unified_search_bar.get_search_data()
            )
        else:
            current_search_data = self.unified_search_bar.get_search_data()
        self.search_results_container.set_search_mode(
            current_search_data.get('mode', 'basic'),
            current_search_data,
        )
        if not show_pagination and self.search_results_container.results_loaded:
            self.search_results_container.results_loaded = False
        self.search_results_list.prepare_for_search()
        self.search_results_container.show_loading()
        if not self.unified_search_bar.search_in_progress:
            self.unified_search_bar.search_in_progress = True

        if not show_pagination:
            self.search_results_container.clear_search_metadata()
            return

        if page_number is None:
            return

        pagination = self.search_results_container.pagination or {}
        self.search_results_container.pagination = {
            'total': pagination.get('total', 0),
            'current_page_number': page_number,
        }

    def _restore_active_search_pagination(self, list_view: WorkItemSearchResultsScroll) -> None:
        list_view.pending_page = None
        self.search_results_container.pagination = {
            'total': (self.search_results_container.pagination or {}).get('total', 0),
            'current_page_number': list_view.page,
        }

    def end_search_request(self) -> None:
        list_view = self.search_results_list
        if list_view.is_pending_initial_render:
            list_view.call_after_refresh(list_view._complete_initial_render)
            self.set_timer(0.25, self._complete_pending_search_render)
            if self.unified_search_bar.search_in_progress:
                self.unified_search_bar.search_in_progress = False
            return
        self.search_results_container.hide_loading()
        if self.unified_search_bar.search_in_progress:
            self.unified_search_bar.search_in_progress = False

    def _complete_pending_search_render(self) -> None:
        list_view = self.search_results_list
        if not list_view.is_pending_initial_render:
            return

        list_view._complete_initial_render()

    def _clear_loaded_work_item_state(
        self,
        *,
        preserve_content: bool = False,
        next_loaded_work_item_key: str | None = None,
    ) -> None:
        """Reset the currently loaded work item using the shared load-state path."""

        self._active_work_item_load_key = None
        self._cancel_progressive_work_item_detail_loads()
        self.focused_work_item_link_key = None

        if next_loaded_work_item_key is None:
            self.search_results_list.clear_loaded_work_item()

        if not preserve_content:
            with self.app.batch_update():
                self.information_panel.work_item = None
                self.work_item_info_container.work_item = None
                self.work_item_fields_widget.work_item = None

                self.related_work_items_widget.work_items = None
                self.related_work_items_widget.work_item_key = None

                self.work_item_comments_widget.comments = None
                self.work_item_comments_widget.work_item_key = None
                self.work_item_comments_widget.work_item_is_service_desk = False

                self.work_item_attachments_widget.attachments = None
                self.work_item_attachments_widget.work_item_key = None

                self.work_item_history_widget.work_item_key = None

                self.work_item_child_work_items_widget.work_items = None
                self.work_item_child_work_items_widget.work_item_key = None

                if CONFIGURATION.get().show_work_item_web_links:
                    self.work_item_remote_links_widget.work_item_key = None

        if preserve_content:
            return

        self.current_loaded_work_item_key = None

        if not self.tabs.disabled:
            self.tabs.disabled = True
        if not self.fields_panel.disabled:
            self.fields_panel.disabled = True
        if not preserve_content:
            if self.fields_panel.display:
                self.fields_panel.display = False
            if self.details_breadcrumb_row.display:
                self.details_breadcrumb_row.display = False
            if self.details_tabs_row.display:
                self.details_tabs_row.display = False

        self.call_after_refresh(self.refresh_bindings)

    async def action_create_work_item(self) -> None:
        from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen

        await self.app.push_screen(
            AddWorkItemScreen(
                project_key=None,
                reporter_account_id=self.atlassian_context.user_info.account_id
                if self.atlassian_context.user_info
                else None,
            ),
            callback=self.create_work_item,
        )

    async def action_create_work_item_from_template(self) -> None:
        from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen
        from gojeera.components.screens.work_item_template_screen import (
            WorkItemTemplatePickerScreen,
        )
        from gojeera.utils.work_item_templates import has_valid_work_item_templates

        if not has_valid_work_item_templates():
            self.notify(
                'No templates found in the gojeera templates directory.',
                title='Work Item Templates',
                severity='warning',
            )
            return

        async def open_create_work_item_from_template(
            selected_template: tuple[str, dict[str, object]] | None,
        ) -> None:
            if selected_template is None:
                return
            _template_name, template = selected_template
            user_info = self.atlassian_context.user_info
            await self.app.push_screen(
                AddWorkItemScreen(
                    reporter_account_id=user_info.account_id if user_info else None,
                    initial_template=template,
                ),
                callback=self.create_work_item,
            )

        await self.app.push_screen(
            WorkItemTemplatePickerScreen(on_use_template=open_create_work_item_from_template),
        )

    async def action_edit_work_item_info(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        await self.work_item_info_container.action_edit_work_item_info()

    def action_reload_loaded_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        self.run_worker(
            self.load_work_item(self.current_loaded_work_item_key, force_reload=True),
            exclusive=True,
            group='work-item',
        )

    def action_watch_loaded_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        self.run_worker(
            self.work_item_fields_widget.toggle_current_user_watching(),
            exclusive=True,
            group='work-item-watchers',
        )

    async def action_flag_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        await self.work_item_fields_widget.toggle_work_item_flag()

    def action_open_loaded_work_item_in_browser(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        app = cast('JiraApp', self.app)
        if url := build_external_url_for_work_item(self.current_loaded_work_item_key, app):
            app.open_url(url)

    def action_copy_loaded_work_item_key(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        self.app.copy_to_clipboard(self.current_loaded_work_item_key)
        self.notify('Key copied to clipboard', title=self.current_loaded_work_item_key)

    def action_copy_loaded_work_item_url(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        app = cast('JiraApp', self.app)
        if url := build_external_url_for_work_item(self.current_loaded_work_item_key, app):
            app.copy_to_clipboard(url)
            self.notify('URL copied to clipboard', title=self.current_loaded_work_item_key)

    def action_copy_loaded_work_item_as_template(self) -> None:
        work_item = self.information_panel.work_item
        if work_item is None:
            return

        from gojeera.utils.work_item_templates import dump_work_item_template

        self.app.copy_to_clipboard(dump_work_item_template(work_item))
        self.notify('Template copied to clipboard', title=work_item.key)

    def action_clone_loaded_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return

        self.run_worker(self.clone_work_item(self.current_loaded_work_item_key))

    async def action_add_attachment(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        await self.work_item_attachments_widget.action_add_attachment()

    async def action_create_work_item_subtask(self) -> None:
        work_item = self.work_item_info_container.work_item
        if not work_item or (work_item.work_item_type and work_item.work_item_type.subtask):
            return

        from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen

        reporter_account_id = (
            self.atlassian_context.user_info.account_id
            if self.atlassian_context.user_info
            else None
        )

        await self.app.push_screen(
            AddWorkItemScreen(
                project_key=work_item.project.key if work_item.project else None,
                reporter_account_id=reporter_account_id,
                parent_work_item=work_item,
            ),
            callback=self.create_work_item,
        )

    async def action_new_related_work_item(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        await self.related_work_items_widget.action_link_work_item()

    async def action_new_web_link(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        await self.work_item_remote_links_widget.action_add_remote_link()

    def action_new_comment(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        if not self.work_item_comments_widget.can_add_comment:
            return
        self.work_item_comments_widget.action_add_comment()

    def action_view_worklog(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        self.information_panel.action_view_worklog()

    def action_log_work(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        self.information_panel.action_log_work()

    def action_apply_changes(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        self.work_item_fields_widget.action_save_work_item()

    def action_discard_changes(self) -> None:
        if not self.current_loaded_work_item_key:
            return
        self.work_item_fields_widget.action_discard_pending_changes()

    async def action_go_to_parent_work_item(self) -> None:
        if self.focused_work_item_link_key:
            self.run_worker(
                self.load_work_item(self.focused_work_item_link_key),
                exclusive=True,
                group='work-item',
            )
            return

        work_item = self.information_panel.work_item
        if not work_item or not work_item.parent_key.strip():
            return

        self.run_worker(
            self.load_work_item(work_item.parent_key.strip()),
            exclusive=True,
            group='work-item',
        )

    async def action_set_parent_work_item(self) -> None:
        work_item = self.information_panel.work_item
        if not work_item:
            return

        from gojeera.utils.data.fields import supports_parent_work_item

        if not supports_parent_work_item(work_item):
            return

        await self.information_panel.breadcrumb_widget.open_parent_work_item_screen()

    def set_pending_work_item_navigation_target(
        self, target: WorkItemNavigationTarget | None
    ) -> None:
        self._pending_work_item_navigation_target = target

    def _set_active_work_item_tab(self, tab_id: str) -> None:
        self.tabs.active = tab_id

    def _apply_pending_work_item_navigation_target(self) -> None:
        target = self._pending_work_item_navigation_target
        if target is None:
            return

        try:
            if target.focused_comment_id:
                self._set_active_work_item_tab('tab-comments')
                self.work_item_comments_widget.focus_comment_by_id(target.focused_comment_id)
        finally:
            self._pending_work_item_navigation_target = None

    def _is_current_loaded_work_item(self, work_item_key: str) -> bool:
        return self.current_loaded_work_item_key == work_item_key

    def _cancel_progressive_work_item_detail_loads(self) -> None:
        if (
            self._comments_loading_worker is not None
            and not self._comments_loading_worker.is_finished
        ):
            self._comments_loading_worker.cancel()
        self._comments_loading_worker = None

        if (
            self._subtasks_loading_worker is not None
            and not self._subtasks_loading_worker.is_finished
        ):
            self._subtasks_loading_worker.cancel()
        self._subtasks_loading_worker = None

    def _bind_loaded_work_item_details(
        self,
        selected_work_item_key: str,
        work_item: JiraWorkItem,
    ) -> None:
        if not self._is_current_loaded_work_item(selected_work_item_key):
            return

        with self.app.batch_update():
            self.information_panel.work_item = work_item
            self.information_panel.set_active_tab(self.tabs.active)

            self.work_item_info_container.work_item = work_item

            self.related_work_items_widget.work_item_key = work_item.key
            self.related_work_items_widget.work_items = work_item.related_work_items

            self.work_item_comments_widget.work_item_key = work_item.key
            self.work_item_comments_widget.work_item_is_service_desk = (
                work_item.project.is_service_desk if work_item.project else False
            )
            self.work_item_comments_widget.comments = work_item.comments

            self.work_item_attachments_widget.work_item_key = work_item.key
            self.work_item_attachments_widget.attachments = work_item.attachments

            self.work_item_history_widget.work_item_key = work_item.key

            self.work_item_child_work_items_widget.work_item_key = work_item.key
            self.work_item_child_work_items_widget.work_items = work_item.subtasks

            if CONFIGURATION.get().show_work_item_web_links:
                self.work_item_remote_links_widget.work_item_key = work_item.key

            self.work_item_fields_widget.available_users = self.available_users
            self.work_item_fields_widget.work_item = work_item

        if self.tabs.active == 'tab-history':
            self.work_item_history_widget.load_if_needed()

        self._apply_pending_work_item_navigation_target()
        self._start_progressive_work_item_detail_loads(work_item)

    def _start_progressive_work_item_detail_loads(
        self,
        work_item: JiraWorkItem,
    ) -> None:
        self._cancel_progressive_work_item_detail_loads()

        self.work_item_comments_widget.work_item_key = work_item.key
        self.work_item_comments_widget.work_item_is_service_desk = (
            work_item.project.is_service_desk if work_item.project else False
        )
        self.work_item_child_work_items_widget.work_item_key = work_item.key

        if not work_item.comments:
            self.work_item_comments_widget.show_loading()
        if not work_item.subtasks:
            self.work_item_child_work_items_widget.show_loading()

        self._comments_loading_worker = self.run_worker(
            self._load_work_item_comments(work_item.key),
            exclusive=False,
            group='work-item-comments',
        )
        self._subtasks_loading_worker = self.run_worker(
            self._load_work_item_subtasks(work_item.key),
            exclusive=False,
            group='work-item-subtasks',
        )

    async def _load_work_item_comments(self, work_item_key: str) -> None:
        try:
            response: APIControllerResponse = await self.api.get_comments(work_item_key)
        except asyncio.CancelledError:
            raise

        if not self._is_current_loaded_work_item(work_item_key):
            return

        if response.success and isinstance(response.result, list):
            self.work_item_comments_widget.comments = response.result
            return

        self.logger.error(
            'Unable to retrieve the comments of the work item',
            extra={'error': response.error, 'work_item_key': work_item_key},
        )
        self.work_item_comments_widget.hide_loading()

    async def _load_work_item_subtasks(self, work_item_key: str) -> None:
        try:
            response: APIControllerResponse = await self.api.search_work_items(
                jql_query=f'parent={work_item_key}',
                fields=['id', 'key', 'status', 'summary', 'issuetype', 'assignee'],
            )
        except asyncio.CancelledError:
            raise

        if not self._is_current_loaded_work_item(work_item_key):
            return

        if response.success and response.result:
            self.work_item_child_work_items_widget.work_items = response.result.work_items
            return

        self.logger.error(
            'Unable to retrieve the sub tasks of the work item',
            extra={'error': response.error, 'work_item_key': work_item_key},
        )
        self.work_item_child_work_items_widget.hide_loading()

    async def create_work_item(self, data: dict | None) -> None:
        if data and data.get('parent_key'):
            await self.retrieve_work_item_subtasks(str(data['parent_key']))

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
                    severity='error',
                )
                self.work_item_child_work_items_widget.work_items = None
            else:
                if response.result:
                    self.work_item_child_work_items_widget.work_items = response.result.work_items
                else:
                    self.work_item_child_work_items_widget.work_items = None

        self.work_item_child_work_items_widget.hide_loading()

    def _bind_provisional_work_item_shell(self, work_item: JiraWorkItem) -> None:
        self.current_loaded_work_item_key = work_item.key

    def _record_recently_viewed_work_item(self, work_item: JiraWorkItem) -> None:
        self.run_worker(
            run_cache_io(
                lambda: get_cache().add_recently_viewed_work_item(
                    work_item.key,
                    work_item.summary,
                    work_item.work_item_type.name if work_item.work_item_type else None,
                )
            ),
            exclusive=False,
            group='recently-viewed-work-items',
        )

    async def load_work_item(
        self, selected_work_item_key: str, *, force_reload: bool = False
    ) -> bool:
        if not selected_work_item_key:
            self.notify(
                'You need to select a work item before fetching its details.',
                title='Find Work Item',
                severity='error',
            )
            return False

        if self._active_work_item_load_key == selected_work_item_key:
            return False

        if self._is_current_loaded_work_item(selected_work_item_key) and not force_reload:
            if self.information_panel.work_item:
                self._record_recently_viewed_work_item(self.information_panel.work_item)
            self._apply_pending_work_item_navigation_target()
            return True

        self._active_work_item_load_key = selected_work_item_key
        self.is_loading = True

        try:
            main_response: APIControllerResponse = await self.api.get_work_item(
                work_item_id_or_key=selected_work_item_key,
            )

            if not main_response.success or not main_response.result:
                self.notify(
                    'Work item not found',
                    severity='warning',
                )
                return False

            result: JiraWorkItemSearchResponse = main_response.result
            work_item: JiraWorkItem = result.work_items[0]

            self._clear_loaded_work_item_state(
                preserve_content=True,
                next_loaded_work_item_key=selected_work_item_key,
            )
            self.search_results_list.mark_loaded_work_item(selected_work_item_key)

            if provisional_work_item := self.search_results_list.get_work_item_by_key(
                selected_work_item_key
            ):
                self._bind_provisional_work_item_shell(provisional_work_item)

            self.tabs.disabled = False
            self.fields_panel.disabled = False
            self.fields_panel.display = True

            if work_item.work_item_type and work_item.work_item_type.subtask:
                self.tabs.hide_tab('tab-subtasks')
            else:
                self.tabs.show_tab('tab-subtasks')

            self.current_loaded_work_item_key = selected_work_item_key
            self._record_recently_viewed_work_item(work_item)
            self.call_after_refresh(self.refresh_bindings)

            self.call_after_refresh(
                self._bind_loaded_work_item_details,
                selected_work_item_key,
                work_item,
            )

            self._active_work_item_load_key = None
            return True
        except asyncio.CancelledError:
            if self._active_work_item_load_key == selected_work_item_key:
                self.is_loading = False
                self._active_work_item_load_key = None
            raise
        finally:
            if self._active_work_item_load_key == selected_work_item_key and self.is_loading:
                self.is_loading = False
                self._active_work_item_load_key = None

    def _try_hide_loading_coordinated(self) -> None:
        info_container = self.work_item_info_container

        if info_container._content_ready and info_container._fields_widget_ready:
            info_container.hide_loading()

            info_container._content_ready = False
            info_container._fields_widget_ready = False

            self.work_item_fields_widget.start_deferred_fields_after_handoff()

            self.is_loading = False

            try:
                work_item_info = self.information_panel
                if work_item_info.work_item is not None:
                    work_item_info.breadcrumb_widget.display = True
                    self.details_breadcrumb_row.display = True
                    self.details_tabs_row.display = True
                    tabs_widget = self.tabs
                    tabs_widget.disabled = False

                    self.information_panel.refresh(layout=True)
                    self.fields_panel.refresh(layout=True)
            except Exception as e:
                self.logger.error(f'Failed to signal WorkItemInformation: {e}')
                self.is_loading = False

    def watch_is_loading(self, loading: bool) -> None:
        self.details_container.loading = loading
        if loading:
            self.details_breadcrumb_row.display = False
            self.details_tabs_row.display = False

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

        from gojeera.components.screens.clone_work_item_screen import CloneWorkItemScreen

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

            self.run_worker(
                self.load_work_item(cloned_key),
                exclusive=True,
                group='work-item',
            )
        else:
            error_msg = clone_response.error if clone_response.error else 'Unknown error'
            self.notify(
                f'Failed to clone work item: {error_msg}',
                severity='error',
                title=work_item_key,
            )

    def action_next_detail_tab(self) -> None:
        if not self.tabs.disabled and self.tabs.tab_count > 0:
            tab_ids = self.tabs.visible_tab_ids()
            current_active = self.tabs.active

            for active_id, next_id in zip(tab_ids, tab_ids[1:], strict=False):
                if active_id == current_active:
                    self.tabs.active = next_id
                    break

    def action_previous_detail_tab(self) -> None:
        if not self.tabs.disabled and self.tabs.tab_count > 0:
            tab_ids = self.tabs.visible_tab_ids()
            current_active = self.tabs.active

            for prev_id, active_id in zip(tab_ids, tab_ids[1:], strict=False):
                if active_id == current_active:
                    self.tabs.active = prev_id
                    break

    async def _focus_item_after_startup(self, position: int) -> None:
        scroll_view = self.search_results_list

        max_attempts = 50
        attempt = 0

        while attempt < max_attempts:
            await self.app.animator.wait_for_idle()
            await asyncio.sleep(0.1)
            item_count = len(scroll_view.work_item_containers)
            if item_count > 0:
                break
            attempt += 1

        item_index = position - 1
        containers = scroll_view.work_item_containers
        if item_index >= len(containers):
            return

        work_item_container = containers[item_index]
        scroll_view._selected_index = item_index
        scroll_view._update_selection()
        scroll_view._scroll_to_index(item_index)

        await asyncio.sleep(0.1)
        await self.app.animator.wait_for_idle()

        scroll_view._select_work_item(work_item_container.work_item_key)

        await asyncio.sleep(0.3)
        await self.app.animator.wait_for_idle()

        self.work_item_info_container.focus()


class JiraApp(WorkspaceMixin, App):
    CSS_PATH = CSS_PATH

    TITLE = TITLE
    BINDINGS = WorkspaceMixin.BINDINGS + [
        Binding(
            key='ctrl+c',
            action='quit',
            description='Quit',
            tooltip='Quit',
            show=True,
        ),
        Binding(key='ctrl+q', action='', description=''),
        register_binding_in_command_palette(
            Binding(
                key='f1',
                action='help',
                description='Help',
                tooltip='Open help',
            )
        ),
        build_toggle_footer_binding(),
        register_binding_in_command_palette(
            Binding(
                key='f12',
                action='debug_info',
                description='Debug',
                tooltip='Show debug information (config, server, user)',
                show=False,
            )
        ),
    ]
    DEFAULT_THEME = DEFAULT_THEME

    COMMANDS = App.COMMANDS | {
        get_work_item_command_provider,
        get_create_command_provider,
        get_search_command_provider,
        get_quick_navigation_provider,
        get_recently_viewed_work_items_provider,
        get_panel_command_provider,
        get_decision_command_provider,
        get_registered_binding_command_provider,
        get_user_mention_command_provider,
    }

    def __init__(
        self,
        settings: ApplicationConfiguration,
        user_info: JiraMyselfInfo | None = None,
        directory_themes: list[Theme] | None = None,
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
        self.atlassian_context = AtlassianContext(user_info=user_info)

        self.initial_work_item_key: str | None = None
        if work_item_key and (cleaned_work_item_key := work_item_key.strip()):
            self.initial_work_item_key = cleaned_work_item_key

        self.initial_assignee: str | None = None

        if assignee and (cleaned_assignee := assignee.strip()):
            self.initial_assignee = cleaned_assignee

        self.initial_jql_filter_label: str | None = jql_filter

        self.focus_item_on_startup: int | None = focus_item_on_startup
        self._directory_themes = directory_themes
        self._init_workspace(
            api=self.api,
            project_key=project_key,
            assignee=self.initial_assignee,
            jql_filter_label=self.initial_jql_filter_label,
            work_item_key=self.initial_work_item_key,
            focus_item_on_startup=self.focus_item_on_startup,
            user_info=self.atlassian_context.user_info,
        )
        self._setup_logging()
        self._register_custom_themes()
        self._setup_theme(user_theme)

    async def upload_staged_attachments(
        self,
        work_item_key: str,
        file_paths: list[str],
    ) -> tuple[list[Attachment], list[str], list[str]]:
        uploaded_attachments: list[Attachment] = []
        errors: list[str] = []
        failed_file_paths: list[str] = []

        for file_path in file_paths:
            response = await asyncio.to_thread(self.api.add_attachment, work_item_key, file_path)
            if response.success and isinstance(response.result, Attachment):
                uploaded_attachments.append(response.result)
                try:
                    Path(file_path).unlink(missing_ok=True)
                    parent_dir = Path(file_path).parent
                    if parent_dir.name.startswith('gojeera-clipboard-'):
                        parent_dir.rmdir()
                except OSError:
                    pass
            else:
                errors.append(response.error or Path(file_path).name)
                failed_file_paths.append(file_path)

        return uploaded_attachments, errors, failed_file_paths

    def search_themes(self) -> None:
        """Show the theme picker with the extended command palette."""
        from textual.theme import ThemeProvider

        self._push_screen_exclusive_sync(
            ExtendedPalette(
                providers=[ThemeProvider],
                placeholder='Search for themes…',
            ),
        )

    def _register_custom_themes(self) -> None:
        directory_themes = self._directory_themes
        if directory_themes is None:
            themes_dir = get_themes_directory()
            directory_themes = load_themes_from_directory(themes_dir)
        for theme in directory_themes:
            self.register_theme(theme)
            self.logger.info(
                'Registered custom theme from directory',
                extra=build_log_extra({'theme_name': theme.name}),
            )

    def _setup_theme(self, user_theme: str | None = None) -> None:
        if input_theme := (user_theme or CONFIGURATION.get().theme):
            try:
                self.theme = input_theme
            except InvalidThemeError:
                self.logger.warning(
                    'Unknown theme, using default theme',
                    extra=build_log_extra(
                        {'requested_theme': input_theme, 'default_theme': self.DEFAULT_THEME}
                    ),
                )
                self.theme = self.DEFAULT_THEME
        else:
            self.theme = self.DEFAULT_THEME

    async def on_mount(self) -> None:
        await WorkspaceMixin.on_mount(self)
        self.run_worker(self._initialize_startup_context(), name='startup_context')

    async def _initialize_startup_context(self) -> None:
        server_info_coroutine = self.api.server_info()
        global_settings_coroutine = self.api.global_settings()
        user_info_coroutine = (
            self.api.myself() if self.atlassian_context.user_info is None else None
        )

        if user_info_coroutine is not None:
            server_info_result, global_settings_result, user_info_result = await asyncio.gather(
                server_info_coroutine,
                global_settings_coroutine,
                user_info_coroutine,
                return_exceptions=True,
            )
        else:
            server_info_result, global_settings_result = await asyncio.gather(
                server_info_coroutine, global_settings_coroutine, return_exceptions=True
            )
            user_info_result = None

        if isinstance(server_info_result, BaseException):
            self.logger.warning(
                'Failed to fetch server info',
                extra=build_log_extra({'error': str(server_info_result)}),
            )
        elif server_info_result.success and server_info_result.result:
            server_info = server_info_result.result
            self.atlassian_context.server_info = server_info
        else:
            self.logger.warning(
                'Failed to fetch server info',
                extra=build_log_extra({'error': server_info_result.error}),
            )

        if isinstance(global_settings_result, BaseException):
            self.logger.warning(
                'Failed to fetch global settings',
                extra=build_log_extra({'error': str(global_settings_result)}),
            )
        elif global_settings_result.success and global_settings_result.result:
            self.atlassian_context.global_settings = global_settings_result.result
        else:
            self.logger.warning(
                'Failed to fetch global settings',
                extra=build_log_extra({'error': global_settings_result.error}),
            )

        if user_info_result is None:
            return

        if isinstance(user_info_result, BaseException):
            self._handle_startup_auth_failure(str(user_info_result))
            return

        if user_info_result.success and user_info_result.result:
            user_info = user_info_result.result
            self.atlassian_context.user_info = user_info
            self.set_authenticated_user(user_info)
            return

        self._handle_startup_auth_failure(user_info_result.error)

    def _handle_startup_auth_failure(self, error_message: str | None) -> None:
        message = error_message or 'Please check your credentials.'
        self.logger.error(
            'Authentication failed during startup',
            extra=build_log_extra({'error': message}),
        )
        self.exit(message=f'Authentication failed: {message}')

    async def action_help(self) -> None:
        from gojeera.components.screens.help_screen import HelpScreen

        if isinstance(self.screen, HelpScreen):
            self._pending_screen_types.discard(HelpScreen)
            self.pop_screen()
            return

        focused = self.focused

        def restore_focus(_response) -> None:
            if focused:
                self.set_focus(focused)

        self.set_focus(None)
        anchor: str | None = None
        if focused and hasattr(focused, 'help_anchor'):
            anchor = str(getattr(focused, 'help_anchor', None))
        await self._push_screen_exclusive(HelpScreen(anchor), restore_focus)

    async def action_debug_info(self) -> None:
        from gojeera.components.screens.debug_screen import DebugInfoScreen

        if isinstance(self.screen, DebugInfoScreen):
            self._pending_screen_types.discard(DebugInfoScreen)
            self.pop_screen()
            return

        await self._push_screen_exclusive(DebugInfoScreen())

    async def action_quit(self) -> None:
        if CONFIGURATION.get().confirm_before_quit:
            from gojeera.components.screens.quit_screen import QuitScreen

            await self._push_screen_exclusive(QuitScreen())
        else:
            await self.api.close()
            self.app.exit()

    def _prepare_exclusive_screen_push(self, screen, callback=None):
        screen_type = type(screen)
        if screen_type in self._pending_screen_types:
            return None

        self._pending_screen_types.add(screen_type)

        def wrapped_callback(result) -> None:
            self._pending_screen_types.discard(screen_type)
            if callback is not None:
                callback(result)

        return wrapped_callback

    async def _push_screen_exclusive(self, screen, callback=None) -> None:
        wrapped_callback = self._prepare_exclusive_screen_push(screen, callback)
        if wrapped_callback is not None:
            await self.push_screen(screen, wrapped_callback)

    def _pop_screen_exclusive(self) -> None:
        self._pending_screen_types.discard(type(self.screen))
        self.pop_screen()

    def _push_screen_exclusive_sync(self, screen, callback=None) -> None:
        wrapped_callback = self._prepare_exclusive_screen_push(screen, callback)
        if wrapped_callback is not None:
            self.push_screen(screen, wrapped_callback)

    def _open_main_command_palette(self) -> None:
        self.active_sub_command_palette_id = None
        if self.use_command_palette and not ExtendedPalette.is_open(self):
            self._push_screen_exclusive_sync(
                ExtendedPalette(
                    id='--command-palette',
                    placeholder='Search actions, navigate to page, or enter a work item key/URL…',
                )
            )

    def action_command_palette(self) -> None:
        if isinstance(self.screen, ExtendedPalette):
            self.active_sub_command_palette_id = None
            self._pop_screen_exclusive()
        else:
            self._open_main_command_palette()

    def action_show_main_command_palette(self) -> None:
        if isinstance(self.screen, ExtendedPalette):
            self.screen.switch_palette_context(
                sub_palette_id=None,
                placeholder='Search actions, navigate to page, or enter a work item key/URL…',
            )
            return
        self.active_sub_command_palette_id = None
        self._open_main_command_palette()

    def _open_sub_command_palette(self, palette_id: str, placeholder: str) -> None:
        if isinstance(self.screen, ExtendedPalette):
            self.screen.switch_palette_context(sub_palette_id=palette_id, placeholder=placeholder)
            return
        self.active_sub_command_palette_id = palette_id
        self._push_screen_exclusive_sync(
            ExtendedPalette(
                id='--command-palette',
                placeholder=placeholder,
            )
        )

    def action_show_recently_viewed_work_items_palette(self) -> None:
        from gojeera.commands.providers.recently_viewed_work_items_provider import (
            RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID,
        )

        self._open_sub_command_palette(
            RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID,
            'Search recently viewed work items…',
        )

    def action_toggle_footer_visibility(self) -> None:
        self.toggle_footer_visibility()

    def _setup_logging(self) -> None:
        self.logger = logging.getLogger('gojeera')
        self.logger.setLevel(CONFIGURATION.get().log_level or logging.WARNING)

        if jira_tui_log_file := os.getenv('GOJEERA_LOG_FILE'):
            log_file = Path(jira_tui_log_file).resolve()
        elif config_log_file := CONFIGURATION.get().log_file:
            log_file = Path(config_log_file).resolve()
        else:
            log_file = get_log_file()

        try:
            fh = logging.FileHandler(log_file, encoding='utf-8', delay=True)
        except Exception as error:
            self.logger.warning(
                'Failed to create log file handler',
                extra=build_log_extra({'error': str(error)}),
                exc_info=True,
            )
        else:
            fh.setLevel(CONFIGURATION.get().log_level or logging.WARNING)
            fh.setFormatter(
                JsonFormatter(
                    '%(asctime)s %(levelname)s %(message)s %(lineno)s %(module)s %(pathname)s '
                )
            )
            self.logger.addHandler(fh)

    def toggle_footer_visibility(self) -> None:
        config = CONFIGURATION.get()
        new_value = not config.show_footer
        config.show_footer = new_value
        self._apply_footer_visibility(new_value)

    def _apply_footer_visibility(self, visible: bool) -> None:
        for screen in self.screen_stack:
            for footer in screen.query(ExtendedFooter):
                footer.display = visible


if __name__ == '__main__':
    from rich.console import Console

    console = Console()

    try:
        settings = ApplicationConfiguration()

        async def check_auth() -> tuple[bool, str | None, JiraMyselfInfo | None]:
            from gojeera.internal.jira.controller import APIController

            try:
                api = APIController(configuration=settings)
                response = await api.myself()

                try:
                    await api.close()
                except Exception:  # nosec: B110
                    # Ignore client close errors during module cleanup.
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

        event_loop = asyncio.new_event_loop()
        try:
            success, error_message, user_info = event_loop.run_until_complete(check_auth())
        finally:
            event_loop.close()

        if not success:
            console.print(f'[bold red]Authentication failed:[/bold red] {error_message}')
            sys.exit(1)

        JiraApp(settings, user_info=user_info).run()
    except Exception as e:
        console.print(f'[bold red]Error:[/bold red] {str(e)}')
        sys.exit(1)
