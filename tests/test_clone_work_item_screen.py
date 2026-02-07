import asyncio

from gojeera.app import JiraApp
from gojeera.components.clone_work_item_screen import CloneWorkItemScreen


async def open_clone_work_item_screen(pilot):
    work_item_key = 'EXAMPLE-1234'
    original_summary = 'Original Work Item Summary'

    # NOTE: (vkhitrin) we directly "enter" the screen without navigating
    #       the UI.
    screen = CloneWorkItemScreen(work_item_key=work_item_key, original_summary=original_summary)
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, CloneWorkItemScreen)
    assert pilot.app.screen.work_item_key == work_item_key
    assert pilot.app.screen.original_summary == original_summary


async def open_and_clear_summary(pilot):
    await open_clone_work_item_screen(pilot)

    summary_input = pilot.app.screen.summary_input
    summary_input.value = ''
    await asyncio.sleep(0.3)

    assert summary_input.value == ''
    assert pilot.app.screen.clone_button.disabled


async def open_and_modify_summary(pilot):
    await open_clone_work_item_screen(pilot)

    summary_input = pilot.app.screen.summary_input
    summary_input.value = 'New custom summary for cloned work item'
    await asyncio.sleep(0.3)

    assert not pilot.app.screen.clone_button.disabled


class TestCloneWorkItemScreen:
    """Snapshot tests to verify clone work item screen display and interactions."""

    def test_clone_work_item_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration
        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_clone_work_item_screen)

    def test_clone_work_item_screen_with_empty_summary(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration
        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_and_clear_summary)

    def test_clone_work_item_screen_with_modified_summary(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration
        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_and_modify_summary)
