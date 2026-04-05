from __future__ import annotations

from textual.command import DiscoveryHit, Hit, Hits, Provider


class SearchCommandProvider(Provider):
    """Expose search-related commands in the command palette."""

    def _get_main_screen(self):
        from gojeera.app import MainScreen

        if isinstance(self.screen, MainScreen):
            return self.screen
        return None

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

    async def discover(self) -> Hits:
        for label, action, help_text, screen in self._iter_commands():
            yield DiscoveryHit(
                label,
                self._make_callback(action, screen),
                help=help_text,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for label, action, help_text, screen in self._iter_commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    self._make_callback(action, screen),
                    help=help_text,
                )

    def _make_callback(self, action: str, screen):
        async def run_command() -> None:
            await self.app.run_action(action, screen)

        return run_command
