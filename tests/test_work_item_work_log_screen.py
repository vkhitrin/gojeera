import asyncio

from httpx import Response
import pytest
import respx
from textual.widgets import Button

from gojeera.app import JiraApp
from gojeera.components.confirmation_screen import ConfirmationScreen
from gojeera.components.work_item_work_log_screen import (
    WorkItemWorkLogScreen,
    WorkLogListItem,
    WorkLogListView,
)


async def open_worklog_screen(pilot):
    screen = WorkItemWorkLogScreen(work_item_key='ENG-3')
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)
    assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)


async def delete_worklog_and_verify(pilot):
    screen = WorkItemWorkLogScreen(work_item_key='ENG-3')
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)

    list_view = pilot.app.screen.worklog_list_view
    initial_count = len(list_view.query(WorkLogListItem))

    assert initial_count > 0, 'Should have at least one worklog to delete'

    list_view.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+d')
    await asyncio.sleep(0.5)

    screen_after_delete = pilot.app.screen
    assert isinstance(screen_after_delete, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen_after_delete)}'
    )

    screen_after_delete.query_one('#confirmation-button-accept', Button).press()
    await asyncio.sleep(1.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(1.0)

    assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)
    list_view = pilot.app.screen.worklog_list_view
    new_count = len(list_view.query(WorkLogListItem))
    assert new_count == initial_count - 1, f'Expected {initial_count - 1} worklogs, got {new_count}'


class TestWorkItemWorkLogScreen:
    @pytest.mark.asyncio
    async def test_worklog_screen_empty_worklogs(
        self, mock_configuration, mock_user_info, mock_jira_worklog_empty
    ):

        async def run_test(pilot):
            screen = WorkItemWorkLogScreen(work_item_key='ENG-2')
            await pilot.app.push_screen(screen)
            await asyncio.sleep(0.3)

            await pilot.app.workers.wait_for_complete()
            await asyncio.sleep(0.3)

            assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)

            list_view = pilot.app.screen.worklog_list_view
            assert isinstance(list_view, WorkLogListView)
            assert len(list_view.query(WorkLogListItem)) == 0

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with respx.mock:
            worklog_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/issue/ENG-2/worklog'
            )
            worklog_route.mock(return_value=Response(200, json=mock_jira_worklog_empty))

            async with app.run_test() as pilot:
                await run_test(pilot)

    def test_worklog_screen_initial_state(
        self, snap_compare, mock_configuration, mock_user_info, mock_jira_worklog
    ):
        """Test worklog screen initial state snapshot."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        with respx.mock:
            worklog_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog'
            )
            worklog_route.mock(return_value=Response(200, json=mock_jira_worklog))

            assert snap_compare(app, terminal_size=(120, 40), run_before=open_worklog_screen)

    def test_delete_worklog_and_verify_in_list(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_worklog_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_worklog_and_verify)
