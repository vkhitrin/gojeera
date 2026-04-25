import asyncio

from gojeera.app import JiraApp
from gojeera.components.screens.debug_screen import DebugInfoScreen
from gojeera.components.screens.help_screen import HelpScreen
from tests.test_helpers import with_snapshot_assertion_fixture


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


def with_debug_snapshot_assertion(run_before):
    return with_snapshot_assertion_fixture(
        run_before,
        fixture_name='mock_jira_api_sync',
    )


class TestDebugScreen:
    @with_debug_snapshot_assertion(open_debug_application_tab)
    def test_debug_screen_application_tab(self): ...

    @with_debug_snapshot_assertion(open_debug_configuration_tab)
    def test_debug_screen_configuration_tab(self): ...

    @with_debug_snapshot_assertion(open_debug_server_tab)
    def test_debug_screen_server_tab(self): ...

    @with_debug_snapshot_assertion(open_debug_user_tab)
    def test_debug_screen_user_tab(self): ...

    @with_debug_snapshot_assertion(open_debug_cache_tab)
    def test_debug_screen_cache_tab(self): ...

    async def test_debug_screen_is_globally_available_from_modal(
        self, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with app.run_test() as pilot:
            await pilot.app.push_screen(HelpScreen())
            await asyncio.sleep(0.2)

            assert isinstance(pilot.app.screen, HelpScreen)

            await pilot.press('f12')
            await asyncio.sleep(0.2)

            assert isinstance(pilot.app.screen, DebugInfoScreen)
            assert any(isinstance(screen, HelpScreen) for screen in pilot.app.screen_stack[:-1])
