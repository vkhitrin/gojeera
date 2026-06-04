from httpx import Response
import respx

from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget

from .conftest import load_fixture
from .test_helpers import assert_snapshot_matches, focus_work_item_tab, wait_until


def mock_work_item_changelog_pages(work_item_key: str = 'ENG-3') -> None:
    changelog_pages = load_fixture('jira_work_item_changelog_pages.json')
    respx.get(
        url__regex=rf'https://example\.atlassian\.acme\.net/rest/api/3/issue/{work_item_key}/changelog.*'
    ).mock(side_effect=[Response(200, json=page) for page in changelog_pages])


async def open_work_item_history(pilot) -> WorkItemHistoryWidget:
    mock_work_item_changelog_pages()

    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=6)

    history_widget = pilot.app.screen.query_one(WorkItemHistoryWidget)
    await wait_until(lambda: history_widget.displayed_count == 3, timeout=3.0)
    return history_widget


async def open_work_item_history_initial_state(pilot):
    await open_work_item_history(pilot)
    await pilot.pause()


async def select_work_item_and_highlight_history(pilot):
    history_widget = await open_work_item_history(pilot)

    history_widget.record_list.focus()
    await pilot.pause()


INITIAL_STATE = open_work_item_history_initial_state
HIGHLIGHT = select_work_item_and_highlight_history


class TestWorkItemHistory:
    def test_work_item_history_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, INITIAL_STATE)

    def test_work_item_history_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, HIGHLIGHT)
