"""Bounded, read-only aggregation; this is not Jira's notification feed."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from gojeera.internal.jira.controller import APIController
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    JiraWorkItemSearchResponse,
    PaginatedWorkItemComments,
)
from gojeera.internal.store.config import ForYouConfig
from gojeera.utils.jira.jql import quote_jql_string

ForYouSection = Literal['due', 'updated', 'mentions']

SEARCH_FIELDS = ['summary', 'status', 'issuetype', 'duedate', 'updated']


@dataclass
class ForYouEntry:
    work_item: JiraWorkItem
    activity_at: datetime | None = None


@dataclass
class ForYouResult:
    entries: list[ForYouEntry] = field(default_factory=list)
    note: str = ''
    error: str | None = None
    limited: bool = False
    failed_comment_items: int = 0


def contains_mention(node: object, account_id: str) -> bool:
    """Match an actual ADF mention, never a display name or plain-text occurrence."""
    if isinstance(node, dict):
        if node.get('type') == 'mention':
            attrs = node.get('attrs')
            return isinstance(attrs, dict) and attrs.get('id') == account_id
        return contains_mention(node.get('content'), account_id)
    if isinstance(node, list):
        return any(contains_mention(child, account_id) for child in node)
    return False


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


class ForYouService:
    def __init__(self, api: APIController, config: ForYouConfig) -> None:
        self.api = api
        self.config = config

    async def _search(self, jql: str, limit: int) -> tuple[list[JiraWorkItem], bool]:
        items: dict[str, JiraWorkItem] = {}
        token: str | None = None
        seen_tokens: set[str] = set()
        while len(items) < limit and len(seen_tokens) < limit:
            response = await self.api.search_work_items(
                jql_query=jql,
                fields=SEARCH_FIELDS,
                limit=min(100, limit - len(items)),
                next_page_token=token,
            )
            if not response.success:
                raise ValueError(response.error or 'Search failed.')
            page = cast(JiraWorkItemSearchResponse, response.result)
            for item in page.work_items:
                items[item.key] = item
            token = page.next_page_token
            if page.is_last or not token:
                return list(items.values())[:limit], len(items) > limit
            if token in seen_tokens or not page.work_items:
                return list(items.values())[:limit], True
            seen_tokens.add(token)
        return list(items.values())[:limit], True

    async def load(
        self,
        section: ForYouSection,
        account_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ForYouResult:
        """Keep errors local to one section, including permissions and unsupported JQL."""
        try:
            if section == 'mentions':
                if not account_id:
                    return ForYouResult(
                        note='Mentions unavailable: current user is not loaded. Refresh to retry.',
                        error='Current user is not loaded.',
                    )
                return await self._mentions(account_id, _utc(now or datetime.now(timezone.utc)))
            if section == 'due':
                jql = (
                    'assignee = currentUser() AND statusCategory != Done '
                    f'AND duedate <= endOfDay("+{self.config.due_soon_days}d") '
                    'ORDER BY duedate ASC, updated DESC'
                )
                note = f'Open assignments overdue or due within {self.config.due_soon_days} days.'
            else:
                jql = (
                    '(assignee = currentUser() OR watcher = currentUser()) '
                    f'AND updated >= -{self.config.recent_days}d ORDER BY updated DESC'
                )
                note = (
                    f'Assigned or watched items updated in the last {self.config.recent_days} days.'
                )
            items, limited = await self._search(jql, self.config.items_per_section)
            if limited:
                note += f' Showing the first {len(items)} matches; more may exist.'
            if not items:
                note += ' No matching work items.'
            return ForYouResult(
                [ForYouEntry(item, _utc(item.updated) if item.updated else None) for item in items],
                note,
                limited=limited,
            )
        except Exception as error:
            return ForYouResult(note=f'Unable to load this section: {error}', error=str(error))

    async def _mentions(self, account_id: str, now: datetime) -> ForYouResult:
        cutoff = now - timedelta(days=self.config.recent_days)
        # Quote the account ID as a Lucene phrase, then quote that phrase for JQL.
        # The text index selects candidates only; comments still require ADF verification.
        phrase = quote_jql_string(quote_jql_string(account_id))
        items, limited = await self._search(
            f'updated >= -{self.config.recent_days}d AND comment ~ {phrase} ORDER BY updated DESC',
            self.config.mention_scan_items,
        )
        semaphore = asyncio.Semaphore(4)

        async def scan(item: JiraWorkItem) -> tuple[ForYouEntry | None, bool, bool]:
            async with semaphore:
                try:
                    return await self._scan_comments(item, account_id, cutoff, now)
                except Exception:
                    return None, False, True

        scanned = await asyncio.gather(*(scan(item) for item in items))
        entries = [entry for entry, _, _ in scanned if entry is not None]
        entries.sort(key=lambda entry: entry.activity_at or cutoff, reverse=True)
        failed = sum(failed for _, _, failed in scanned)
        capped = sum(capped for _, capped, _ in scanned)
        note = (
            f'Verified mention matches: {len(entries)}. '
            f'Best effort: scanned {len(items) - failed}/{len(items)} account-ID search candidates, '
            f'up to {self.config.comments_per_item} newest comments each. '
            f'Mentions in comments created or edited within {self.config.recent_days} days; '
            'an edit does not prove the mention itself is new. Descriptions are not scanned. '
            'Only indexed candidates are scanned; Jira may not index every mention.'
        )
        if limited:
            note += (
                ' Item scan limit reached; more items may contain mentions. '
                'Increase for_you.mention_scan_items to expand coverage.'
            )
        if capped:
            note += f' Comment scan incomplete for {capped} items.'
        if failed:
            note += f' Comments unavailable for {failed} items; refresh to retry.'
        if len(entries) > self.config.items_per_section:
            note += f' Showing the latest {self.config.items_per_section} matching items.'
        if not items:
            note += ' No account-ID comment-search candidates found.'
        if not entries:
            note += ' No verified mentions found in scanned comments.'
        return ForYouResult(
            entries[: self.config.items_per_section],
            note,
            limited=limited or len(entries) > self.config.items_per_section,
            failed_comment_items=failed,
        )

    async def _scan_comments(
        self, item: JiraWorkItem, account_id: str, cutoff: datetime, now: datetime
    ) -> tuple[ForYouEntry | None, bool, bool]:
        offset = 0
        latest: datetime | None = None
        incomplete = False
        while offset < self.config.comments_per_item:
            response = await self.api.get_comments(
                item.key, offset=offset, limit=min(100, self.config.comments_per_item - offset)
            )
            if not response.success:
                return (ForYouEntry(item, latest) if latest else None), True, True
            page = cast(PaginatedWorkItemComments, response.result)
            remaining = self.config.comments_per_item - offset
            for comment in page.comments[:remaining]:
                timestamps = [
                    _utc(value) for value in (comment.created, comment.updated) if value is not None
                ]
                activity = max(timestamps) if timestamps else None
                if (
                    activity is not None
                    and cutoff <= activity <= now
                    and contains_mention(comment.body, account_id)
                ):
                    latest = max(latest, activity) if latest else activity
            offset += len(page.comments)
            incomplete = not page.is_last or len(page.comments) > remaining
            if page.is_last or not page.comments:
                break
        return (ForYouEntry(item, latest) if latest else None), incomplete, False
