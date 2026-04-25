from __future__ import annotations

from gojeera.commands.providers.action_command_provider import ActionCommandProvider


class SearchCommandProvider(ActionCommandProvider):
    """Expose search-related commands in the command palette."""

    def _iter_commands(self):
        screen = self._get_main_screen()
        if not screen:
            return

        if screen.search_results_container.search_active:
            yield (
                'Clear Search',
                'clear_search',
                'Remove Search Results',
                screen,
            )
