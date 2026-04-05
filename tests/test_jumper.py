import asyncio

from gojeera.app import JiraApp

from .test_helpers import wait_for_mount


async def open_loaded_work_item_and_show_jumper(pilot):
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)

    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    await pilot.press('ctrl+backslash')
    await asyncio.sleep(0.3)


class TestJumper:
    def test_main_screen_jumper_overlay(
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
            run_before=open_loaded_work_item_and_show_jumper,
        )
