from __future__ import annotations

from typing import cast

from gojeera.commands.providers.recent_items_provider import (
    RecentItem,
    RecentItemsProvider,
    format_relative_timestamp,
    get_recent_cache_items,
)

RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID = 'recently-viewed-work-items'
RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL = 'Recently Viewed Work Items'
RECENTLY_VIEWED_WORK_ITEMS_ACTION_HELP = 'Show the last 10 viewed work items'


class RecentlyViewedWorkItemsProvider(RecentItemsProvider):
    """Expose recently viewed work items in the command palette."""

    palette_id = RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID
    action_label = RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL
    action_help = RECENTLY_VIEWED_WORK_ITEMS_ACTION_HELP
    action_name = 'show_recently_viewed_work_items_palette'

    def _build_callback(self, _item_key_value: str):
        work_item_key = _item_key_value

        async def open_work_item() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            app.run_worker(app.load_work_item(work_item_key), exclusive=True, group='work-item')

        return open_work_item

    async def _get_recently_viewed_work_items(self) -> list[dict[str, str | float | None]]:
        return await get_recent_cache_items(lambda cache: cache.get_recently_viewed_work_items())

    async def _get_items(self) -> list[RecentItem]:
        return await self._get_recently_viewed_work_items()

    @staticmethod
    def _format_label(item: dict[str, str | float | None]) -> str:
        work_item_key = str(item['key'])
        raw_work_item_type = item.get('work_item_type')
        work_item_type = raw_work_item_type.strip() if isinstance(raw_work_item_type, str) else ''
        raw_summary = item.get('summary')
        summary = raw_summary.strip() if isinstance(raw_summary, str) else ''

        label_parts = []
        if work_item_type:
            label_parts.append(f'[{work_item_type}]')
        label_parts.append(work_item_key)
        if summary:
            label_parts.append(summary)
        return ' '.join(label_parts)

    @staticmethod
    def _format_help(item: dict[str, str | float | None]) -> str | None:
        return format_relative_timestamp(item.get('viewed_at'), 'viewed')

    def _item_key(self, item: RecentItem) -> str:
        return str(item['key'])
