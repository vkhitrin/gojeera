from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

from gojeera.app import COMMENTS_PAGE_SIZE
from gojeera.components.screens.work_item_work_log_screen import WorkItemWorkLogScreen
from gojeera.components.work_item.work_item_comments import (
    COMMENT_RENDER_BATCH_SIZE,
    WorkItemCommentsWidget,
)
from gojeera.components.work_item.work_item_fields import DYNAMIC_FIELD_MOUNT_BATCH_SIZE
from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
from gojeera.internal.jira.controller import (
    RECORDS_PER_PAGE_SEARCH_PROJECTS,
    APIController,
)
from gojeera.internal.models.work_items import PaginatedWorkItemComments


def test_interactive_loading_work_is_bounded() -> None:
    assert COMMENT_RENDER_BATCH_SIZE <= 20
    assert DYNAMIC_FIELD_MOUNT_BATCH_SIZE <= 6
    assert COMMENTS_PAGE_SIZE <= 50
    assert WorkItemHistoryWidget.PAGE_SIZE <= 100
    assert WorkItemWorkLogScreen.PAGE_SIZE <= 100
    assert RECORDS_PER_PAGE_SEARCH_PROJECTS <= 100


def test_comment_page_preserves_total_and_completion_state() -> None:
    controller = object.__new__(APIController)
    first_page = controller._build_work_item_comments(
        {
            'comments': [{'id': '1', 'author': {'accountId': 'user-1'}}],
            'startAt': 0,
            'maxResults': 1,
            'total': 2,
        }
    )
    last_page = controller._build_work_item_comments(
        {
            'comments': [{'id': '2', 'author': {'accountId': 'user-1'}}],
            'startAt': 1,
            'maxResults': 1,
            'total': 2,
        }
    )

    assert isinstance(first_page, PaginatedWorkItemComments)
    assert first_page.total == 2
    assert not first_page.is_last
    assert last_page.is_last


def test_comments_request_next_page_only_while_incomplete(monkeypatch) -> None:
    load_more = Mock()
    fake_app = SimpleNamespace(load_more_work_item_comments=load_more)
    monkeypatch.setattr(
        WorkItemCommentsWidget,
        'app',
        property(lambda self: fake_app),
    )
    widget = WorkItemCommentsWidget()
    widget.work_item_key = 'ENG-1'
    widget.pagination_complete = False

    widget.load_more_if_needed()
    widget.pagination_complete = True
    widget.load_more_if_needed()

    load_more.assert_called_once_with('ENG-1')


async def test_project_search_publishes_each_page_before_caching_complete_result() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def search_projects(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    'values': [
                        {
                            'id': '1',
                            'key': 'ONE',
                            'name': 'One',
                            'projectTypeKey': 'software',
                        }
                    ],
                    'isLast': False,
                }
            return {
                'values': [
                    {
                        'id': '2',
                        'key': 'TWO',
                        'name': 'Two',
                        'projectTypeKey': 'service_desk',
                    }
                ],
                'isLast': True,
            }

    class FakeCache:
        def __init__(self) -> None:
            self.cached_projects = None
            self.writes: list[list] = []

        def get_projects(self, *, allow_stale=False):
            return self.cached_projects

        def set_projects(self, projects):
            self.writes.append(list(projects))

    controller = object.__new__(APIController)
    fake_client = FakeClient()
    fake_cache = FakeCache()
    controller.client = cast(Any, fake_client)
    controller.cache = cast(Any, fake_cache)
    published: list[list[str]] = []

    response = await controller.search_projects(
        on_page=lambda projects: published.append([project.key for project in projects])
    )

    assert published == [['ONE'], ['ONE', 'TWO']]
    assert [[project.key for project in page] for page in fake_cache.writes] == [['ONE', 'TWO']]
    assert response.success
    assert isinstance(response.result, list)
    assert [project.key for project in response.result] == ['ONE', 'TWO']
