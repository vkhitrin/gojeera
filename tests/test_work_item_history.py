from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

from httpx import Response
import pytest
import respx

from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraProjectFeature
from gojeera.internal.models.work_items import PaginatedWorkItemHistory, WorkItemHistoryEntry

from .conftest import load_fixture
from .test_helpers import assert_snapshot_matches, focus_work_item_tab, wait_until


def mock_work_item_changelog_pages(work_item_key: str = 'ENG-3') -> None:
    changelog_pages = load_fixture('jira_work_item_changelog_pages.json')
    respx.get(
        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{work_item_key}/changelog.*'
    ).mock(side_effect=[Response(200, json=page) for page in changelog_pages])


async def test_history_fetches_one_page_at_a_time(monkeypatch) -> None:
    class TrackingHistoryWidget(WorkItemHistoryWidget):
        def __init__(self):
            super().__init__()
            self.published_histories: list[list[WorkItemHistoryEntry] | None] = []
            self.append_records = Mock()

        @property
        def table(self):
            return SimpleNamespace(append_records=self.append_records)

        def watch_history(self, history: list[WorkItemHistoryEntry] | None) -> None:
            self.published_histories.append(list(history) if history is not None else None)

        def watch_work_item_key(self, work_item_key: str | None = None) -> None:
            pass

        def watch_is_loading(self, loading: bool) -> None:
            pass

    entries = [
        WorkItemHistoryEntry(id='1', created=datetime(2026, 1, 3, tzinfo=timezone.utc)),
        WorkItemHistoryEntry(id='2', created=datetime(2026, 1, 2, tzinfo=timezone.utc)),
        WorkItemHistoryEntry(id='3', created=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    get_history = AsyncMock(
        side_effect=[
            APIControllerResponse(
                result=PaginatedWorkItemHistory(
                    entries=[entries[0]], max_results=1, start_at=0, is_last=False
                )
            ),
            APIControllerResponse(
                result=PaginatedWorkItemHistory(
                    entries=[entries[1]], max_results=1, start_at=1, is_last=False
                )
            ),
            APIControllerResponse(
                result=PaginatedWorkItemHistory(
                    entries=[entries[2]], max_results=1, start_at=2, is_last=True
                )
            ),
        ]
    )
    mark_count_loaded = Mock()
    fake_app = SimpleNamespace(
        api=SimpleNamespace(get_work_item_history=get_history),
        mark_detail_tab_count_loaded=mark_count_loaded,
    )
    monkeypatch.setattr(
        TrackingHistoryWidget,
        'app',
        property(lambda self: fake_app),
    )
    widget = TrackingHistoryWidget()
    widget.work_item_key = 'ENG-1'
    widget.published_histories.clear()

    await widget.fetch_history('ENG-1')

    published_pages = [history for history in widget.published_histories if history is not None]
    assert len(published_pages) == 1
    assert [entry.id for entry in cast(list, published_pages[0])] == ['1']
    widget.append_records.assert_not_called()
    assert get_history.await_count == 1
    mark_count_loaded.assert_not_called()

    await widget.fetch_history('ENG-1')

    widget.append_records.assert_called_once()
    assert [record.key for record in widget.append_records.call_args.args[0]] == ['2']
    assert get_history.await_count == 2
    mark_count_loaded.assert_not_called()

    await widget.fetch_history('ENG-1')

    assert get_history.await_count == 3
    assert widget.append_records.call_count == 2
    assert [record.key for record in widget.append_records.call_args.args[0]] == ['3']
    assert len([history for history in widget.published_histories if history is not None]) == 1
    mark_count_loaded.assert_called_once_with('tab-history', 3)


async def test_history_failure_does_not_schedule_automatic_retry(monkeypatch) -> None:
    scheduled_callbacks: list[object] = []

    class FailingHistoryWidget(WorkItemHistoryWidget):
        @property
        def is_mounted(self) -> bool:
            return True

        def call_after_refresh(self, callback, *args) -> bool:
            del args
            scheduled_callbacks.append(callback)
            return True

        def hide_loading(self) -> None:
            pass

        def notify(self, *args, **kwargs) -> None:
            pass

        def watch_history(self, history: list[WorkItemHistoryEntry] | None) -> None:
            pass

        def watch_work_item_key(self, work_item_key: str | None = None) -> None:
            pass

        def watch_is_loading(self, loading: bool) -> None:
            pass

    get_history = AsyncMock(return_value=APIControllerResponse(success=False, error='offline'))
    fake_app = SimpleNamespace(api=SimpleNamespace(get_work_item_history=get_history))
    monkeypatch.setattr(
        FailingHistoryWidget,
        'app',
        property(lambda self: fake_app),
    )
    widget = FailingHistoryWidget()
    widget.work_item_key = 'ENG-1'

    await widget.fetch_history('ENG-1')

    get_history.assert_awaited_once_with('ENG-1', offset=0, limit=widget.PAGE_SIZE)
    assert scheduled_callbacks == []


async def open_work_item_history(pilot) -> WorkItemHistoryWidget:
    mock_work_item_changelog_pages()

    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=0)
    pilot.app.tabs.active = 'tab-history'
    await pilot.pause()

    history_widget = pilot.app.screen.query_one(WorkItemHistoryWidget)
    await wait_until(lambda: history_widget.displayed_count == 3, timeout=3.0)
    return history_widget


async def open_work_item_history_initial_state(pilot):
    await open_work_item_history(pilot)
    await pilot.pause()


async def select_work_item_and_highlight_history(pilot):
    history_widget = await open_work_item_history(pilot)

    history_widget.table.focus()
    await pilot.pause()


INITIAL_STATE = open_work_item_history_initial_state
HIGHLIGHT = select_work_item_and_highlight_history


def disable_development_features(application_cache) -> None:
    application_cache.set_project_features(
        'ENG',
        [
            JiraProjectFeature(
                project_key='ENG',
                feature='jsw.classic.code',
                state='DISABLED',
                localised_name='Code',
            )
        ],
    )


@pytest.fixture
def history_snapshot_context(
    snap_compare,
    application_cache,
    mock_configuration,
    mock_jira_api_with_search_results,
    mock_user_info,
):
    del mock_jira_api_with_search_results
    disable_development_features(application_cache)
    return snap_compare, mock_configuration, mock_user_info


class TestWorkItemHistory:
    def test_work_item_history_initial_state(self, history_snapshot_context):
        snap_compare, configuration, user_info = history_snapshot_context
        assert_snapshot_matches(snap_compare, configuration, user_info, INITIAL_STATE)

    def test_work_item_history_row_highlighted(self, history_snapshot_context):
        snap_compare, configuration, user_info = history_snapshot_context
        assert_snapshot_matches(snap_compare, configuration, user_info, HIGHLIGHT)
