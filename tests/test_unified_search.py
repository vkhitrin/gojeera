import asyncio
import copy
from typing import TYPE_CHECKING, Any, cast

import pytest
from textual.widgets import Button, Input

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.api_controller.factories import WorkItemFactory
from gojeera.app import JiraApp
from gojeera.components.unified_search import UnifiedSearchBar
from gojeera.models import JiraWorkItemSearchResponse
from gojeera.widgets.vim_select import VimSelect

from .test_helpers import wait_for_mount, wait_until

if TYPE_CHECKING:
    from gojeera.app import MainScreen


SORTABLE_PRIORITY_RANK = {
    'Lowest': 0,
    'Low': 1,
    'Medium': 2,
    'High': 3,
    'Highest': 4,
}


def get_main_screen(app: JiraApp) -> 'MainScreen':
    return cast('MainScreen', app.screen)


async def switch_to_text_search(pilot):
    await wait_for_mount(pilot)

    await pilot.press('enter')
    await asyncio.sleep(0.2)
    await pilot.press('down')
    await asyncio.sleep(0.2)
    await pilot.press('enter')
    await asyncio.sleep(0.3)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar.search_mode == 'text', (
        f"Expected 'text' mode but got '{search_bar.search_mode}'"
    )


async def switch_to_jql_search(pilot):
    await wait_for_mount(pilot)

    await pilot.press('enter')
    await asyncio.sleep(0.2)
    await pilot.press('down')
    await asyncio.sleep(0.1)
    await pilot.press('down')
    await asyncio.sleep(0.2)
    await pilot.press('enter')
    await asyncio.sleep(0.3)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar.search_mode == 'jql', (
        f"Expected 'jql' mode but got '{search_bar.search_mode}'"
    )


async def fill_text_search(pilot):
    await switch_to_text_search(pilot)

    await pilot.press('tab')
    await asyncio.sleep(0.1)

    for char in 'test search query':
        await pilot.press(char)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)


async def fill_jql_search(pilot):
    await switch_to_jql_search(pilot)

    await pilot.press('tab')
    await asyncio.sleep(0.1)

    for char in 'project = ENG':
        await pilot.press(char if char != ' ' else 'space')
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)


async def open_project_selector(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)

    await pilot.press('enter')
    await asyncio.sleep(0.5)


async def open_assignee_selector(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)
    await pilot.press('down')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.press('tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)


async def open_type_selector(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)
    await pilot.press('down')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)


async def open_status_selector(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)
    await pilot.press('down')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.press('tab', 'tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)


async def open_jql_filters_dropdown(pilot):
    await switch_to_jql_search(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    jql_input = search_bar.query_one('#unified-search-input')
    jql_input.focus()
    await asyncio.sleep(0.2)

    await pilot.press('space')
    await asyncio.sleep(0.1)
    await pilot.press('backspace')
    await asyncio.sleep(0.5)


async def apply_initial_jql_filter_for_snapshot(pilot):
    await wait_for_mount(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    await search_bar.set_initial_jql_filter('Open Issues Assigned To Me')
    await asyncio.sleep(0.2)


async def perform_basic_search_and_wait(pilot) -> None:
    app = cast(JiraApp, pilot.app)
    await pilot.press('ctrl+j')
    await app.workers.wait_for_complete()
    await wait_until(lambda: not get_main_screen(app).is_search_request_in_progress, timeout=3.0)
    await asyncio.sleep(0.2)


async def wait_for_search_and_results(pilot) -> None:
    app = cast(JiraApp, pilot.app)
    await asyncio.sleep(0.1)
    await app.workers.wait_for_complete()
    await wait_until(
        lambda: (
            not get_main_screen(app).is_search_request_in_progress
            and get_main_screen(app).search_results_list.work_item_search_results is not None
        ),
        timeout=3.0,
    )
    await asyncio.sleep(0.2)


async def switch_mode(pilot, mode: str) -> UnifiedSearchBar:
    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    mode_selector = search_bar.query_one('#search-mode-selector', VimSelect)
    mode_selector.value = mode
    await asyncio.sleep(0.2)
    return search_bar


def install_sortable_search_api(app: JiraApp, search_payload: dict) -> None:
    issues = copy.deepcopy(search_payload['issues'])

    for issue in issues:
        if issue['key'] == 'ENG-1':
            issue['fields']['updated'] = '2026-03-01T17:00:00.000+0200'
            break

    def parse_key(issue: dict) -> tuple[str, int]:
        project, number = issue['key'].split('-', 1)
        return project, int(number)

    def parse_order_by(jql_query: str | None) -> tuple[str, str]:
        if not jql_query:
            return 'created', 'DESC'

        normalized = jql_query.lower()
        marker = ' order by '
        if marker not in normalized:
            return 'created', 'DESC'

        order_clause = jql_query[normalized.rfind(marker) + len(marker) :].strip()
        parts = order_clause.split()
        if not parts:
            return 'created', 'DESC'

        field = parts[0]
        direction = parts[1].upper() if len(parts) > 1 else 'DESC'
        return field, direction

    def filter_issues(jql_query: str | None) -> list[dict]:
        if not jql_query:
            return issues

        normalized = jql_query.lower()
        filtered = issues
        if 'monster' in normalized:
            filtered = [
                issue for issue in filtered if 'monster' in issue['fields']['summary'].lower()
            ]
        return filtered

    def sort_issues(filtered_issues: list[dict], field: str, direction: str) -> list[dict]:
        reverse = direction != 'ASC'

        def sort_key(issue: dict):
            fields = issue['fields']
            match field:
                case 'updated':
                    return fields.get('updated') or ''
                case 'key':
                    return parse_key(issue)
                case 'priority':
                    priority = fields.get('priority')
                    priority_name = priority.get('name') if isinstance(priority, dict) else None
                    if isinstance(priority_name, str):
                        return SORTABLE_PRIORITY_RANK.get(priority_name, -1)
                    return -1
                case 'status':
                    return (fields.get('status') or {}).get('name') or ''
                case 'resolved':
                    return fields.get('resolutiondate') or ''
                case 'lastViewed':
                    return fields.get('updated') or ''
                case _:
                    return fields.get('created') or ''

        return sorted(filtered_issues, key=sort_key, reverse=reverse)

    def build_search_response_payload(jql_query: str | None) -> JiraWorkItemSearchResponse:
        field, direction = parse_order_by(jql_query)
        filtered = filter_issues(jql_query)
        sorted_issues = sort_issues(filtered, field, direction)
        work_items = [WorkItemFactory.new_work_item(issue) for issue in sorted_issues]
        return JiraWorkItemSearchResponse(
            work_items=work_items,
            next_page_token=None,
            is_last=True,
            total=len(work_items),
            offset=0,
        )

    async def mock_search_work_items(
        self,
        project_key: str | None = None,
        created_from=None,
        created_until=None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        search_in_active_sprint: bool = False,
        jql_query: str | None = None,
        next_page_token: str | None = None,
        limit: int | None = None,
        fields: list[str] | None = None,
    ) -> APIControllerResponse:
        return APIControllerResponse(success=True, result=build_search_response_payload(jql_query))

    async def mock_count_work_items(
        self,
        project_key: str | None = None,
        created_from=None,
        created_until=None,
        status: int | None = None,
        assignee: str | None = None,
        work_item_type: int | None = None,
        jql_query: str | None = None,
    ) -> APIControllerResponse:
        return APIControllerResponse(
            success=True,
            result=len(filter_issues(jql_query)),
        )

    app_api = cast(Any, app.api)
    app_api.search_work_items = mock_search_work_items.__get__(app.api, type(app.api))
    app_api.count_work_items = mock_count_work_items.__get__(app.api, type(app.api))


def get_result_keys(app: JiraApp) -> list[str]:
    response = get_main_screen(app).search_results_list.work_item_search_results
    assert response is not None
    return [work_item.key for work_item in response.work_items]


class TestUnifiedSearch:
    def test_set_initial_jql_filter(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        filter_label = 'Open Issues Assigned To Me'
        filter_expression = 'assignee = currentUser() AND resolution = Unresolved'

        mock_configuration.jql_filters = [
            {
                'label': filter_label,
                'expression': filter_expression,
            }
        ]

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=apply_initial_jql_filter_for_snapshot,
        )

    def test_unified_search_basic_mode_initial(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_mount)

    def test_unified_search_switch_to_text_mode(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=switch_to_text_search)

    def test_unified_search_switch_to_jql_mode(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=switch_to_jql_search)

    def test_unified_search_text_with_query(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_text_search)

    def test_unified_search_jql_with_query(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_jql_search)

    def test_unified_search_project_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_project_selector)

    def test_unified_search_assignee_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_assignee_selector)

    def test_unified_search_type_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_type_selector)

    def test_unified_search_status_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_status_selector)

    def test_unified_search_jql_with_filters(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        config.jql_filters = [
            {
                'label': 'My Open Issues',
                'expression': 'assignee = currentUser() AND status != Done',
            },
            {'label': 'Recently Updated', 'expression': 'updated >= -7d ORDER BY updated DESC'},
        ]

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_jql_filters_dropdown)

    @pytest.mark.asyncio
    async def test_search_button_stays_enabled_after_multiple_basic_searches(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)

            search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
            search_button = search_bar.query_one('#unified-search-button', Button)
            assert not search_button.disabled

            await perform_basic_search_and_wait(pilot)
            assert not search_button.disabled

            await perform_basic_search_and_wait(pilot)
            assert not search_button.disabled

            await perform_basic_search_and_wait(pilot)
            assert not search_button.disabled

    @pytest.mark.asyncio
    async def test_basic_search_then_text_mode_disables_empty_search(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await perform_basic_search_and_wait(pilot)

            search_bar = await switch_mode(pilot, 'text')
            search_button = search_bar.query_one('#unified-search-button', Button)

            assert search_bar.search_mode == 'text'
            assert search_button.disabled

            await pilot.press('ctrl+j')
            await asyncio.sleep(0.2)

            assert not get_main_screen(cast(JiraApp, pilot.app)).is_search_request_in_progress
            assert search_button.disabled

    @pytest.mark.asyncio
    async def test_basic_search_then_jql_mode_disables_empty_search_and_results_controls(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_jira_search_with_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        install_sortable_search_api(app, mock_jira_search_with_results)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await perform_basic_search_and_wait(pilot)

            search_bar = await switch_mode(pilot, 'jql')
            search_button = search_bar.query_one('#unified-search-button', Button)
            order_by = pilot.app.screen.query_one('#search-results-order-by', VimSelect)
            order_direction = pilot.app.screen.query_one(
                '#search-results-order-direction-button', Button
            )
            refresh_button = pilot.app.screen.query_one('#search-results-refresh-button', Button)

            assert search_bar.search_mode == 'jql'
            assert search_button.disabled
            assert order_by.display
            assert order_direction.display
            assert refresh_button.display
            assert order_by.disabled
            assert order_direction.disabled
            assert refresh_button.disabled

            await pilot.press('ctrl+j')
            await asyncio.sleep(0.2)

            assert not get_main_screen(cast(JiraApp, pilot.app)).is_search_request_in_progress
            assert search_button.disabled

    @pytest.mark.asyncio
    async def test_basic_search_sort_change_updates_first_result(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_jira_search_with_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        install_sortable_search_api(app, mock_jira_search_with_results)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await perform_basic_search_and_wait(pilot)

            initial_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert initial_keys
            assert initial_keys[0] == 'ENG-8'

            order_by = pilot.app.screen.query_one('#search-results-order-by', VimSelect)
            order_by.value = 'priority'
            await wait_for_search_and_results(pilot)

            sorted_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert sorted_keys
            assert sorted_keys[0] != 'ENG-8'

    @pytest.mark.asyncio
    async def test_basic_search_refresh_keeps_results_unchanged(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_jira_search_with_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        install_sortable_search_api(app, mock_jira_search_with_results)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await perform_basic_search_and_wait(pilot)

            initial_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert initial_keys

            refresh_button = pilot.app.screen.query_one('#search-results-refresh-button', Button)
            refresh_button.press()
            await wait_for_search_and_results(pilot)

            refreshed_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert refreshed_keys == initial_keys

    @pytest.mark.asyncio
    async def test_text_search_sort_change_updates_to_latest_updated_issue(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_jira_search_with_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        install_sortable_search_api(app, mock_jira_search_with_results)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)

            search_bar = await switch_mode(pilot, 'text')
            search_input = search_bar.query_one('#unified-search-input', Input)
            search_input.value = 'monster'
            await asyncio.sleep(0.2)

            await pilot.press('ctrl+j')
            await wait_for_search_and_results(pilot)

            initial_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert initial_keys
            assert initial_keys[0] == 'ENG-8'

            order_by = pilot.app.screen.query_one('#search-results-order-by', VimSelect)
            order_by.value = 'updated'
            await wait_for_search_and_results(pilot)

            updated_keys = get_result_keys(cast(JiraApp, pilot.app))
            assert updated_keys
            assert updated_keys[0] == 'ENG-1'
