from __future__ import annotations

from typing import cast

from gojeera.commands.providers import recent_items_provider

RECENT_SEARCHES_PALETTE_ID = 'recent-searches'
RECENT_SEARCHES_ACTION_LABEL = 'Recent Searches'
RECENT_SEARCHES_ACTION_HELP = 'Show the last 10 executed JQL searches'


class RecentSearchesProvider(recent_items_provider.RecentItemsProvider):
    """Expose recently executed JQL searches in the command palette."""

    palette_id = RECENT_SEARCHES_PALETTE_ID
    action_label = RECENT_SEARCHES_ACTION_LABEL
    action_help = RECENT_SEARCHES_ACTION_HELP
    action_name = 'show_recent_searches_palette'

    def _build_callback(self, _item_key_value: str):
        jql = _item_key_value

        async def run_recent_search() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_run_recent_search(jql)

        return run_recent_search

    async def _get_recent_searches(self) -> list[dict[str, str | float | None]]:
        return await recent_items_provider.get_recent_cache_items(
            lambda cache: cache.get_recent_searches()
        )

    async def _get_items(self) -> list[recent_items_provider.RecentItem]:
        return await self._get_recent_searches()

    @staticmethod
    def _format_label(item: dict[str, str | float | None]) -> str:
        return str(item['jql']).strip()

    @staticmethod
    def _format_help(item: dict[str, str | float | None]) -> str | None:
        return recent_items_provider.format_relative_timestamp(item.get('searched_at'), 'searched')
