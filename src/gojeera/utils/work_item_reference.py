from __future__ import annotations

from typing import Protocol, runtime_checkable

from gojeera.utils.urls import extract_work_item_key


@runtime_checkable
class WorkItemReferenceLoader(Protocol):
    async def fetch_work_items(self, selected_work_item_key: str) -> None: ...

    def notify(
        self,
        message: str,
        *,
        severity: str | None = None,
        title: str | None = None,
    ) -> None: ...


def resolve_work_item_reference(value: str) -> str | None:
    return extract_work_item_key(value)


async def load_work_item_reference(
    loader: WorkItemReferenceLoader,
    value: str,
    *,
    title: str = 'Quick Navigation',
) -> bool:
    work_item_key = resolve_work_item_reference(value)
    if work_item_key is None:
        loader.notify(
            'Invalid work item key format. Expected PROJECT-123 or a Jira browse URL.',
            severity='warning',
            title=title,
        )
        return False

    await loader.fetch_work_items(work_item_key)
    return True
