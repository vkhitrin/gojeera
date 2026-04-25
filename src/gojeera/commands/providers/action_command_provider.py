from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from textual.command import DiscoveryHit, Hit, Hits, Provider


class ActionCommandProvider(Provider):
    """Shared command-palette provider for screen actions."""

    def _get_main_screen(self):
        from gojeera.app import JiraApp

        if isinstance(self.app, JiraApp):
            return self.app
        return None

    def _iter_commands(self) -> Iterable[tuple[str, str, str, Any]]:
        raise NotImplementedError

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

    def _make_callback(self, action: str, screen: Any):
        async def run_command() -> None:
            await self.app.run_action(action, screen)

        return run_command
