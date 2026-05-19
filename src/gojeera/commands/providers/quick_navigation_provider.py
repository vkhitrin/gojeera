from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.command import Hit, Hits, Provider

from gojeera.utils.jira.reference import WorkItemReferenceLoader, load_work_item_reference
from gojeera.utils.jira.urls import extract_work_item_key

if TYPE_CHECKING:
    from gojeera.app import JiraApp


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

    async def search(self, query: str) -> Hits:
        raw_query = query.strip()
        work_item_key = extract_work_item_key(raw_query)
        if work_item_key is None:
            return

        label = f'Open work item {work_item_key}'
        matcher = self.matcher(query)
        score = matcher.match(label)
        if score <= 0:
            score = 1.0

        yield Hit(
            score,
            matcher.highlight(label),
            self._build_callback(raw_query),
            text=label,
            help='Load a work item by key or Jira browse URL',
        )
