import asyncio

from gojeera.app import JiraApp
from gojeera.components.quick_navigation_screen import QuickNavigationScreen


async def open_quick_navigation_screen(pilot):
    screen = QuickNavigationScreen()
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, QuickNavigationScreen)
    assert pilot.app.screen.work_item_key_input.has_focus
    assert pilot.app.screen.open_button.disabled


async def quick_navigation_load_valid_work_item(pilot):
    await open_quick_navigation_screen(pilot)

    await pilot.press(*'EXAMPLE-19539')
    await asyncio.sleep(0.2)

    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    main_screen = pilot.app.screen
    assert main_screen.current_loaded_work_item_key == 'EXAMPLE-19539'
    assert main_screen.information_panel.work_item is not None
    assert main_screen.information_panel.work_item.key == 'EXAMPLE-19539'


class TestQuickNavigationScreen:
    def test_quick_navigation_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_quick_navigation_screen,
        )

    def test_quick_navigation_loads_valid_work_item(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=quick_navigation_load_valid_work_item,
        )
