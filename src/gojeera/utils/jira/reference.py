from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from gojeera.utils.jira.urls import (
    extract_focused_comment_id,
    extract_focused_work_log_id,
    extract_work_item_key,
)

if TYPE_CHECKING:
    from gojeera.internal.models.work_items import JiraWorkItem


LOOKUP_WORK_ITEM_FIELDS = ['id', 'key', 'summary', 'issuetype', 'status']


@dataclass(frozen=True)
class WorkItemNavigationTarget:
    focused_comment_id: str | None = None
    focused_work_log_id: str | None = None

    @property
    def has_target(self) -> bool:
        return self.focused_comment_id is not None or self.focused_work_log_id is not None


@dataclass(frozen=True)
class WorkItemReference:
    work_item_key: str
    navigation_target: WorkItemNavigationTarget | None = None


@runtime_checkable
class WorkItemReferenceLoader(Protocol):
    async def load_work_item(self, selected_work_item_key: str) -> bool: ...

    def set_pending_work_item_navigation_target(
        self, target: WorkItemNavigationTarget | None
    ) -> None: ...

    def notify(
        self,
        message: str,
        *,
        severity: str | None = None,
        title: str | None = None,
    ) -> None: ...


@runtime_checkable
class WorkItemLookupAPI(Protocol):
    async def get_work_item(
        self,
        work_item_id_or_key: str,
        fields: list[str] | None = None,
    ): ...


def parse_work_item_reference(value: str) -> WorkItemReference | None:
    work_item_key = extract_work_item_key(value)
    if work_item_key is None:
        return None

    navigation_target = WorkItemNavigationTarget(
        focused_comment_id=extract_focused_comment_id(value),
        focused_work_log_id=extract_focused_work_log_id(value),
    )

    return WorkItemReference(
        work_item_key=work_item_key,
        navigation_target=navigation_target if navigation_target.has_target else None,
    )


def resolve_work_item_reference(value: str) -> str | None:
    reference = parse_work_item_reference(value)
    return reference.work_item_key if reference else None


async def lookup_work_item_for_reference(
    api: WorkItemLookupAPI,
    work_item_key: str,
) -> JiraWorkItem | None:
    response = await api.get_work_item(
        work_item_id_or_key=work_item_key,
        fields=LOOKUP_WORK_ITEM_FIELDS,
    )
    if not response.success or not response.result or not response.result.work_items:
        return None
    return response.result.work_items[0]


async def load_work_item_reference(
    loader: WorkItemReferenceLoader,
    value: str,
    *,
    title: str = 'Quick Navigation',
) -> bool:
    reference = parse_work_item_reference(value)
    if reference is None:
        loader.notify(
            'Invalid work item key format. Expected PROJECT-123 or a Jira browse URL.',
            severity='warning',
            title=title,
        )
        return False

    loader.set_pending_work_item_navigation_target(reference.navigation_target)
    loaded = await loader.load_work_item(reference.work_item_key)
    if not loaded:
        loader.set_pending_work_item_navigation_target(None)
    return loaded
