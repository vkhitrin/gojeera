import asyncio

from gojeera.app import JiraApp

from .test_helpers import wait_for_mount


async def perform_default_search(pilot):
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)


async def perform_search_navigate_mixed(pilot):
    await perform_default_search(pilot)

    await pilot.press('j', 'j')
    await asyncio.sleep(0.2)

    await pilot.press('down')
    await asyncio.sleep(0.3)


async def perform_search_navigate_and_select(pilot):
    await perform_default_search(pilot)
    await pilot.press('down')
    await asyncio.sleep(0.2)
    await pilot.press('enter')
    await asyncio.sleep(0.5)


class TestWorkItemResult:
    def test_work_item_results_with_results(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=perform_default_search)

    def test_work_item_results_navigation(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=perform_search_navigate_mixed)

    def test_work_item_results_truncated_summary(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        config.search_results_truncate_work_item_summary = 50

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=perform_default_search)

    def test_work_item_results_search_on_startup(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        config.search_on_startup = True

        app = JiraApp(settings=config, user_info=mock_user_info, focus_item_on_startup=1)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_mount)
