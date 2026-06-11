from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.utils.jira.reference import WorkItemReferenceLoader, load_work_item_reference
from gojeera.utils.jira.urls import extract_work_item_key
from gojeera.widgets.layout.sub_palette import mark_sub_command_palette_hit

if TYPE_CHECKING:
    from gojeera.app import JiraApp

QUICK_NAVIGATION_BROWSE_WORK_ITEM_PALETTE_ID = 'quick-navigation-browse-work-item'
QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_LABEL = 'Quick Navigation > Browse Work Item'
QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_HELP = 'Open a work item by key or Jira browse URL'


class QuickNavigationProvider(Provider):
    """Open Jira work items from command palette input."""

    def _build_callback(self, work_item_reference: str):
        async def open_work_item() -> None:
            app = cast('JiraApp', self.app)
            app.run_worker(
                load_work_item_reference(
                    cast(WorkItemReferenceLoader, app),
                    work_item_reference,
                    title='Quick Navigation',
                ),
                exclusive=True,
                group='work-item',
            )

        return open_work_item

    def _build_browse_work_item_action_callback(self):
        return lambda: self.app.run_action('show_browse_work_item_palette')

    def _is_browse_work_item_palette_active(self) -> bool:
        return (
            getattr(self.app, 'active_sub_command_palette_id', None)
            == QUICK_NAVIGATION_BROWSE_WORK_ITEM_PALETTE_ID
        )

    async def discover(self) -> Hits:
        yield DiscoveryHit(
            QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_LABEL,
            self._build_browse_work_item_action_callback(),
            help=QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_HELP,
        )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_LABEL)
        if action_score > 0:
            yield Hit(
                action_score,
                matcher.highlight(QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_LABEL),
                self._build_browse_work_item_action_callback(),
                help=QUICK_NAVIGATION_BROWSE_WORK_ITEM_ACTION_HELP,
            )

        if not self._is_browse_work_item_palette_active():
            return

        raw_query = query.strip()
        work_item_key = extract_work_item_key(raw_query)
        if work_item_key is None:
            return

        label = f'Open work item {work_item_key}'
        score = matcher.match(label)
        if score <= 0:
            score = 1.0

        yield mark_sub_command_palette_hit(
            Hit(
                score,
                matcher.highlight(label),
                self._build_callback(raw_query),
                text=label,
                help='Load a work item by key or Jira browse URL',
            ),
            QUICK_NAVIGATION_BROWSE_WORK_ITEM_PALETTE_ID,
        )
