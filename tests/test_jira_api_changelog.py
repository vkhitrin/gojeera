import pytest

from tests.conftest import load_fixture
from tests.jira_api_test_utils import build_api_with_mocked_client


@pytest.mark.asyncio
async def test_get_work_item_changelog_requests_page():
    changelog_pages = load_fixture('jira_work_item_changelog_pages.json')
    api, make_request = build_api_with_mocked_client([changelog_pages[1]])

    changelog = await api.get_work_item_changelog('ENG-1', offset=1, limit=100)

    assert changelog == changelog_pages[1]
    assert make_request.await_count == 1
    assert make_request.await_args_list[0].kwargs['url'] == 'issue/ENG-1/changelog'
    assert make_request.await_args_list[0].kwargs['params'] == {
        'maxResults': 100,
        'startAt': 1,
    }
