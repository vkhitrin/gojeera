import asyncio
from typing import Any, cast

from httpx import Response
import pytest
import respx

from gojeera.app import JiraApp
from gojeera.components.screens.work_item_work_log_screen import WorkItemWorkLogScreen
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.work_items import JiraWorklog, PaginatedJiraWorklog
from gojeera.widgets.layout.record_list import RecordList

from .test_helpers import accept_confirmation, assert_confirmation_screen, wait_until


async def show_worklog_screen(
    pilot,
    *,
    work_item_key: str = 'ENG-3',
) -> WorkItemWorkLogScreen:
    screen = WorkItemWorkLogScreen(work_item_key=work_item_key)
    await pilot.app.push_screen(screen)
    await wait_until(lambda: isinstance(pilot.app.screen, WorkItemWorkLogScreen), timeout=3.0)
    await wait_until(lambda: not pilot.app.screen.is_loading, timeout=3.0)
    await wait_until(
        lambda: (
            len(pilot.app.screen.worklog_list_view._records) > 0
            or pilot.app.screen.worklog_list_view.is_mounted
        ),
        timeout=3.0,
    )
    pilot.app.screen.set_focus(pilot.app.screen.worklog_list_view)
    await wait_until(
        lambda: pilot.app.focused is pilot.app.screen.worklog_list_view,
        timeout=3.0,
    )
    await wait_until(
        lambda: pilot.app.screen.worklog_list_view.selected_record is not None,
        timeout=3.0,
    )
    await pilot.pause()
    assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)
    return pilot.app.screen


async def open_worklog_screen(pilot):
    await show_worklog_screen(pilot)


async def delete_worklog_and_verify(pilot):
    await show_worklog_screen(pilot)

    list_view = pilot.app.screen.worklog_list_view
    initial_count = len(list_view._records)

    assert initial_count > 0, 'Should have at least one worklog to delete'

    list_view.focus()
    await pilot.pause()

    await pilot.press('ctrl+d')
    await wait_until(lambda: assert_confirmation_screen(pilot.app.screen), timeout=3.0)
    await accept_confirmation(pilot)
    await wait_until(lambda: isinstance(pilot.app.screen, WorkItemWorkLogScreen), timeout=3.0)
    await wait_until(lambda: not pilot.app.screen.is_loading, timeout=3.0)

    assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)
    list_view = pilot.app.screen.worklog_list_view
    await wait_until(lambda: len(list_view._records) == initial_count - 1, timeout=3.0)
    new_count = len(list_view._records)
    assert new_count == initial_count - 1, f'Expected {initial_count - 1} worklogs, got {new_count}'


class TestWorkItemWorkLogScreen:
    @pytest.mark.asyncio
    async def test_worklog_screen_reuses_probe_and_appends_the_next_page(
        self,
        search_results_app,
    ):
        app = search_results_app
        release_page = asyncio.Event()
        requested_pages: list[tuple[int | None, int | None]] = []

        async def get_work_item_worklog(
            work_item_key: str,
            offset: int | None = None,
            limit: int | None = None,
        ) -> APIControllerResponse:
            assert work_item_key == 'ENG-3'
            requested_pages.append((offset, limit))
            await release_page.wait()
            return APIControllerResponse(
                result=PaginatedJiraWorklog(
                    logs=[
                        JiraWorklog(id='2', work_item_id='ENG-3'),
                        JiraWorklog(id='3', work_item_id='ENG-3'),
                    ],
                    max_results=100,
                    start_at=1,
                    total=3,
                )
            )

        cast(Any, app.api).get_work_item_worklog = get_work_item_worklog
        initial_page = PaginatedJiraWorklog(
            logs=[JiraWorklog(id='1', work_item_id='ENG-3')],
            max_results=1,
            start_at=0,
            total=3,
        )

        async with app.run_test() as pilot:
            screen = WorkItemWorkLogScreen('ENG-3', initial_page=initial_page)
            await app.push_screen(screen)
            await wait_until(lambda: requested_pages == [(1, 100)], timeout=3.0)

            assert [record.key for record in screen.worklog_list_view._records] == ['1']
            assert screen.loading_label.display
            assert not screen.modal_outer.loading

            release_page.set()
            await wait_until(
                lambda: len(screen.worklog_list_view._records) == 3,
                timeout=3.0,
            )
            await pilot.pause()

            assert [record.key for record in screen.worklog_list_view._records] == [
                '1',
                '2',
                '3',
            ]
            assert not screen.loading_label.display

            async def get_reloaded_worklogs(
                work_item_key: str,
                offset: int | None = None,
                limit: int | None = None,
            ) -> APIControllerResponse:
                assert (work_item_key, offset, limit) == ('ENG-3', 0, 100)
                return APIControllerResponse(
                    result=PaginatedJiraWorklog(
                        logs=[JiraWorklog(id='4', work_item_id='ENG-3')],
                        max_results=100,
                        start_at=0,
                        total=1,
                    )
                )

            cast(Any, app.api).get_work_item_worklog = get_reloaded_worklogs
            await screen.reload_worklogs()
            assert [record.key for record in screen.worklog_list_view._records] == ['4']

    @pytest.mark.asyncio
    async def test_worklog_screen_empty_worklogs(
        self,
        mock_configuration,
        mock_user_info,
        mock_jira_worklog_empty,
        mock_jira_server_info,
    ):

        async def run_test(pilot):
            screen = WorkItemWorkLogScreen(work_item_key='ENG-2')
            await pilot.app.push_screen(screen)
            await wait_until(
                lambda: isinstance(pilot.app.screen, WorkItemWorkLogScreen), timeout=3.0
            )
            await wait_until(lambda: not pilot.app.screen.is_loading, timeout=3.0)

            assert isinstance(pilot.app.screen, WorkItemWorkLogScreen)

            list_view = pilot.app.screen.worklog_list_view
            assert isinstance(list_view, RecordList)
            assert len(list_view._records) == 0

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with respx.mock:
            server_info_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/serverInfo'
            )
            server_info_route.mock(return_value=Response(200, json=mock_jira_server_info))
            worklog_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/issue/ENG-2/worklog'
            )
            worklog_route.mock(return_value=Response(200, json=mock_jira_worklog_empty))

            async with app.run_test() as pilot:
                await run_test(pilot)

    def test_worklog_screen_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_worklog,
        mock_jira_server_info,
    ):
        """Test worklog screen initial state snapshot."""
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        with respx.mock:
            server_info_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/serverInfo'
            )
            server_info_route.mock(return_value=Response(200, json=mock_jira_server_info))
            worklog_route = respx.get(
                'https://example.atlassian.acme.net/rest/api/3/issue/ENG-3/worklog'
            )
            worklog_route.mock(return_value=Response(200, json=mock_jira_worklog))

            assert snap_compare(app, terminal_size=(120, 40), run_before=open_worklog_screen)

    def test_delete_worklog(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_worklog_deletion,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=delete_worklog_and_verify)
