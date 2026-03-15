from __future__ import annotations

from typing import Protocol, cast

from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.config import CONFIGURATION


class FooterToggleApp(Protocol):
    def toggle_footer_visibility(self) -> None: ...


class FooterCommandProvider(Provider):
    """Command palette provider for toggling footer visibility."""

    @property
    def _command_text(self) -> str:
        return 'Hide Footer' if CONFIGURATION.get().show_footer else 'Show Footer'

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            self._command_text,
            self._toggle_footer,
            help='Toggle footer visibility',
        )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        score = matcher.match(self._command_text)
        if score > 0:
            yield Hit(
                score,
                matcher.highlight(self._command_text),
                self._toggle_footer,
                help='Toggle footer visibility',
            )

    async def _toggle_footer(self) -> None:
        cast(FooterToggleApp, self.app).toggle_footer_visibility()
