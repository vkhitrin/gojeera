from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import humanize
from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.widgets.layout.sub_palette import mark_sub_command_palette_hit

RECENT_SEARCHES_PALETTE_ID = 'recent-searches'
RECENT_SEARCHES_ACTION_LABEL = 'Recent Searches'
RECENT_SEARCHES_ACTION_HELP = 'Show the last 10 executed JQL searches'


class RecentSearchesProvider(Provider):
    """Expose recently executed JQL searches in the command palette."""

    def _build_callback(self, jql: str):
        async def run_recent_search() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_run_recent_search(jql)

        return run_recent_search

    async def _get_recent_searches(self) -> list[dict[str, str | float | None]]:
        return await run_cache_io(lambda: get_cache().get_recent_searches())

    @staticmethod
    def _format_label(recent_search: dict[str, str | float | None]) -> str:
        return str(recent_search['jql']).strip()

    @staticmethod
    def _format_help(recent_search: dict[str, str | float | None]) -> str | None:
        searched_at = recent_search.get('searched_at')
        if not isinstance(searched_at, int | float):
            return None
        searched_at_datetime = datetime.fromtimestamp(float(searched_at), tz=timezone.utc)
        return f'Last searched {humanize.naturaltime(searched_at_datetime)}'

    @staticmethod
    def _mark_recent_search_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, RECENT_SEARCHES_PALETTE_ID)

    def _is_recent_searches_palette_active(self) -> bool:
        return (
            getattr(self.app, 'active_sub_command_palette_id', None) == RECENT_SEARCHES_PALETTE_ID
        )

    def _build_recent_search_discovery_hit(
        self, recent_search: dict[str, str | float | None]
    ) -> DiscoveryHit:
        label = self._format_label(recent_search)
        return DiscoveryHit(
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(label),
            text=label,
            help=self._format_help(recent_search),
        )

    def _build_recent_search_hit(
        self, recent_search: dict[str, str | float | None], score: float
    ) -> Hit:
        label = self._format_label(recent_search)
        return Hit(
            score,
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(label),
            text=label,
            help=self._format_help(recent_search),
        )

    def _build_recent_searches_action_callback(self):
        return lambda: self.app.run_action('show_recent_searches_palette')

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            RECENT_SEARCHES_ACTION_LABEL,
            self._build_recent_searches_action_callback(),
            help=RECENT_SEARCHES_ACTION_HELP,
        )

        if not self._is_recent_searches_palette_active():
            return

        for recent_search in await self._get_recent_searches():
            yield self._mark_recent_search_hit(
                self._build_recent_search_discovery_hit(recent_search)
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(RECENT_SEARCHES_ACTION_LABEL)
        if action_score > 0:
            yield Hit(
                action_score,
                matcher.highlight(RECENT_SEARCHES_ACTION_LABEL),
                self._build_recent_searches_action_callback(),
                help=RECENT_SEARCHES_ACTION_HELP,
            )

        if self._is_recent_searches_palette_active() is False:
            return

        recent_searches = await self._get_recent_searches()
        for recent_search in recent_searches:
            label = self._format_label(recent_search)
            score = matcher.match(label)
            if score > 0 or not query.strip():
                yield self._mark_recent_search_hit(
                    self._build_recent_search_hit(recent_search, score if score > 0 else 1.0)
                )
