import importlib.metadata

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from gojeera.config import CONFIGURATION


class AppHeader(Vertical):
    """Custom header widget that displays the connected Jira instance."""

    jira_url: reactive[str] = reactive('Loading...')

    @staticmethod
    def _obfuscate_string(value: str) -> str:
        return 'obfuscated' if value else value

    def on_mount(self) -> None:
        self.set_timer(0.5, self._update_jira_url)

    def _update_jira_url(self) -> None:
        config = CONFIGURATION.get()

        server_info = getattr(self.app, 'server_info', None)

        if server_info and hasattr(server_info, 'base_url'):
            new_url = server_info.base_url
            self.jira_url = new_url
        else:
            new_url = config.jira.api_base_url
            self.jira_url = new_url

    def compose(self) -> ComposeResult:
        config = CONFIGURATION.get()

        try:
            version = importlib.metadata.version('gojeera')
        except importlib.metadata.PackageNotFoundError:
            version = 'unknown'

        authenticated_user = config.jira.api_username

        jira_url = self.jira_url
        if config.obfuscate_personal_info:
            jira_url = self._obfuscate_string(jira_url)
            authenticated_user = self._obfuscate_string(authenticated_user)

        yield Static(
            f'[b]gojeera[/] [dim]v{version}[/] | [b]Connected to:[/] [dim]{jira_url}[/] | '
            f'[b]Authenticated as:[/] [dim]{authenticated_user}[/]',
            id='app-header-info',
        )

    def watch_jira_url(self, new_url: str) -> None:
        """React to changes in jira_url by updating the Static widget."""
        if not self.is_mounted:
            return

        try:
            header_widget = self.query_one('#app-header-info', Static)
        except Exception:
            return

        config = CONFIGURATION.get()

        try:
            version = importlib.metadata.version('gojeera')
        except importlib.metadata.PackageNotFoundError:
            version = 'unknown'

        authenticated_user = config.jira.api_username
        jira_url = new_url

        if config.obfuscate_personal_info:
            jira_url = self._obfuscate_string(jira_url)
            authenticated_user = self._obfuscate_string(authenticated_user)

        new_text = (
            f'[b]gojeera[/] [dim]v{version}[/] | [b]Connected to:[/] [dim]{jira_url}[/] | '
            f'[b]Authenticated as:[/] [dim]{authenticated_user}[/]'
        )
        header_widget.update(new_text)
