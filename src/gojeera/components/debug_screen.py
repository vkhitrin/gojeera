"""Debug information modal screen for displaying config, server info, and user details."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Static, TabbedContent, TabPane
import yaml

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.cache import get_cache
from gojeera.config import CONFIGURATION
from gojeera.models import JiraGlobalSettings, JiraMyselfInfo, JiraServerInfo
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class DebugInfoScreen(ModalScreen):
    """Modal screen for displaying debug information about gojeera configuration and Jira server."""

    BINDINGS = [
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

    @staticmethod
    def _obfuscate_if_enabled(value: str | None) -> str:
        if not value:
            return value or ''

        if CONFIGURATION.get().obfuscate_personal_info:
            return 'obfuscated'
        return value

    @property
    def tabs(self) -> TabbedContent:
        return self.query_one('#debug_tabs', TabbedContent)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('Debug Information', id='modal_title')
            with TabbedContent(initial='tab-config', id='debug_tabs'):
                with TabPane('Configuration', id='tab-config'):
                    with VerticalScroll():
                        yield GojeeraMarkdown(id='config-markdown')
                with TabPane('Server Info', id='tab-server'):
                    with VerticalScroll():
                        yield GojeeraMarkdown(id='server-markdown')
                        yield GojeeraMarkdown(id='global-markdown')
                with TabPane('User Info', id='tab-user'):
                    with VerticalScroll():
                        yield GojeeraMarkdown(id='user-markdown')
                with TabPane('Cache', id='tab-cache'):
                    with VerticalScroll():
                        yield GojeeraMarkdown(id='cache-markdown')

        yield Footer(show_command_palette=False)

    async def on_mount(self) -> None:
        container = self.query_one('#modal_outer')
        container.scroll_home()

        if CONFIGURATION.get().jumper.enabled:
            from textual.widgets._tabbed_content import ContentTab

            tabs = self.query_one('#debug_tabs', TabbedContent)
            content_tabs = list(tabs.query(ContentTab))
            for content_tab in content_tabs:
                content_tab.jump_mode = 'click'

        await self._populate_config_section()

        self._show_server_loading()
        self._show_user_loading()
        self._show_global_settings_loading()

        self._fetch_server_info()
        self._fetch_user_info()
        self._fetch_global_settings()

        await self._populate_cache_section()

    async def action_show_overlay(self) -> None:
        """Show the Jumper overlay to jump between widgets."""
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def _populate_config_section(self) -> None:
        config_md = self.query_one('#config-markdown', expect_type=GojeeraMarkdown)

        config = CONFIGURATION.get()

        import json as json_lib

        json_str = config.model_dump_json(exclude={'jira'})
        data = json_lib.loads(json_str)

        if CONFIGURATION.get().obfuscate_personal_info:
            self._obfuscate_dict(data)

        yaml_output = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

        lines = ['### Configuration\n']
        lines.append('```yaml')
        lines.append(yaml_output.rstrip())
        lines.append('```')

        config_md.update('\n'.join(lines))

    def _obfuscate_dict(self, data: dict) -> None:
        if not CONFIGURATION.get().obfuscate_personal_info:
            return

        for key, value in data.items():
            if isinstance(value, dict):
                self._obfuscate_dict(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self._obfuscate_dict(item)
            elif isinstance(value, str) and value:
                if any(indicator in value.lower() for indicator in ['http', '@', 'user', 'name']):
                    data[key] = 'obfuscated'

    async def _populate_cache_section(self) -> None:
        cache_md = self.query_one('#cache-markdown', expect_type=GojeeraMarkdown)

        stats = self._cache.get_stats()

        lines = ['### Cache Statistics\n']
        lines.append(f'**Total Entries**: `{stats["total_entries"]}`  ')
        lines.append(f'**Active Entries**: `{stats["active_entries"]}`  ')
        lines.append(f'**Expired Entries**: `{stats["expired_entries"]}`  ')

        if stats['cache_types']:
            lines.append(f'\n**Cache Types**: `{", ".join(sorted(stats["cache_types"]))}`  ')

        lines.append('\n### Cache Entries\n')

        if stats['total_entries'] == 0:
            lines.append('*No cached entries*')
        else:
            cache_entries = []
            for key, entry in self._cache._cache.items():
                status = '✗ Expired' if entry.is_expired() else '✓ Active'
                ttl_info = (
                    f'{entry.ttl_seconds}s' if entry.ttl_seconds is not None else 'No expiration'
                )
                age_seconds = int((datetime.now() - entry.created_at).total_seconds())
                cache_entries.append((key, status, ttl_info, age_seconds))

            cache_entries.sort(key=lambda x: x[0])

            lines.append('| Key | Status | TTL | Age |')
            lines.append('|-----|--------|-----|-----|')

            for key, status, ttl_info, age_seconds in cache_entries:
                lines.append(f'| `{key}` | {status} | `{ttl_info}` | `{age_seconds}s` |')

        cache_md.update('\n'.join(lines))

    def _show_server_loading(self) -> None:
        with self.app.batch_update():
            server_md = self.query_one('#server-markdown', expect_type=GojeeraMarkdown)
            server_md.update('*Loading server information...*')

    def _show_user_loading(self) -> None:
        with self.app.batch_update():
            user_md = self.query_one('#user-markdown', expect_type=GojeeraMarkdown)
            user_md.update('*Loading user information...*')

    def _show_global_settings_loading(self) -> None:
        with self.app.batch_update():
            global_md = self.query_one('#global-markdown', expect_type=GojeeraMarkdown)
            global_md.update('*Loading global settings...*')

    @work(exclusive=False)
    async def _fetch_server_info(self) -> None:
        app = cast('JiraApp', self.app)  # noqa: F821

        server_info: JiraServerInfo | None = self._cache.get('debug_server_info')

        if not server_info:
            response_server_info: APIControllerResponse = await app.api.server_info()
            if response_server_info.success and response_server_info.result:
                server_info = response_server_info.result

                self._cache.set('debug_server_info', server_info, ttl_seconds=None)

        self._update_server_section(server_info)

    def _update_server_section(self, server_info: JiraServerInfo | None) -> None:
        server_md = self.query_one('#server-markdown', expect_type=GojeeraMarkdown)

        lines = []

        if server_info:
            lines.append('### Server Details\n')
            lines.append(f'**Base URL**: `{self._obfuscate_if_enabled(server_info.base_url)}`  ')
            lines.append(f'**Version**: `{server_info.get_version()}`  ')
            lines.append(f'**Deployment Type**: `{server_info.get_deployment_type()}`  ')
            lines.append(f'**Build Number**: `{server_info.get_build_number()}`  ')
            lines.append(f'**Build Date**: `{server_info.get_build_date()}`  ')
            lines.append(f'**Server Time**: `{server_info.get_server_time()}`  ')
            lines.append(f'**Server Title**: `{server_info.get_server_title()}`  ')
            lines.append(f'**Default Locale**: `{server_info.get_default_locale()}`  ')
            lines.append(f'**Server Time Zone**: `{server_info.get_server_time_zone()}`  ')

            if server_info.get_display_url_confluence():
                lines.append(
                    f'**Confluence URL**: `{self._obfuscate_if_enabled(server_info.get_display_url_confluence())}`  '
                )
            if server_info.get_display_url_servicedesk_help_center():
                lines.append(
                    f'**Servicedesk URL**: `{self._obfuscate_if_enabled(server_info.get_display_url_servicedesk_help_center())}`  '
                )
        else:
            lines.append('*Unable to fetch server information*')

        server_md.update('\n'.join(lines))

    @work(exclusive=False)
    async def _fetch_user_info(self) -> None:
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

    def _update_user_section(self, user_info: JiraMyselfInfo | None) -> None:
        user_md = self.query_one('#user-markdown', expect_type=GojeeraMarkdown)

        lines = []

        if user_info:
            lines.append('### Account Details\n')
            lines.append(
                f'**Account ID**: `{self._obfuscate_if_enabled(user_info.get_account_id())}`  '
            )
            lines.append(f'**Account Type**: `{user_info.account_type}`  ')

            status = '✓ Active' if user_info.active else '✗ Inactive'
            lines.append(f'**Status**: {status}  ')

            if user_info.display_name:
                lines.append(
                    f'**Display Name**: `{self._obfuscate_if_enabled(user_info.display_name)}`  '
                )
            if user_info.email:
                lines.append(f'**Email**: `{self._obfuscate_if_enabled(user_info.email)}`  ')
            if user_info.user_groups:
                lines.append(f'**User Groups**: `{user_info.user_groups}`  ')
        else:
            lines.append('*Unable to fetch user information*')

        user_md.update('\n'.join(lines))

    @work(exclusive=False)
    async def _fetch_global_settings(self) -> None:
        app = cast('JiraApp', self.app)  # noqa: F821

        jira_global_settings: JiraGlobalSettings | None = self._cache.get('debug_global_settings')

        if not jira_global_settings:
            response_global_settings: APIControllerResponse = await app.api.global_settings()
            if response_global_settings.success and response_global_settings.result:
                jira_global_settings = response_global_settings.result

                self._cache.set('debug_global_settings', jira_global_settings, ttl_seconds=None)

        self._update_global_settings_section(jira_global_settings)

    def _update_global_settings_section(
        self, jira_global_settings: JiraGlobalSettings | None
    ) -> None:
        global_md = self.query_one('#global-markdown', expect_type=GojeeraMarkdown)

        lines = []

        if jira_global_settings:
            lines.append('### Features\n')
            lines.append(f'**Attachments**: {jira_global_settings.display_attachments_enabled()}  ')
            lines.append(
                f'**Work Item Linking**: {jira_global_settings.display_work_item_linking_enabled()}  '
            )
            lines.append(f'**Subtasks**: {jira_global_settings.display_subtasks_enabled()}  ')
            lines.append(
                f'**Voting**: {jira_global_settings.display_voting_enabled() or "Unknown"}  '
            )
            lines.append(
                f'**Time Tracking**: {jira_global_settings.display_time_tracking_enabled()}  '
            )
            lines.append(f'**Watching**: {jira_global_settings.display_watching_enabled()}  ')
            lines.append(
                f'**Unassigned Work Items**: {jira_global_settings.display_unassigned_work_items_allowed()}  '
            )

            if tracking_config := jira_global_settings.time_tracking_configuration:
                lines.append('\n### Time Tracking Configuration\n')
                lines.append(f'**Default Unit**: `{tracking_config.display_default_unit()}`  ')
                lines.append(f'**Time Format**: `{tracking_config.display_time_format()}`  ')
                lines.append(
                    f'**Working Days/Week**: `{tracking_config.display_working_days_per_week()}`  '
                )
                lines.append(
                    f'**Working Hours/Day**: `{tracking_config.display_working_hours_per_day()}`  '
                )
        else:
            lines.append('*Unable to fetch global settings*')

        global_md.update('\n'.join(lines))

    def on_key(self, event: events.Key) -> None:
        if event.key == 'escape':
            self.app.pop_screen()
            event.stop()
        elif event.key == 'pageup':
            container = self.query_one('#modal_outer')
            container.scroll_page_up()
            event.stop()
        elif event.key == 'pagedown':
            container = self.query_one('#modal_outer')
            container.scroll_page_down()
            event.stop()

    def on_click(self) -> None:
        self.app.pop_screen()

    def action_focus_next(self) -> None:
        if self.tabs.tab_count > 0:
            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active
            tab_ids = [pane.id for pane in tab_panes if pane.id]

            if current_active in tab_ids:
                current_index = tab_ids.index(current_active)
                if current_index < len(tab_ids) - 1:
                    next_id = tab_ids[current_index + 1]
                    self.tabs.active = next_id

    def action_focus_previous(self) -> None:
        """Focus previous tab (vim h key)."""
        if self.tabs.tab_count > 0:
            tab_panes = list(self.tabs.query('TabPane'))
            if not tab_panes:
                return

            current_active = self.tabs.active
            tab_ids = [pane.id for pane in tab_panes if pane.id]

            if current_active in tab_ids:
                current_index = tab_ids.index(current_active)
                if current_index > 0:
                    prev_id = tab_ids[current_index - 1]
                    self.tabs.active = prev_id
