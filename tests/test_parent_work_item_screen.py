import asyncio

from gojeera.app import JiraApp
from gojeera.components.parent_work_item_screen import ParentWorkItemScreen


async def open_parent_work_item_screen(pilot):
    await pilot.app.screen.fetch_work_items('ENG-3')
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)

    work_item = pilot.app.screen.information_panel.work_item
    assert work_item is not None

    await pilot.app.push_screen(ParentWorkItemScreen(work_item=work_item))
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, ParentWorkItemScreen)
    assert pilot.app.screen.parent_input.has_focus
    assert pilot.app.screen.apply_button.disabled


async def select_parent_work_item_and_enable_set(pilot):
    await open_parent_work_item_screen(pilot)

    parent_input = pilot.app.screen.parent_input
    parent_input.value = ''
    await asyncio.sleep(0.2)
    await pilot.press(*'ENG-9')
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, ParentWorkItemScreen)
    assert not pilot.app.screen.apply_button.disabled


class TestParentWorkItemScreen:
    def test_parent_work_item_screen_initial_state(
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
            run_before=open_parent_work_item_screen,
        )

    def test_parent_work_item_screen_with_selected_parent(
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
            run_before=select_parent_work_item_and_enable_set,
        )
