from abc import abstractmethod
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timezone
from typing import Any

import humanize
from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.internal.store.cache import ApplicationCache, get_cache, run_cache_io
from gojeera.widgets.layout.sub_palette import mark_sub_command_palette_hit

RecentItem = dict[str, str | float | None]


async def get_recent_cache_items(
    getter: Callable[[ApplicationCache], list[RecentItem]],
) -> list[RecentItem]:
    return await run_cache_io(lambda: getter(get_cache()))


def format_relative_timestamp(value: object, action: str) -> str | None:
    if not isinstance(value, int | float):
        return None
    timestamp = datetime.fromtimestamp(float(value), tz=timezone.utc)
    return f'Last {action} {humanize.naturaltime(timestamp)}'


class RecentItemsProvider(Provider):
    """Shared command-palette behavior for persisted recent-item lists."""

    palette_id: str
    action_label: str
    action_help: str
    action_name: str

    @abstractmethod
    async def _get_items(self) -> list[RecentItem]: ...

    @staticmethod
    @abstractmethod
    def _format_label(item: RecentItem) -> str: ...

    @staticmethod
    @abstractmethod
    def _format_help(item: RecentItem) -> str | None: ...

    @abstractmethod
    def _build_callback(self, _item_key_value: str) -> Any: ...

    def _item_key(self, item: RecentItem) -> str:
        return self._format_label(item)

    def _action_callback(self):
        return lambda: self.app.run_action(self.action_name)

    def _is_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == self.palette_id

    def _mark_item_hit(self, hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, self.palette_id)

    def _build_item_discovery_hit(self, item: RecentItem) -> DiscoveryHit:
        label = self._format_label(item)
        return DiscoveryHit(
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(self._item_key(item)),
            text=label,
            help=self._format_help(item),
        )

    def _build_item_hit(self, item: RecentItem, score: float) -> Hit:
        label = self._format_label(item)
        return Hit(
            score,
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(self._item_key(item)),
            text=label,
            help=self._format_help(item),
        )

    async def _active_items(self) -> AsyncIterator[RecentItem]:
        if not self._is_palette_active():
            return
        for item in await self._get_items():
            yield item

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            self.action_label,
            self._action_callback(),
            help=self.action_help,
        )
        async for item in self._active_items():
            yield self._mark_item_hit(self._build_item_discovery_hit(item))

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(self.action_label)
        if action_score > 0:
            yield Hit(
                action_score,
                matcher.highlight(self.action_label),
                self._action_callback(),
                help=self.action_help,
            )
        async for item in self._active_items():
            label = self._format_label(item)
            score = matcher.match(label)
            if score > 0 or not query.strip():
                yield self._mark_item_hit(self._build_item_hit(item, score if score > 0 else 1.0))
