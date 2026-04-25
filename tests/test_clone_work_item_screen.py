import asyncio

from gojeera.app import JiraApp

from .test_helpers import open_clone_work_item_screen as open_clone_work_item_screen_helper


async def open_clone_work_item_screen_snapshot(pilot):
    await open_clone_work_item_screen_helper(pilot)


async def open_and_clear_summary(pilot):
    await open_clone_work_item_screen_helper(pilot)

    summary_input = pilot.app.screen.summary_input
    summary_input.value = ''
    await asyncio.sleep(0.3)

    assert summary_input.value == ''
    assert pilot.app.screen.clone_button.disabled


async def open_and_modify_summary(pilot):
    await open_clone_work_item_screen_helper(pilot)

    summary_input = pilot.app.screen.summary_input
    summary_input.value = 'New custom summary for cloned work item'
    await asyncio.sleep(0.3)

    assert not pilot.app.screen.clone_button.disabled


def with_clone_work_item_snapshot(run_before):
    def decorator(_):
        def wrapper(self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info):
            app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
            assert snap_compare(app, terminal_size=(120, 40), run_before=run_before)

        return wrapper

    return decorator


class TestCloneWorkItemScreen:
    """Snapshot tests to verify clone work item screen display and interactions."""

    @with_clone_work_item_snapshot(open_clone_work_item_screen_snapshot)
    def test_clone_work_item_screen_initial_state(self): ...

    @with_clone_work_item_snapshot(open_and_clear_summary)
    def test_clone_work_item_screen_with_empty_summary(self): ...

    @with_clone_work_item_snapshot(open_and_modify_summary)
    def test_clone_work_item_screen_with_modified_summary(self): ...
