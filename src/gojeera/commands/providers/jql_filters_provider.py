from __future__ import annotations

from typing import cast

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.internal.models.jira import JiraFilterDict
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.config import CONFIGURATION
from gojeera.widgets.layout.sub_palette import mark_sub_command_palette_hit

JQL_FILTERS_PALETTE_ID = 'jql-filters'
JQL_FILTERS_ACTION_LABEL = 'Quick Navigation > JQL Filters'
JQL_FILTERS_ACTION_HELP = 'Browse configured and remote JQL filters'


class JQLFiltersProvider(Provider):
    """Expose configured and remote JQL filters in the command palette."""

    def _build_callback(self, expression: str):
        async def run_filter() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_run_jql_filter(expression)

        return run_filter

    async def _get_jql_filters(self) -> list[JiraFilterDict]:
        from gojeera.app import JiraApp

        app = cast('JiraApp', self.app)
        filters = list(CONFIGURATION.get().jql_filters or [])
        user_info = app.atlassian_context.user_info
        if user_info is None:
            return filters

        try:
            cached_filters = await run_cache_io(
                lambda: get_cache().get_remote_filters(user_info.account_id, allow_stale=True)
            )
        except Exception:
            return filters

        if not cached_filters:
            return filters

        filters.extend(filter_data.as_filter_dict() for filter_data in cached_filters)
        return filters

    @staticmethod
    def _clean_expression(expression: object) -> str:
        return str(expression or '').replace('\n', ' ').replace('\t', ' ').strip()

    @staticmethod
    def _format_label(filter_data: JiraFilterDict) -> str:
        label = str(filter_data.get('label') or '').strip()
        source = str(filter_data.get('source') or 'local').strip()
        source_label = 'Remote' if source == 'remote' else 'Local'
        starred = ' ★' if filter_data.get('starred', False) else ''
        return f'[{source_label}{starred}] {label}' if label else ''

    @classmethod
    def _format_help(cls, filter_data: JiraFilterDict) -> str | None:
        expression = cls._clean_expression(filter_data.get('expression'))
        return expression or None

    @staticmethod
    def _mark_filter_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, JQL_FILTERS_PALETTE_ID)

    def _is_jql_filters_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == JQL_FILTERS_PALETTE_ID

    async def _iter_filters(self) -> list[JiraFilterDict]:
        filters = [
            filter_data
            for filter_data in await self._get_jql_filters()
            if self._format_label(filter_data)
            and self._clean_expression(filter_data.get('expression'))
        ]
        return sorted(
            filters,
            key=lambda filter_data: (
                not bool(filter_data.get('starred', False)),
                str(filter_data.get('label') or '').casefold(),
            ),
        )

    def _build_filter_discovery_hit(self, filter_data: JiraFilterDict) -> DiscoveryHit:
        label = self._format_label(filter_data)
        expression = self._clean_expression(filter_data.get('expression'))
        return DiscoveryHit(
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(expression),
            text=label,
            help=self._format_help(filter_data),
        )

    def _build_filter_hit(self, filter_data: JiraFilterDict, score: float) -> Hit:
        label = self._format_label(filter_data)
        expression = self._clean_expression(filter_data.get('expression'))
        return Hit(
            score,
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(expression),
            text=label,
            help=self._format_help(filter_data),
        )

    def _build_jql_filters_action_callback(self):
        return lambda: self.app.run_action('show_jql_filters_palette')

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            JQL_FILTERS_ACTION_LABEL,
            self._build_jql_filters_action_callback(),
            help=JQL_FILTERS_ACTION_HELP,
        )

        if not self._is_jql_filters_palette_active():
            return

        for filter_data in await self._iter_filters():
            yield self._mark_filter_hit(self._build_filter_discovery_hit(filter_data))

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(JQL_FILTERS_ACTION_LABEL)
        if action_score > 0:
            yield Hit(
                action_score,
                matcher.highlight(JQL_FILTERS_ACTION_LABEL),
                self._build_jql_filters_action_callback(),
                help=JQL_FILTERS_ACTION_HELP,
            )

        if self._is_jql_filters_palette_active() is False:
            return

        for filter_data in await self._iter_filters():
            label = self._format_label(filter_data)
            expression = self._clean_expression(filter_data.get('expression'))
            score = max(matcher.match(label), matcher.match(expression))
            if score > 0 or not query.strip():
                yield self._mark_filter_hit(
                    self._build_filter_hit(filter_data, score if score > 0 else 1.0)
                )
