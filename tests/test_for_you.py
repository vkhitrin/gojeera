import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast
from unittest.mock import AsyncMock, Mock

from pydantic import ValidationError
import pytest
from textual.widgets import TabPane

from gojeera.components.screens.for_you_screen import ForYouScreen
from gojeera.internal.jira.controller import APIController, APIControllerResponse
from gojeera.internal.jira.for_you import ForYouService, contains_mention
from gojeera.internal.models.jira import JiraUser, WorkItemStatus
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    JiraWorkItemSearchResponse,
    PaginatedWorkItemComments,
    WorkItemComment,
)
from gojeera.internal.store.config import ForYouConfig
from gojeera.widgets.layout.extended_table import ExtendedTable
from gojeera.widgets.navigation.extended_jumper import ExtendedJumper
from gojeera.widgets.navigation.extended_tabbed_content import ExtendedTabbedContent

from .test_helpers import wait_until

NOW = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)
USER = JiraUser(account_id='me', active=True, display_name='Me')


def item(key='ENG-1'):
    return JiraWorkItem(
        id=key,
        key=key,
        summary='A [literal] summary',
        status=WorkItemStatus(id='1', name='Open'),
        updated=NOW,
    )


def mention(account_id='me'):
    return {
        'type': 'doc',
        'content': [
            {'type': 'paragraph', 'content': [{'type': 'mention', 'attrs': {'id': account_id}}]}
        ],
    }


def comment(body=None, created=NOW, updated=None):
    return WorkItemComment(id='1', author=USER, body=body, created=created, updated=updated)


def search_page(items, token=None):
    return APIControllerResponse(
        result=JiraWorkItemSearchResponse(
            work_items=items,
            next_page_token=token,
            is_last=token is None,
        )
    )


def comments_page(comments, offset=0, total=None):
    return APIControllerResponse(
        result=PaginatedWorkItemComments(
            comments=comments,
            start_at=offset,
            max_results=len(comments),
            total=len(comments) if total is None else total,
        )
    )


def service(config=None):
    api = Mock(spec=APIController)
    api.search_work_items = AsyncMock(return_value=search_page([item()]))
    api.get_comments = AsyncMock(return_value=comments_page([]))
    return ForYouService(cast(APIController, api), config or ForYouConfig()), api


@pytest.mark.parametrize(
    'body,expected',
    [
        (mention(), True),
        (mention('someone-else'), False),
        ('@Me me', False),
        ({'type': 'text', 'text': 'me'}, False),
        ({'type': 'mention', 'attrs': None}, False),
        (None, False),
    ],
)
def test_only_actual_account_id_mentions_match(body, expected):
    assert contains_mention(body, 'me') is expected


@pytest.mark.parametrize(
    'field,maximum',
    [
        ('due_soon_days', 365),
        ('recent_days', 365),
        ('items_per_section', 200),
        ('mention_scan_items', 200),
        ('comments_per_item', 500),
    ],
)
def test_configuration_bounds(field, maximum):
    for invalid in (0, -1, maximum + 1):
        with pytest.raises(ValidationError):
            ForYouConfig(**{field: invalid})
    assert getattr(ForYouConfig(**{field: maximum}), field) == maximum


@pytest.mark.asyncio
async def test_due_and_updated_queries_use_personal_scope_and_configured_windows():
    feed, api = service(ForYouConfig(due_soon_days=3, recent_days=2))
    due = await feed.load('due', 'me')
    jql = api.search_work_items.call_args.kwargs['jql_query']
    assert 'assignee = currentUser()' in jql
    assert 'statusCategory != Done' in jql
    assert 'duedate <= endOfDay("+3d")' in jql
    assert 'duedate >=' not in jql  # Include overdue items, not just future dates.
    assert len(due.entries) == 1
    updated = await feed.load('updated', 'me')
    assert api.search_work_items.call_args.kwargs['jql_query'] == (
        '(assignee = currentUser() OR watcher = currentUser()) '
        'AND updated >= -2d ORDER BY updated DESC'
    )
    assert updated.entries[0].activity_at == NOW


@pytest.mark.asyncio
async def test_search_paginates_deduplicates_and_reports_truncation():
    feed, api = service(ForYouConfig(items_per_section=2))
    api.search_work_items = AsyncMock(
        side_effect=[
            search_page([item()], 'page-2'),
            search_page([item(), item('ENG-2')], 'page-3'),
        ]
    )
    result = await feed.load('updated', 'me')
    assert [entry.work_item.key for entry in result.entries] == ['ENG-1', 'ENG-2']
    assert 'more may exist' in result.note
    assert result.limited
    assert result.error is None
    assert api.search_work_items.call_count == 2
    assert api.search_work_items.call_args.kwargs['next_page_token'] == 'page-2'
    assert api.search_work_items.call_args.kwargs['limit'] == 1


@pytest.mark.asyncio
async def test_search_stops_repeating_page_tokens():
    feed, api = service()
    api.search_work_items.return_value = search_page([item()], 'same')
    result = await feed.load('due', 'me')
    assert len(result.entries) == 1
    assert api.search_work_items.call_count == 2
    assert 'more may exist' in result.note


@pytest.mark.asyncio
async def test_mentions_verify_comment_dates_paginate_and_deduplicate():
    feed, api = service(ForYouConfig(comments_per_item=4))
    old = NOW - timedelta(days=30)
    api.get_comments = AsyncMock(
        side_effect=[
            comments_page(
                [
                    comment(mention('someone-else')),
                    comment(mention(), created=old),
                ],
                total=4,
            ),
            comments_page(
                [
                    comment(mention(), created=old, updated=NOW - timedelta(hours=1)),
                    comment(mention(), created=NOW - timedelta(days=7)),
                ],
                offset=2,
                total=4,
            ),
        ]
    )
    result = await feed.load('mentions', 'me', now=NOW)
    assert len(result.entries) == 1
    assert result.entries[0].activity_at == NOW - timedelta(hours=1)
    assert api.get_comments.call_args.kwargs == {'offset': 2, 'limit': 2}
    assert api.search_work_items.call_args.kwargs['jql_query'] == (
        'updated >= -7d AND comment ~ "\\"me\\"" ORDER BY updated DESC'
    )
    api.search_work_items.assert_awaited_once()
    assert 'Best effort' in result.note
    assert 'edit does not prove' in result.note


@pytest.mark.asyncio
async def test_mentions_limits_partial_failures_sorting_and_timezone():
    feed, api = service(ForYouConfig(mention_scan_items=3, comments_per_item=1))
    api.search_work_items.return_value = search_page(
        [item('ENG-1'), item('ENG-2'), item('ENG-3')], 'more'
    )

    async def get_comments(key, **kwargs):
        assert kwargs['limit'] == 1
        if key == 'ENG-2':
            return APIControllerResponse(success=False, error='Forbidden')
        timestamp = NOW if key == 'ENG-3' else NOW - timedelta(days=1)
        timestamp = timestamp.astimezone(timezone(timedelta(hours=3)))
        return comments_page([comment(mention(), created=timestamp)], total=5)

    api.get_comments = AsyncMock(side_effect=get_comments)
    result = await feed.load('mentions', 'me', now=NOW)
    assert [entry.work_item.key for entry in result.entries] == ['ENG-3', 'ENG-1']
    assert result.entries[0].activity_at == NOW
    assert 'Item scan limit reached' in result.note
    assert 'Comment scan incomplete for 3 items' in result.note
    assert 'Comments unavailable for 1 items' in result.note
    assert result.limited
    assert result.failed_comment_items == 1
    assert api.get_comments.call_count == 3


@pytest.mark.asyncio
async def test_mentions_missing_identity_empty_results_and_search_errors():
    feed, api = service()
    result = await feed.load('mentions', None, now=NOW)
    assert 'current user is not loaded' in result.note
    assert result.error == 'Current user is not loaded.'
    api.search_work_items.assert_not_called()
    result = await feed.load('mentions', 'me', now=NOW)
    assert 'No verified mentions' in result.note
    api.search_work_items.return_value = search_page([])
    assert 'No matching work items' in (await feed.load('due', 'me')).note
    api.search_work_items.return_value = APIControllerResponse(success=False, error='Forbidden')
    failed = await feed.load('updated', 'me')
    assert 'Forbidden' in failed.note
    assert failed.error == 'Forbidden'


@pytest.mark.asyncio
async def test_mentions_scan_only_targeted_candidates_for_seven_hour_old_match():
    feed, api = service(ForYouConfig(mention_scan_items=2))
    account_id = '712020:abcd-1234'
    mentioned_at = NOW - timedelta(hours=7)

    async def search(**kwargs):
        if 'comment ~' in kwargs['jql_query']:
            assert kwargs['jql_query'] == (
                'updated >= -7d AND comment ~ "\\"712020:abcd-1234\\"" ORDER BY updated DESC'
            )
            return search_page([item('ENG-MENTION')])
        # The mentioned issue is outside the broad scan's first page.
        return search_page([item('ENG-RECENT-1'), item('ENG-RECENT-2')], 'more')

    async def get_comments(key, **kwargs):
        comments = (
            [comment(mention(account_id), created=mentioned_at)] if key == 'ENG-MENTION' else []
        )
        return comments_page(comments)

    api.search_work_items = AsyncMock(side_effect=search)
    api.get_comments = AsyncMock(side_effect=get_comments)
    result = await feed.load('mentions', account_id, now=NOW)
    assert [entry.work_item.key for entry in result.entries] == ['ENG-MENTION']
    assert result.entries[0].activity_at == mentioned_at
    api.search_work_items.assert_awaited_once()
    api.get_comments.assert_awaited_once_with('ENG-MENTION', offset=0, limit=100)
    assert 'scanned 1/1 account-ID search candidates' in result.note
    assert 'Item scan limit reached' not in result.note


@pytest.mark.asyncio
@pytest.mark.parametrize('unavailable', [True, False])
async def test_mentions_never_fall_back_when_comment_index_is_unavailable_or_empty(unavailable):
    feed, api = service()
    api.search_work_items = AsyncMock(
        side_effect=[
            APIControllerResponse(success=False, error='Unsupported search')
            if unavailable
            else search_page([]),
            search_page([item()]),
        ]
    )
    api.get_comments = AsyncMock(
        return_value=comments_page(
            [
                comment(mention(), created=NOW - timedelta(hours=7)),
            ]
        )
    )
    result = await feed.load('mentions', 'me', now=NOW)
    assert not result.entries
    api.search_work_items.assert_awaited_once()
    api.get_comments.assert_not_awaited()
    if unavailable:
        assert 'Unable to load this section: Unsupported search' in result.note
    else:
        assert 'No account-ID comment-search candidates found' in result.note


@pytest.mark.asyncio
async def test_comment_index_candidates_still_require_recent_adf_mentions():
    feed, api = service()
    api.search_work_items.return_value = search_page([item()])
    api.get_comments.return_value = comments_page(
        [
            comment('me'),
            comment(mention('someone-else')),
            comment(mention(), created=NOW - timedelta(days=8)),
        ]
    )
    result = await feed.load('mentions', 'me', now=NOW)
    assert not result.entries
    assert 'No verified mentions' in result.note
    api.search_work_items.assert_awaited_once()
    assert api.get_comments.await_count == 1


@pytest.mark.asyncio
async def test_mentions_paginate_only_targeted_candidates_with_configured_window():
    feed, api = service(ForYouConfig(mention_scan_items=2, recent_days=2))
    api.search_work_items = AsyncMock(
        side_effect=[
            search_page([item()], 'next'),
            search_page([item(), item('ENG-2')]),
        ]
    )
    api.get_comments.return_value = comments_page([comment(mention())])
    result = await feed.load('mentions', 'me', now=NOW)
    assert [entry.work_item.key for entry in result.entries] == ['ENG-1', 'ENG-2']
    assert api.search_work_items.await_count == 2
    for call in api.search_work_items.await_args_list:
        assert call.kwargs['jql_query'] == (
            'updated >= -2d AND comment ~ "\\"me\\"" ORDER BY updated DESC'
        )
    assert api.search_work_items.call_args.kwargs['next_page_token'] == 'next'
    assert api.get_comments.await_count == 2
    assert 'Item scan limit reached' not in result.note


@pytest.mark.asyncio
@pytest.mark.parametrize('has_mention', [True, False])
async def test_mentions_render_without_tab_tooltips(jira_app, monkeypatch, has_mention):
    now = datetime.now(timezone.utc)
    account_id = jira_app.atlassian_context.user_info.account_id
    raw_comment = {
        'id': '1',
        'author': {'accountId': account_id, 'displayName': 'Me', 'active': True},
        'body': mention(account_id),
        'created': (now - timedelta(hours=7)).isoformat(),
        'updated': (now - timedelta(hours=7)).isoformat(),
    }
    # Exercise controller parsing rather than manufacturing a parsed ADF comment.
    parsed = jira_app.api._build_work_item_comments(
        {
            'comments': [raw_comment] if has_mention else [],
            'startAt': 0,
            'total': 1 if has_mention else 0,
        }
    )
    monkeypatch.setattr(
        jira_app.api, 'search_work_items', AsyncMock(return_value=search_page([item()]))
    )
    monkeypatch.setattr(
        jira_app.api, 'get_comments', AsyncMock(return_value=APIControllerResponse(result=parsed))
    )
    async with jira_app.run_test(size=(100, 30)) as pilot:
        await jira_app.action_show_for_you()
        screen = jira_app.screen
        await wait_until(lambda: not screen.query_one('#for-you-mentions', TabPane).loading)
        await pilot.pause()
        await pilot.press(']', ']')
        await pilot.pause()
        assert screen.query_one(ExtendedTabbedContent).active == 'for-you-mentions'
        table = screen.query_one('#mentions-table', ExtendedTable)
        assert table.row_count == int(has_mention)
        assert screen.query_one(ExtendedTabbedContent).get_tab('for-you-mentions').tooltip is None
        await pilot.press('escape')


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed():
    feed, api = service()
    api.get_comments = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await feed.load('mentions', 'me', now=NOW)


@pytest.mark.asyncio
async def test_modal_command_palette_refresh_open_and_close(jira_app, monkeypatch):
    app = jira_app
    search = AsyncMock(return_value=search_page([item()]))
    monkeypatch.setattr(app.api, 'search_work_items', search)
    monkeypatch.setattr(app.api, 'get_comments', AsyncMock(return_value=comments_page([])))
    load = AsyncMock()
    monkeypatch.setattr(app, 'load_work_item', load)

    async with app.run_test(size=(120, 40)) as pilot:
        app.action_command_palette()
        await pilot.pause()
        await pilot.press(*'For You')
        await pilot.pause()
        await pilot.press('enter')
        await wait_until(lambda: isinstance(app.screen, ForYouScreen))
        screen = app.screen
        await wait_until(lambda: screen.query_one('#due-table', ExtendedTable).row_count == 1)
        table = screen.query_one('#due-table', ExtendedTable)
        assert table.region.height > 0
        assert table.get_row_at(0)[1].plain == 'A [literal] summary'
        await app.action_show_for_you()
        assert app.screen is screen  # Exclusive modal guard.
        calls = search.call_count
        await pilot.press('ctrl+r')
        await wait_until(lambda: search.call_count >= calls + 3)
        await wait_until(lambda: table.row_count == 1)
        table.focus()
        await pilot.press('enter')
        await wait_until(lambda: load.await_count == 1)
        load.assert_awaited_once_with('ENG-1')
        assert not isinstance(app.screen, ForYouScreen)
        await app.action_show_for_you()
        await pilot.pause()
        await pilot.press('escape')
        assert not isinstance(app.screen, ForYouScreen)


@pytest.mark.asyncio
async def test_modal_renders_other_sections_while_mentions_load_and_cancels_on_close(
    jira_app,
    monkeypatch,
):
    app = jira_app
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def get_comments(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(app.api, 'search_work_items', AsyncMock(return_value=search_page([item()])))
    monkeypatch.setattr(app.api, 'get_comments', get_comments)
    async with app.run_test(size=(100, 30)) as pilot:
        await app.action_show_for_you()
        screen = app.screen
        await wait_until(started.is_set)
        assert screen.query_one('#due-table', ExtendedTable).row_count == 1
        assert not screen.query_one('#for-you-due', TabPane).loading
        assert screen.query_one('#for-you-mentions', TabPane).loading
        assert screen.query_one(ExtendedTabbedContent).get_tab('for-you-mentions').tooltip is None
        await pilot.pause()
        screen.query_one(ExtendedTabbedContent).active = 'for-you-updated'
        await pilot.pause()
        assert screen.query_one('#updated-table', ExtendedTable).region.height > 0
        await pilot.press('escape')
        await wait_until(cancelled.is_set)


@pytest.mark.asyncio
@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('theme', ['textual-dark', 'textual-light'])
async def test_modal_loading_resets_after_results_or_errors(jira_app, monkeypatch, success, theme):
    jira_app.theme = theme
    release = asyncio.Event()

    async def search(**kwargs):
        await release.wait()
        return (
            search_page([]) if success else APIControllerResponse(success=False, error='Forbidden')
        )

    monkeypatch.setattr(jira_app.api, 'search_work_items', search)
    async with jira_app.run_test(size=(100, 30)) as pilot:
        await jira_app.action_show_for_you()
        screen = jira_app.screen
        await pilot.pause()
        panes = list(screen.query(TabPane))
        assert all(pane.loading for pane in panes)
        modal_background = screen.query_one('#modal_outer').styles.background
        for pane in panes:
            indicator = pane._cover_widget
            assert indicator is not None
            assert indicator.styles.background == modal_background
        release.set()
        await wait_until(lambda: all(not pane.loading for pane in panes))
        tabs = screen.query_one(ExtendedTabbedContent)
        for pane in panes:
            assert list(pane.children) == [pane.query_one(ExtendedTable)]
            assert tabs.get_tab(pane).tooltip is None
        release.clear()
        await pilot.press('ctrl+r')
        assert all(pane.loading for pane in panes)
        assert all(tabs.get_tab(pane).tooltip is None for pane in panes)
        await pilot.press(']')
        assert screen.query_one(ExtendedTabbedContent).active == 'for-you-updated'
        await pilot.press('[')
        assert screen.query_one(ExtendedTabbedContent).active == 'for-you-due'
        await pilot.press('escape')


@pytest.mark.asyncio
@pytest.mark.parametrize('jumper_enabled', [True, False])
async def test_modal_extended_tabs_support_brackets_and_jumping(
    jira_app,
    monkeypatch,
    jumper_enabled,
):
    jira_app.config.jumper.enabled = jumper_enabled
    monkeypatch.setattr(jira_app.api, 'search_work_items', AsyncMock(return_value=search_page([])))
    async with jira_app.run_test(size=(120, 40)) as pilot:
        workspace_tab = jira_app.tabs.active
        await jira_app.action_show_for_you()
        screen = jira_app.screen
        await wait_until(lambda: all(not pane.loading for pane in screen.query(TabPane)))
        await pilot.pause()
        tabs = screen.query_one(ExtendedTabbedContent)
        screen.query_one('#due-table', ExtendedTable).focus()
        for key, section in [
            ('[', 'due'),
            (']', 'updated'),
            (']', 'mentions'),
            (']', 'mentions'),
            ('[', 'updated'),
            ('[', 'due'),
        ]:
            await pilot.press(key)
            await pilot.pause()
            assert tabs.active == f'for-you-{section}'
            assert screen.query_one(f'#{section}-table', ExtendedTable).has_focus
            assert jira_app.tabs.active == workspace_tab

        tabs.tabs_widget.focus()
        await pilot.press(']')
        await pilot.pause()
        assert tabs.active == 'for-you-updated'
        assert tabs.tabs_widget.has_focus

        if jumper_enabled:
            overlays = screen.query_one(ExtendedJumper).get_overlays()
            targets = {info.widget: info for info in overlays.values()}
            for section in ('due', 'updated', 'mentions'):
                assert targets[tabs.get_tab(f'for-you-{section}')].jump_mode == 'click'
            mention_key = targets[tabs.get_tab('for-you-mentions')].key
            await pilot.press('ctrl+backslash')
            await pilot.press(*mention_key)
            await pilot.pause()
            assert jira_app.screen is screen
            assert tabs.active == 'for-you-mentions'
        else:
            assert not list(screen.query(ExtendedJumper))
        await pilot.press('escape')
