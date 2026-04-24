import asyncio

from gojeera.app import JiraApp


async def open_debug_screen(pilot):
    await asyncio.sleep(0.5)
    await pilot.press('f12')
    await asyncio.sleep(0.5)


async def open_debug_tab(pilot, tab_index: int):
    await open_debug_screen(pilot)
    for _ in range(tab_index):
        await pilot.press('right_square_bracket')
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.5)


async def open_debug_application_tab(pilot):
    await open_debug_tab(pilot, 0)


async def open_debug_configuration_tab(pilot):
    await open_debug_tab(pilot, 1)


async def open_debug_server_tab(pilot):
    await open_debug_tab(pilot, 2)


async def open_debug_user_tab(pilot):
    await open_debug_tab(pilot, 3)


async def open_debug_cache_tab(pilot):
    await open_debug_tab(pilot, 4)


class TestDebugScreen:
    def test_debug_screen_application_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_debug_application_tab)

    def test_debug_screen_configuration_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_debug_configuration_tab,
        )

    def test_debug_screen_server_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_debug_server_tab,
        )

    def test_debug_screen_user_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_debug_user_tab,
        )

    def test_debug_screen_cache_tab(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_debug_cache_tab,
        )
