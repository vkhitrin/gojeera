from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

import humanize
from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.widgets.layout.sub_palette import mark_sub_command_palette_hit
from gojeera.internal.store.cache import get_cache, run_cache_io

RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID = 'recently-viewed-work-items'
RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL = 'Recently Viewed Work Items'
RECENTLY_VIEWED_WORK_ITEMS_ACTION_HELP = 'Show the last 10 viewed work items'


class RecentlyViewedWorkItemsProvider(Provider):
    """Expose recently viewed work items in the command palette."""

    def _build_callback(self, work_item_key: str):
        async def open_work_item() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            app.run_worker(app.load_work_item(work_item_key), exclusive=True, group='work-item')

        return open_work_item

    async def _get_recently_viewed_work_items(self) -> list[dict[str, str | float | None]]:
        return await run_cache_io(lambda: get_cache().get_recently_viewed_work_items())

    @staticmethod
    def _format_label(recently_viewed_work_item: dict[str, str | float | None]) -> str:
        work_item_key = str(recently_viewed_work_item['key'])
        raw_work_item_type = recently_viewed_work_item.get('work_item_type')
        work_item_type = raw_work_item_type.strip() if isinstance(raw_work_item_type, str) else ''
        raw_summary = recently_viewed_work_item.get('summary')
        summary = raw_summary.strip() if isinstance(raw_summary, str) else ''

        label_parts = []
        if work_item_type:
            label_parts.append(f'[{work_item_type}]')
        label_parts.append(work_item_key)
        if summary:
            label_parts.append(summary)
        return ' '.join(label_parts)

    @staticmethod
    def _format_help(recently_viewed_work_item: dict[str, str | float | None]) -> str | None:
        viewed_at = recently_viewed_work_item.get('viewed_at')
        if not isinstance(viewed_at, int | float):
            return None
        viewed_at_datetime = datetime.fromtimestamp(float(viewed_at), tz=timezone.utc)
        return f'Last viewed {humanize.naturaltime(viewed_at_datetime)}'

    @staticmethod
    def _mark_recent_item_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID)

    def _is_recently_viewed_palette_active(self) -> bool:
        return (
            getattr(self.app, 'active_sub_command_palette_id', None)
            == RECENTLY_VIEWED_WORK_ITEMS_PALETTE_ID
        )

    def _build_recent_item_discovery_hit(
        self, recently_viewed_work_item: dict[str, str | float | None]
    ) -> DiscoveryHit:
        label = self._format_label(recently_viewed_work_item)
        return DiscoveryHit(
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(str(recently_viewed_work_item['key'])),
            text=label,
            help=self._format_help(recently_viewed_work_item),
        )

    def _build_recent_item_hit(
        self, recently_viewed_work_item: dict[str, str | float | None], score: float
    ) -> Hit:
        label = self._format_label(recently_viewed_work_item)
        return Hit(
            score,
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(str(recently_viewed_work_item['key'])),
            text=label,
            help=self._format_help(recently_viewed_work_item),
        )

    def _build_recently_viewed_action_callback(self):
        return lambda: self.app.run_action('show_recently_viewed_work_items_palette')

    def _should_show_recently_viewed_work_items(self) -> bool:
        return self._is_recently_viewed_palette_active()

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL,
            self._build_recently_viewed_action_callback(),
            help=RECENTLY_VIEWED_WORK_ITEMS_ACTION_HELP,
        )

        if not self._should_show_recently_viewed_work_items():
            return

        for recently_viewed_work_item in await self._get_recently_viewed_work_items():
            yield self._mark_recent_item_hit(
                self._build_recent_item_discovery_hit(recently_viewed_work_item)
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL)
        if action_score > 0:
            yield Hit(
                action_score,
                matcher.highlight(RECENTLY_VIEWED_WORK_ITEMS_ACTION_LABEL),
                self._build_recently_viewed_action_callback(),
                help=RECENTLY_VIEWED_WORK_ITEMS_ACTION_HELP,
            )

        if self._is_recently_viewed_palette_active() is False:
            return

        recently_viewed_work_items = await self._get_recently_viewed_work_items()
        for recently_viewed_work_item in recently_viewed_work_items:
            label = self._format_label(recently_viewed_work_item)
            score = matcher.match(label)
            if score > 0 or not query.strip():
                yield self._mark_recent_item_hit(
                    self._build_recent_item_hit(
                        recently_viewed_work_item, score if score > 0 else 1.0
                    )
                )
