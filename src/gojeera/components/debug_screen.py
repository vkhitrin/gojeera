"""Debug information modal screen for displaying config, server info, and user details."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static, TabPane
import yaml

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION
from gojeera.models import JiraGlobalSettings, JiraMyselfInfo, JiraServerInfo
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.extended_tabbed_content import ExtendedTabbedContent
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class DebugInfoScreen(ExtendedModalScreen[None]):
    """Modal screen for displaying debug information about gojeera configuration and Jira server."""

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('f12', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
        Binding(
            key='[',
            action='focus_previous',
            description='Previous tab',
            show=True,
        ),
        Binding(
            key=']',
            action='focus_next',
            description='Next tab',
            show=True,
        ),
    ]
    TITLE = 'Debug Information'

    def __init__(
        self,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
    ):
        super().__init__(name, id)
        self._cache = get_cache()
        self._loading_sections: set[str] = set()

    @property
    def tabs(self) -> ExtendedTabbedContent:
        return self.query_one('#debug_tabs', ExtendedTabbedContent)

    @property
    def modal_outer(self):
        return self.query_one('#modal_outer')

    @property
    def config_content(self) -> Static:
        return self.query_one('#config-content', expect_type=Static)

    @property
    def cache_content(self) -> Static:
        return self.query_one('#cache-content', expect_type=Static)

    @property
    def server_content(self) -> Static:
        return self.query_one('#server-content', expect_type=Static)

    @property
    def user_content(self) -> Static:
        return self.query_one('#user-content', expect_type=Static)

    @property
    def global_content(self) -> Static:
        return self.query_one('#global-content', expect_type=Static)

    @property
    def application_content(self) -> Static:
        return self.query_one('#application-content', expect_type=Static)

    @property
    def application_scroll(self) -> VerticalScroll:
        return self.query_one('#application-scroll', expect_type=VerticalScroll)

    @property
    def config_scroll(self) -> VerticalScroll:
        return self.query_one('#config-scroll', expect_type=VerticalScroll)

    @property
    def server_scroll(self) -> VerticalScroll:
        return self.query_one('#server-scroll', expect_type=VerticalScroll)

    @property
    def user_scroll(self) -> VerticalScroll:
        return self.query_one('#user-scroll', expect_type=VerticalScroll)

    @property
    def cache_scroll(self) -> VerticalScroll:
        return self.query_one('#cache-scroll', expect_type=VerticalScroll)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Debug Information', id='modal_title')
            with ExtendedTabbedContent(initial='tab-application', id='debug_tabs'):
                with TabPane('Application', id='tab-application'):
                    with VerticalScroll(id='application-scroll'):
                        yield Static(id='application-content')
                with TabPane('Configuration', id='tab-config'):
                    with VerticalScroll(id='config-scroll'):
                        yield Static(id='config-content')
                with TabPane('Server Info', id='tab-server'):
                    with VerticalScroll(id='server-scroll'):
                        yield Static(id='server-content')
                        yield Static(id='global-content')
                with TabPane('User Info', id='tab-user'):
                    with VerticalScroll(id='user-scroll'):
                        yield Static(id='user-content')
                with TabPane('Cache', id='tab-cache'):
                    with VerticalScroll(id='cache-scroll'):
                        yield Static(id='cache-content')

        yield ExtendedFooter(show_command_palette=False)

    async def on_mount(self) -> None:
        self.modal_outer.scroll_home()

        if CONFIGURATION.get().jumper.enabled:
            from textual.widgets._tabbed_content import ContentTab

            content_tabs = list(self.tabs.query(ContentTab))
            for content_tab in content_tabs:
                setattr(content_tab, 'jump_mode', 'click')  # noqa: B010

        self._set_section_loading('server_info', True)
        self._set_section_loading('global_settings', True)
        self._set_section_loading('user', True)

        await self._populate_application_section()
        await self._populate_config_section()

        self._fetch_server_info()
        self._fetch_user_info()
        self._fetch_global_settings()

        await self._populate_cache_section()
        self.call_after_refresh(lambda: focus_first_available(self.tabs.tabs_widget))

    async def action_show_overlay(self) -> None:
        """Show the Jumper overlay to jump between widgets."""
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def _populate_config_section(self) -> None:
        data = self._get_effective_configuration_data()

        yaml_output = yaml.dump(
            data,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        self.config_content.update(yaml_output.rstrip())

    def _get_effective_configuration_data(self) -> dict:
        app = cast('JiraApp', self.app)
        config = app.config

        import json as json_lib

        json_str = config.model_dump_json(exclude={'jira'})
        data = json_lib.loads(json_str)

        # Reflect runtime theme overrides such as the CLI `--theme` option.
        if getattr(app, 'theme', None):
            data['theme'] = app.theme

        return data

    async def _populate_application_section(self) -> None:
        app = cast('JiraApp', self.app)
        main_screen = self._get_main_screen()
        jira_config = app.config.jira

        app_state: dict[str, object] = {
            'auth_profile': jira_config.get_active_profile_name(),
            'auth_type': jira_config.auth_type,
            'theme': getattr(app, 'theme', None),
            'focused_widget': self._describe_widget(getattr(app, 'focused', None)),
            'screen_stack': [type(screen).__name__ for screen in app.screen_stack],
            'screen_count': len(app.screen_stack),
        }

        if main_screen is not None:
            current_search_data = main_screen.unified_search_bar.get_search_data()
            active_search_data = main_screen._active_search_data
            active_search_term = main_screen._active_search_term
            executed_query = self._build_executed_query(main_screen, active_search_data)

            app_state.update(
                {
                    'current_loaded_work_item_key': main_screen.current_loaded_work_item_key,
                    'focused_work_item_link_key': main_screen.focused_work_item_link_key,
                    'search_request_in_progress': main_screen.is_search_request_in_progress,
                    'active_information_tab': main_screen.tabs.active,
                    'search_results_page': main_screen.search_results_list.page,
                    'search_results_total_pages': main_screen.search_results_list.total_pages,
                    'search_results_pending_page': main_screen.search_results_list.pending_page,
                    'current_search_data': current_search_data,
                    'active_search_data': active_search_data,
                    'active_search_term': active_search_term,
                    'executed_query': executed_query,
                }
            )

        yaml_output = yaml.dump(
            app_state,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

        self.application_content.update(yaml_output.rstrip())

    @staticmethod
    def _describe_widget(widget: object) -> str | None:
        if widget is None:
            return None

        widget_id = getattr(widget, 'id', None)
        if widget_id:
            return f'{type(widget).__name__}#{widget_id}'
        return type(widget).__name__

    def _get_main_screen(self) -> MainScreen | None:
        for screen in reversed(self.app.screen_stack):
            if screen is self:
                continue
            if type(screen).__name__ == 'MainScreen':
                return cast('MainScreen', screen)
        return None

    def _build_executed_query(
        self, main_screen: MainScreen, search_data: dict | None
    ) -> str | None:
        if not search_data:
            return None

        mode = search_data.get('mode', 'basic')
        work_item_key = str(search_data.get('work_item_key') or '').strip()
        if mode == 'basic' and work_item_key:
            return f'work_item_key={work_item_key}'

        search_term: str | None = None
        jql_expression: str | None = None
        order_by: str | None = None

        if mode in ('text', 'jql'):
            jql_expression = search_data.get('jql')

        if mode in ('basic', 'text'):
            order_by = main_screen.search_results_container.controls.current_order_by

        executed_query = main_screen._build_jql_query(
            search_term=search_term,
            jql_expression=jql_expression,
            use_advance_search=CONFIGURATION.get().enable_advanced_full_text_search,
        )

        if mode == 'basic' and not executed_query:
            project_key = search_data.get('project')
            assignee = search_data.get('assignee')
            work_item_type = search_data.get('type')
            status = search_data.get('status')
            if not any([project_key, assignee, work_item_type, status]):
                return f'created >= -30d order by {order_by or "created DESC"}'

        if order_by:
            return main_screen._append_order_by(executed_query, order_by)

        return executed_query

    async def _populate_cache_section(self) -> None:
        stats = self._cache.get_stats()

        lines = []
        lines.append(f'Total Entries: {stats["total_entries"]}')
        lines.append(f'Active Entries: {stats["active_entries"]}')
        lines.append(f'Expired Entries: {stats["expired_entries"]}')

        if stats['cache_types']:
            lines.append(f'Cache Types: {", ".join(sorted(stats["cache_types"]))}')

        lines.append('')

        if stats['total_entries'] == 0:
            lines.append('No cached entries')
        else:
            cache_entries = []
            for key, entry in self._cache._cache.items():
                status = 'Expired' if entry.is_expired() else 'Active'
                ttl_info = (
                    f'{entry.ttl_seconds}s' if entry.ttl_seconds is not None else 'No expiration'
                )
                age_seconds = int((datetime.now() - entry.created_at).total_seconds())
                cache_entries.append((key, status, ttl_info, age_seconds))

            cache_entries.sort(key=lambda x: x[0])

            for key, status, ttl_info, age_seconds in cache_entries:
                lines.append(f'{key}')
                lines.append(f'  Status: {status}')
                lines.append(f'  TTL: {ttl_info}')
                lines.append(f'  Age: {age_seconds}s')
                lines.append('')

        self.cache_content.update('\n'.join(lines).rstrip())

    def _set_section_loading(self, section: str, is_loading: bool) -> None:
        if is_loading:
            self._loading_sections.add(section)
        else:
            self._loading_sections.discard(section)

        if section in {'server_info', 'global_settings'}:
            self.server_scroll.loading = bool(
                {'server_info', 'global_settings'} & self._loading_sections
            )
            return

        scroll_map = {
            'application': self.application_scroll,
            'config': self.config_scroll,
            'user': self.user_scroll,
            'cache': self.cache_scroll,
        }
        if section in scroll_map:
            scroll_map[section].loading = is_loading

    @work(exclusive=False)
    async def _fetch_server_info(self) -> None:
        try:
            app = cast('JiraApp', self.app)  # noqa: F821

            server_info: JiraServerInfo | None = self._cache.get('debug_server_info')

            if not server_info:
                response_server_info: APIControllerResponse = await app.api.server_info()
                if response_server_info.success and response_server_info.result:
                    server_info = response_server_info.result

                    self._cache.set('debug_server_info', server_info, ttl_seconds=None)

            self._update_server_section(server_info)
        finally:
            self._set_section_loading('server_info', False)

    def _update_server_section(self, server_info: JiraServerInfo | None) -> None:
        lines = []

        if server_info:
            lines.append(f'Base URL: {server_info.base_url}')
            lines.append(f'Version: {server_info.get_version()}')
            lines.append(f'Deployment Type: {server_info.get_deployment_type()}')
            lines.append(f'Build Number: {server_info.get_build_number()}')
            lines.append(f'Build Date: {server_info.get_build_date()}')
            lines.append(f'Server Time: {server_info.get_server_time()}')
            lines.append(f'Server Title: {server_info.get_server_title()}')
            lines.append(f'Default Locale: {server_info.get_default_locale()}')
            lines.append(f'Server Time Zone: {server_info.get_server_time_zone()}')

            if server_info.get_display_url_confluence():
                lines.append(f'Confluence URL: {server_info.get_display_url_confluence()}')
            if server_info.get_display_url_servicedesk_help_center():
                lines.append(
                    f'Servicedesk URL: {server_info.get_display_url_servicedesk_help_center()}'
                )
        else:
            lines.append('Unable to fetch server information')

        self.server_content.update('\n'.join(lines))

    @work(exclusive=False)
    async def _fetch_user_info(self) -> None:
        try:
            app = cast('JiraApp', self.app)  # noqa: F821

            user_info: JiraMyselfInfo | None = app.user_info

            if not user_info:
                user_info = self._cache.get('debug_user_info')

            if not user_info:
                response_myself: APIControllerResponse = await app.api.myself()
                if response_myself.success and response_myself.result:
                    user_info = response_myself.result

                    self._cache.set('debug_user_info', user_info, ttl_seconds=None)

            self._update_user_section(user_info)
        finally:
            self._set_section_loading('user', False)

    def _update_user_section(self, user_info: JiraMyselfInfo | None) -> None:
        lines = []

        if user_info:
            lines.append(f'Account ID: {user_info.get_account_id()}')
            lines.append(f'Account Type: {user_info.account_type}')

            status = 'Active' if user_info.active else 'Inactive'
            lines.append(f'Status: {status}')

            if user_info.display_name:
                lines.append(f'Display Name: {user_info.display_name}')
            if user_info.email:
                lines.append(f'Email: {user_info.email}')
            if user_info.user_groups:
                lines.append(f'User Groups: {user_info.user_groups}')
        else:
            lines.append('Unable to fetch user information')

        self.user_content.update('\n'.join(lines))

    @work(exclusive=False)
    async def _fetch_global_settings(self) -> None:
        try:
            app = cast('JiraApp', self.app)  # noqa: F821

            jira_global_settings: JiraGlobalSettings | None = self._cache.get(
                'debug_global_settings'
            )

            if not jira_global_settings:
                response_global_settings: APIControllerResponse = await app.api.global_settings()
                if response_global_settings.success and response_global_settings.result:
                    jira_global_settings = response_global_settings.result

                    self._cache.set('debug_global_settings', jira_global_settings, ttl_seconds=None)

            self._update_global_settings_section(jira_global_settings)
        finally:
            self._set_section_loading('global_settings', False)

    def _update_global_settings_section(
        self, jira_global_settings: JiraGlobalSettings | None
    ) -> None:
        lines = []

        if jira_global_settings:
            lines.append(f'Attachments: {jira_global_settings.display_attachments_enabled()}')
            lines.append(
                f'Work Item Linking: {jira_global_settings.display_work_item_linking_enabled()}'
            )
            lines.append(f'Subtasks: {jira_global_settings.display_subtasks_enabled()}')
            lines.append(f'Voting: {jira_global_settings.display_voting_enabled() or "Unknown"}')
            lines.append(f'Time Tracking: {jira_global_settings.display_time_tracking_enabled()}')
            lines.append(f'Watching: {jira_global_settings.display_watching_enabled()}')
            lines.append(
                'Unassigned Work Items: '
                f'{jira_global_settings.display_unassigned_work_items_allowed()}'
            )

            if tracking_config := jira_global_settings.time_tracking_configuration:
                lines.append('')
                lines.append(f'Default Unit: {tracking_config.display_default_unit()}')
                lines.append(f'Time Format: {tracking_config.display_time_format()}')
                lines.append(
                    f'Working Days/Week: {tracking_config.display_working_days_per_week()}'
                )
                lines.append(
                    f'Working Hours/Day: {tracking_config.display_working_hours_per_day()}'
                )
        else:
            lines.append('Unable to fetch global settings')

        self.global_content.update('\n'.join(lines))

    def on_key(self, event: events.Key) -> None:
        if event.key == 'escape':
            self.app.pop_screen()
            event.stop()
        elif event.key == 'pageup':
            self.modal_outer.scroll_page_up()
            event.stop()
        elif event.key == 'pagedown':
            self.modal_outer.scroll_page_down()
            event.stop()

    def action_focus_next(self) -> None:
        if self.tabs.tab_count > 0:
            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active
            tab_ids = [pane.id for pane in tab_panes if pane.id]

            for active_id, next_id in zip(tab_ids, tab_ids[1:], strict=False):
                if active_id == current_active:
                    self.tabs.active = next_id
                    break

    def action_focus_previous(self) -> None:
        """Focus previous tab (vim h key)."""
        if self.tabs.tab_count > 0:
            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active
            tab_ids = [pane.id for pane in tab_panes if pane.id]

            for prev_id, active_id in zip(tab_ids, tab_ids[1:], strict=False):
                if active_id == current_active:
                    self.tabs.active = prev_id
                    break
