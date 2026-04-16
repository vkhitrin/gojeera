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


async def perform_search_navigate_mixed_in_light_theme(pilot):
    pilot.app.theme = 'textual-light'
    await asyncio.sleep(0.2)
    await perform_search_navigate_mixed(pilot)


async def perform_search_navigate_mixed_then_switch_to_light_theme(pilot):
    await perform_search_navigate_mixed(pilot)
    pilot.app.theme = 'textual-light'
    await asyncio.sleep(0.3)


async def perform_search_navigate_mixed_then_switch_to_dark_theme(pilot):
    pilot.app.theme = 'textual-light'
    await asyncio.sleep(0.2)
    await perform_search_navigate_mixed(pilot)
    pilot.app.theme = 'textual-dark'
    await asyncio.sleep(0.3)


class TestWorkItemResult:
    def test_work_item_results_navigation(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=perform_search_navigate_mixed)

    def test_work_item_results_navigation_light_theme(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration
        config.theme = 'textual-light'

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=perform_search_navigate_mixed_in_light_theme,
        )

    def test_work_item_results_navigation_start_with_dark_theme_switch_theme_to_light(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=perform_search_navigate_mixed_then_switch_to_light_theme,
        )

    def test_work_item_results_navigation_start_with_light_theme_switch_theme_to_dark(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=perform_search_navigate_mixed_then_switch_to_dark_theme,
        )

    def test_work_item_results_search_on_startup(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        config = mock_configuration

        config.search_on_startup = True

        app = JiraApp(settings=config, user_info=mock_user_info, focus_item_on_startup=1)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_mount)
