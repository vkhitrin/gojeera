from __future__ import annotations

from time import monotonic
from typing import NamedTuple, cast

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.internal.models.jira import JiraFilterDict
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.config import CONFIGURATION
from gojeera.widgets.layout.sub_palette import (
    mark_command_palette_notice,
    mark_sub_command_palette_hit,
)

JQL_FILTERS_PALETTE_ID = 'jql-filters'
JQL_FILTERS_ACTION_LABEL = 'Quick Navigation > JQL Filters'
JQL_FILTERS_ACTION_HELP = 'Browse configured and remote JQL filters'
PREPARED_FILTERS_TTL_SECONDS = 5.0
MAX_DISPLAYED_FILTERS = 100
JQL_FILTERS_PALETTE_PLACEHOLDER = f'Search JQL filters (up to {MAX_DISPLAYED_FILTERS} results)…'


class PreparedJQLFilter(NamedTuple):
    label: str
    expression: str
    expression_casefold: str
    starred: bool


class JQLFiltersProvider(Provider):
    """Expose configured and remote JQL filters in the command palette."""

    palette_id = JQL_FILTERS_PALETTE_ID
    shows_result_limit_warning = True

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

    @staticmethod
    def _mark_filter_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, JQL_FILTERS_PALETTE_ID)

    def _is_jql_filters_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == JQL_FILTERS_PALETTE_ID

    async def _iter_filters(self) -> list[PreparedJQLFilter]:
        cached_filters = getattr(self, '_sorted_jql_filters', None)
        if cached_filters is not None and monotonic() < getattr(
            self, '_sorted_jql_filters_expires_at', 0.0
        ):
            return cast(list[PreparedJQLFilter], cached_filters)

        filters = []
        for filter_data in await self._get_jql_filters():
            label = self._format_label(filter_data)
            expression = self._clean_expression(filter_data.get('expression'))
            if not label or not expression:
                continue
            filters.append(
                PreparedJQLFilter(
                    label=label,
                    expression=expression,
                    expression_casefold=expression.casefold(),
                    starred=bool(filter_data.get('starred', False)),
                )
            )
        sorted_filters = sorted(
            filters,
            key=lambda prepared_filter: (
                not prepared_filter.starred,
                prepared_filter.label.casefold(),
            ),
        )
        self._sorted_jql_filters = sorted_filters
        self._sorted_jql_filters_expires_at = monotonic() + PREPARED_FILTERS_TTL_SECONDS
        return sorted_filters

    def _build_filter_discovery_hit(self, prepared_filter: PreparedJQLFilter) -> DiscoveryHit:
        return DiscoveryHit(
            Text(prepared_filter.label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(prepared_filter.expression),
            text=prepared_filter.label,
            help=prepared_filter.expression,
        )

    def _build_filter_hit(self, prepared_filter: PreparedJQLFilter, score: float) -> Hit:
        return Hit(
            score,
            Text(prepared_filter.label, no_wrap=True, overflow='ellipsis'),
            self._build_callback(prepared_filter.expression),
            text=prepared_filter.label,
            help=prepared_filter.expression,
        )

    def _build_limit_notice(self, total: int) -> DiscoveryHit:
        notice = DiscoveryHit(
            f'{MAX_DISPLAYED_FILTERS}-result limit: showing '
            f'{MAX_DISPLAYED_FILTERS} of {total} matches.',
            lambda: None,
            help='Type more characters to narrow the results',
        )
        return cast(
            DiscoveryHit,
            self._mark_filter_hit(mark_command_palette_notice(notice)),
        )

    def _build_jql_filters_action_callback(self):
        return lambda: self.app.run_action('show_jql_filters_palette')

    async def discover(self) -> Hits:
        if not self._is_jql_filters_palette_active():
            yield DiscoveryHit(
                JQL_FILTERS_ACTION_LABEL,
                self._build_jql_filters_action_callback(),
                help=JQL_FILTERS_ACTION_HELP,
            )
            return

        filters = await self._iter_filters()
        if len(filters) > MAX_DISPLAYED_FILTERS:
            yield self._build_limit_notice(len(filters))
        for prepared_filter in filters[:MAX_DISPLAYED_FILTERS]:
            yield self._mark_filter_hit(self._build_filter_discovery_hit(prepared_filter))

    async def search(self, query: str) -> Hits:
        if self._is_jql_filters_palette_active() is False:
            matcher = self.matcher(query)
            action_score = matcher.match(JQL_FILTERS_ACTION_LABEL)
            if action_score > 0:
                yield Hit(
                    action_score,
                    matcher.highlight(JQL_FILTERS_ACTION_LABEL),
                    self._build_jql_filters_action_callback(),
                    help=JQL_FILTERS_ACTION_HELP,
                )
            return

        matcher = self.matcher(query)
        normalized_query = query.strip()
        query_casefold = normalized_query.casefold()
        matches: list[tuple[float, PreparedJQLFilter]] = []
        for prepared_filter in await self._iter_filters():
            label_score = matcher.match(prepared_filter.label)
            expression_score = (
                0.75 if query_casefold in prepared_filter.expression_casefold else 0.0
            )
            score = max(label_score, expression_score)
            if score > 0:
                matches.append((score, prepared_filter))

        matches.sort(key=lambda match: match[0], reverse=True)
        if len(matches) > MAX_DISPLAYED_FILTERS:
            yield self._build_limit_notice(len(matches))
        for score, prepared_filter in matches[:MAX_DISPLAYED_FILTERS]:
            yield self._mark_filter_hit(self._build_filter_hit(prepared_filter, score))
