import asyncio
from contextlib import asynccontextmanager
import copy
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from textual.widgets import Button, Input

from gojeera.app import JiraApp
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.jira.factories import WorkItemFactory
from gojeera.internal.models.work_items import JiraWorkItemSearchResponse
from gojeera.internal.store.cache import get_cache
from gojeera.widgets.selection.vim_select import VimSelect

from .test_helpers import choose_select_option, wait_for_mount, wait_until

SORTABLE_PRIORITY_RANK = {
    'Lowest': 0,
    'Low': 1,
    'Medium': 2,
    'High': 3,
    'Highest': 4,
}


def get_main_screen(app: JiraApp) -> 'JiraApp':
    return app


async def seed_search_history(pilot) -> None:
    cache = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)._cache
    await asyncio.to_thread(cache.add_search_history, 'text', 'recent text search')
    await asyncio.to_thread(cache.add_search_history, 'text', 'another text query')
    await asyncio.to_thread(cache.add_search_history, 'jql', 'project = ENG ORDER BY updated DESC')
    await asyncio.to_thread(cache.add_search_history, 'jql', 'assignee = currentUser()')


async def switch_to_text_search(pilot):
    await wait_for_mount(pilot)

    await choose_select_option(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar.search_mode == 'text', (
        f"Expected 'text' mode but got '{search_bar.search_mode}'"
    )


async def switch_to_jql_search(pilot):
    await wait_for_mount(pilot)

    await choose_select_option(pilot, steps=2)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    assert search_bar.search_mode == 'jql', (
        f"Expected 'jql' mode but got '{search_bar.search_mode}'"
    )


async def open_text_search_history_dropdown(pilot):
    await switch_to_text_search(pilot)
    await seed_search_history(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    search_bar._refresh_search_history_autocomplete('text')
    await pilot.app.workers.wait_for_complete()

    search_input = search_bar.query_one('#unified-search-input', Input)
    search_input.focus()
    await asyncio.sleep(0.2)
    await pilot.press('down')
    await asyncio.sleep(0.2)


async def wait_for_jql_filters_loaded(search_bar: UnifiedSearchBar) -> None:
    await wait_until(
        lambda: (
            search_bar.unified_input.placeholder != 'Loading filters... (Enter JQL query or wait)'
        ),
        timeout=3.0,
    )


async def fill_text_search(pilot):
    await switch_to_text_search(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    search_input = search_bar.query_one('#unified-search-input', Input)
    search_input.focus()
    await asyncio.sleep(0.1)

    for char in 'test search query':
        await pilot.press(char if char != ' ' else 'space')
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    assert search_input.value == 'test search query'


async def fill_jql_search(pilot):
    await switch_to_jql_search(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    search_input = search_bar.query_one('#unified-search-input', Input)
    search_input.focus()
    await asyncio.sleep(0.1)

    for char in 'project = ENG':
        await pilot.press(char if char != ' ' else 'space')
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    assert search_input.value == 'project = ENG'


async def open_project_selector(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)

    await pilot.press('enter')
    await asyncio.sleep(0.5)


async def open_dependent_filter_selector(
    pilot,
    *,
    tabs_to_target: tuple[str, ...],
    wait_for_workers: bool = False,
):
    await wait_for_mount(pilot)

    await pilot.press('tab', 'tab')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)
    await pilot.press('down')
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.press(*tabs_to_target)
    await asyncio.sleep(0.1)
    await pilot.press('enter')
    await asyncio.sleep(0.5)

    if wait_for_workers:
        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.3)


async def open_assignee_selector(pilot):
    await open_dependent_filter_selector(pilot, tabs_to_target=('tab',))


async def open_type_selector(pilot):
    await open_dependent_filter_selector(pilot, tabs_to_target=('tab', 'tab'))


async def open_status_selector(pilot):
    await open_dependent_filter_selector(
        pilot,
        tabs_to_target=('tab', 'tab', 'tab'),
        wait_for_workers=True,
    )


async def open_jql_filters_dropdown(pilot):
    await switch_to_jql_search(pilot)
    await seed_search_history(pilot)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    await wait_for_jql_filters_loaded(search_bar)
    search_bar._refresh_search_history_autocomplete('jql')
    await pilot.app.workers.wait_for_complete()

    jql_input = search_bar.query_one('#unified-search-input')
    jql_input.focus()
    await asyncio.sleep(0.2)

    await pilot.press('space')
    await asyncio.sleep(0.1)
    await pilot.press('backspace')
    await asyncio.sleep(0.5)


async def apply_initial_jql_filter_for_snapshot(pilot):
    await wait_for_mount(pilot)
    await seed_search_history(pilot)

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


def assert_first_result_key(app: JiraApp, expected_key: str) -> list[str]:
    result_keys = get_result_keys(app)
    assert result_keys
    assert result_keys[0] == expected_key
    return result_keys


async def change_search_order_and_wait(pilot, order_value: str) -> list[str]:
    order_by = pilot.app.screen.query_one('#search-results-order-by', VimSelect)
    order_by.value = order_value
    await wait_for_search_and_results(pilot)
    result_keys = get_result_keys(cast(JiraApp, pilot.app))
    assert result_keys
    return result_keys


async def assert_ctrl_j_keeps_empty_search_idle(pilot, search_button: Button) -> None:
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.2)

    assert not get_main_screen(cast(JiraApp, pilot.app)).is_search_request_in_progress
    assert search_button.disabled


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
        work_items = [WorkItemFactory.create_work_item(issue) for issue in sorted_issues]
        return JiraWorkItemSearchResponse(
            work_items=work_items,
            next_page_token=None,
            is_last=True,
            total=len(work_items),
            offset=0,
        )

    async def mock_search_work_items(self, **kwargs: Any) -> APIControllerResponse:
        del self
        jql_query = cast(str | None, kwargs.get('jql_query'))
        return APIControllerResponse(success=True, result=build_search_response_payload(jql_query))

    async def mock_count_work_items(self, **kwargs: Any) -> APIControllerResponse:
        del self
        jql_query = cast(str | None, kwargs.get('jql_query'))
        return APIControllerResponse(
            success=True,
            result=len(filter_issues(jql_query)),
        )

    app_api = cast(Any, app.api)
    app_api.search_work_items = mock_search_work_items.__get__(app.api, type(app.api))
    app_api.count_work_items = mock_count_work_items.__get__(app.api, type(app.api))


def build_sortable_search_app(
    configuration,
    user_info,
    search_payload: dict,
) -> JiraApp:
    app = JiraApp(settings=configuration, user_info=user_info)
    install_sortable_search_api(app, search_payload)
    return app


@asynccontextmanager
async def run_search_pilot(
    app: JiraApp,
    *,
    perform_basic_search: bool,
):
    async with app.run_test() as pilot:
        await wait_for_mount(pilot)
        if perform_basic_search:
            await perform_basic_search_and_wait(pilot)
        yield pilot


@asynccontextmanager
async def run_sortable_search_test(
    configuration,
    user_info,
    *,
    search_payload: dict,
    perform_basic_search: bool,
):
    app = build_sortable_search_app(configuration, user_info, search_payload)
    async with run_search_pilot(app, perform_basic_search=perform_basic_search) as pilot:
        yield pilot


@asynccontextmanager
async def run_search_test(
    configuration,
    user_info,
    *,
    perform_basic_search: bool = False,
):
    app = JiraApp(settings=configuration, user_info=user_info)
    async with run_search_pilot(app, perform_basic_search=perform_basic_search) as pilot:
        yield pilot


@pytest.fixture
def search_test_runner(
    mock_configuration,
    mock_jira_api_with_search_results,
    mock_user_info,
):
    del mock_jira_api_with_search_results

    def run(*, perform_basic_search: bool = False):
        return run_search_test(
            mock_configuration,
            mock_user_info,
            perform_basic_search=perform_basic_search,
        )

    return run


@pytest.fixture
def sortable_search_runner(
    mock_configuration,
    mock_jira_api_with_search_results,
    mock_jira_search_with_results,
    mock_user_info,
):
    del mock_jira_api_with_search_results

    def run(*, perform_basic_search: bool):
        return run_sortable_search_test(
            mock_configuration,
            mock_user_info,
            search_payload=mock_jira_search_with_results,
            perform_basic_search=perform_basic_search,
        )

    return run


@pytest.fixture
def basic_sortable_search_runner(sortable_search_runner):
    return lambda: sortable_search_runner(perform_basic_search=True)


def _configure_empty_search_api(app: JiraApp) -> None:
    cast(Any, app.api).prepare_work_item_search = AsyncMock(
        return_value=APIControllerResponse(result={})
    )
    cast(Any, app.api).search_work_items = AsyncMock(
        return_value=APIControllerResponse(
            result=JiraWorkItemSearchResponse(work_items=[], is_last=True)
        )
    )


@asynccontextmanager
async def loaded_search_results(app: JiraApp, *, timeout: float):
    async with app.run_test() as pilot:
        await wait_for_mount(pilot)
        await app.search_work_items(search_data={'mode': 'basic'})
        await wait_until(lambda: app.search_results_container.results_loaded, timeout=timeout)
        yield pilot


def with_basic_sortable_search_pilot():
    def decorator(test):
        async def wrapper(self, basic_sortable_search_runner):
            async with basic_sortable_search_runner() as pilot:
                await test(self, pilot)

        return wrapper

    return decorator


def get_result_keys(app: JiraApp) -> list[str]:
    response = get_main_screen(app).search_results_list.work_item_search_results
    assert response is not None
    return [work_item.key for work_item in response.work_items]


class TestUnifiedSearch:
    @pytest.mark.asyncio
    async def test_search_and_total_count_requests_run_concurrently(
        self, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        del mock_jira_api_with_search_results
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        started: set[str] = set()
        both_started = asyncio.Event()
        release_search = asyncio.Event()
        release_count = asyncio.Event()
        prepared_kwargs = {'jql_query': 'created >= -30d order by created DESC'}
        prepare = AsyncMock(return_value=APIControllerResponse(result=prepared_kwargs))
        cast(Any, app.api).prepare_work_item_search = prepare

        async def mark_started(name: str) -> None:
            started.add(name)
            if len(started) == 2:
                both_started.set()

        async def search_work_items(**kwargs: Any) -> APIControllerResponse:
            assert kwargs['prepared_search_kwargs'] is prepared_kwargs
            await mark_started('search')
            await release_search.wait()
            return APIControllerResponse(
                result=JiraWorkItemSearchResponse(work_items=[], is_last=True)
            )

        async def count_work_items(**kwargs: Any) -> APIControllerResponse:
            assert kwargs['prepared_search_kwargs'] is prepared_kwargs
            await mark_started('count')
            await release_count.wait()
            return APIControllerResponse(result=7)

        cast(Any, app.api).search_work_items = search_work_items
        cast(Any, app.api).count_work_items = count_work_items

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            request = asyncio.create_task(app._search_work_items(search_data={'mode': 'basic'}))
            await asyncio.wait_for(both_started.wait(), timeout=1.0)
            release_search.set()
            result = await asyncio.wait_for(request, timeout=1.0)
            count_task = app._pending_search_count_task
            assert count_task is not None
            assert not count_task.done()
            release_count.set()
            assert (await count_task).result == 7

        assert started == {'search', 'count'}
        assert result.total == 0
        prepare.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_results_stop_loading_before_slow_count_finishes(
        self, mock_configuration, search_results_app
    ):
        app = search_results_app
        count_started = asyncio.Event()
        release_count = asyncio.Event()
        _configure_empty_search_api(app)

        async def count_work_items(**kwargs: Any) -> APIControllerResponse:
            del kwargs
            count_started.set()
            await release_count.wait()
            return APIControllerResponse(result=77)

        cast(Any, app.api).count_work_items = count_work_items

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await app.search_work_items(search_data={'mode': 'basic'})
            await asyncio.wait_for(count_started.wait(), timeout=1.0)

            assert not app.search_results_container.is_loading
            assert app.search_results_container.pagination == {
                'total': 0,
                'current_page_number': 1,
            }

            release_count.set()
            await wait_until(
                lambda: (app.search_results_container.pagination or {}).get('total') == 77,
                timeout=1.0,
            )
            total_pages = app.search_results_list.total_pages

        page_size = mock_configuration.search_results_per_page
        assert total_pages == (77 + page_size - 1) // page_size

    @pytest.mark.asyncio
    async def test_repeated_search_recalculates_total_count(self, search_results_app):
        app = search_results_app
        _configure_empty_search_api(app)
        count_work_items = AsyncMock(
            side_effect=[
                APIControllerResponse(result=7),
                APIControllerResponse(result=0),
            ]
        )
        cast(Any, app.api).count_work_items = count_work_items

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            search_data = app.unified_search_bar.get_search_data()
            await app.search_work_items(search_data=search_data)
            await wait_until(
                lambda: (app.search_results_container.pagination or {}).get('total') == 7,
                timeout=1.0,
            )

            await app.action_search()
            await wait_until(
                lambda: (
                    count_work_items.await_count == 2
                    and not app.search_results_container.is_loading
                    and (app.search_results_container.pagination or {}).get('total') == 0
                ),
                timeout=1.0,
            )

            assert (app.search_results_container.pagination or {}).get('total') == 0
            assert app.search_results_list.total_pages == 1

    @pytest.mark.asyncio
    async def test_initial_jql_search_is_validated_once_for_search_and_count(
        self, search_results_app
    ):
        app = search_results_app
        validation = AsyncMock(return_value=APIControllerResponse())
        cast(Any, app.api).validate_jql_query = validation
        cast(Any, app.api).search_work_items = AsyncMock(
            return_value=APIControllerResponse(
                result=JiraWorkItemSearchResponse(work_items=[], is_last=True)
            )
        )
        cast(Any, app.api).count_work_items = AsyncMock(
            return_value=APIControllerResponse(result=0)
        )

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await app._search_work_items(search_data={'mode': 'jql', 'jql': 'project = ENG'})

        validation.assert_awaited_once_with('project = ENG')

    @pytest.mark.asyncio
    async def test_active_search_page_reuses_validation_and_total(
        self,
        monkeypatch,
        search_results_app,
    ):
        app = search_results_app
        validation = AsyncMock()
        monkeypatch.setattr(app.api, 'validate_jql_query', validation)
        search = AsyncMock(
            return_value=SimpleNamespace(
                response=JiraWorkItemSearchResponse(work_items=[], is_last=True),
                total=0,
            )
        )
        monkeypatch.setattr(app, '_search_work_items', search)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            app._active_search_data = {'mode': 'jql', 'jql': 'project = ENG'}
            app.search_results_list.total_pages = 4
            app.search_results_container.pagination = {
                'total': 77,
                'current_page_number': 1,
            }

            await app.search_work_items(page=2, use_active_search=True)

            total_pages = app.search_results_list.total_pages
            pagination = app.search_results_container.pagination

        validation.assert_not_awaited()
        assert search.await_args is not None
        assert search.await_args.kwargs['calculate_total'] is False
        assert total_pages == 4
        assert pagination == {
            'total': 77,
            'current_page_number': 2,
        }

    @pytest.mark.asyncio
    async def test_active_search_page_retains_current_results_while_loading_and_on_failure(
        self,
        monkeypatch,
        search_results_app,
    ):
        app = search_results_app
        page_request_started = asyncio.Event()
        release_page_request = asyncio.Event()

        async def fail_page_request(**kwargs: Any):
            del kwargs
            page_request_started.set()
            await release_page_request.wait()
            return SimpleNamespace(response=None, total=0)

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            await app.search_work_items(search_data={'mode': 'basic'})
            await wait_until(lambda: app.search_results_container.results_loaded, timeout=1.0)
            existing_response = app.search_results_list.work_item_search_results
            existing_rows = list(app.search_results_list.work_item_containers)
            assert existing_response is not None
            assert existing_rows

            app._active_search_data = {'mode': 'basic'}
            monkeypatch.setattr(app, '_search_work_items', fail_page_request)
            request = asyncio.create_task(app.search_work_items(page=2, use_active_search=True))
            await asyncio.wait_for(page_request_started.wait(), timeout=1.0)

            assert app.search_results_container.is_loading
            assert app.search_results_list.work_item_search_results is existing_response
            assert app.search_results_list.work_item_containers == existing_rows
            assert app.search_results_list.display

            release_page_request.set()
            await asyncio.wait_for(request, timeout=1.0)

            assert app.search_results_list.work_item_search_results is existing_response
            assert app.search_results_list.work_item_containers == existing_rows
            assert app.search_results_list.display
            assert not app.search_results_container.is_loading

    @pytest.mark.asyncio
    async def test_ctrl_j_search_focuses_results_after_render(
        self,
        search_results_app,
    ):
        app = search_results_app

        async with loaded_search_results(app, timeout=3.0) as pilot:
            app.unified_search_bar.unified_input.focus()
            await pilot.pause()

            await pilot.press('ctrl+j')
            await wait_until(
                lambda: (
                    app.search_results_container.results_loaded
                    and not app.search_results_container.is_loading
                ),
                timeout=3.0,
            )

            assert app.focused is app.search_results_list

    def test_pending_search_render_ignores_unmounted_results(self):
        complete_initial_render = Mock()
        list_view = SimpleNamespace(
            is_mounted=False,
            is_pending_initial_render=True,
            _complete_initial_render=complete_initial_render,
        )

        JiraApp._complete_pending_search_render(cast(Any, list_view))

        complete_initial_render.assert_not_called()

    @pytest.mark.asyncio
    async def test_page_key_navigation_restores_search_results_focus_after_render(
        self,
        monkeypatch,
        mock_configuration,
        search_results_app,
    ):
        app = search_results_app

        async with loaded_search_results(app, timeout=1.0) as pilot:
            search_results = app.search_results_list
            existing_response = search_results.work_item_search_results
            assert existing_response is not None

            monkeypatch.setattr(
                app,
                '_search_work_items',
                AsyncMock(return_value=SimpleNamespace(response=existing_response, total=0)),
            )
            app._active_search_data = {'mode': 'basic'}
            search_results.total_pages = 2
            search_results.token_by_page[2] = 'next-page-token'
            app.search_results_container.pagination = {
                'total': mock_configuration.search_results_per_page * 2,
                'current_page_number': 1,
            }
            search_results.focus()
            await pilot.pause()

            await pilot.press('n')
            await wait_until(
                lambda: (
                    search_results.page == 2
                    and app.focused is search_results
                    and not app.search_results_container.is_loading
                ),
                timeout=1.0,
            )

            await pilot.press('p')
            await wait_until(
                lambda: (
                    search_results.page == 1
                    and app.focused is search_results
                    and not app.search_results_container.is_loading
                ),
                timeout=1.0,
            )

    @pytest.mark.asyncio
    async def test_search_results_page_actions_do_not_overflow(
        self, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        del mock_jira_api_with_search_results
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        page_requests: list[int] = []

        def record_page_request(*, page_number: int, **kwargs: Any) -> None:
            del kwargs
            page_requests.append(page_number)

        cast(Any, app)._start_search_page = record_page_request

        async with app.run_test() as pilot:
            await wait_for_mount(pilot)
            search_results = get_main_screen(app).search_results_list
            search_results.focus()

            search_results.page = 1
            search_results.total_pages = 3
            await pilot.press('p')
            await pilot.pause()

            assert search_results.page == 1
            assert page_requests == []

            search_results.page = 3
            search_results.total_pages = 3
            search_results.token_by_page = {}
            await pilot.press('n')
            await pilot.pause()

            assert search_results.page == 3
            assert page_requests == []

    def test_set_initial_jql_filter(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
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
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_mount)

    def test_unified_search_switch_to_text_mode(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=switch_to_text_search)

    def test_unified_search_text_mode_with_search_history(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(
            app, terminal_size=(120, 40), run_before=open_text_search_history_dropdown
        )

    def test_unified_search_switch_to_jql_mode(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=switch_to_jql_search)

    def test_unified_search_text_with_query(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_text_search)

    def test_unified_search_jql_with_query(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_jql_search)

    def test_unified_search_project_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_project_selector)

    def test_unified_search_assignee_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_assignee_selector)

    def test_unified_search_type_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_type_selector)

    def test_unified_search_status_selector_opened(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_status_selector)

    def test_unified_search_jql_with_filters(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        del mock_jira_api_sync
        config = mock_configuration

        config.jql_filters = [
            {
                'label': 'My Open Issues',
                'expression': 'assignee = currentUser() AND status != Done',
            },
            {'label': 'Recently Updated', 'expression': 'updated >= -7d ORDER BY updated DESC'},
        ]
        config.fetch_remote_filters.enabled = True

        get_cache().set_remote_filters(
            mock_user_info.account_id,
            [
                {
                    'label': 'Favorite Remote Filter',
                    'expression': 'project = ENG AND priority = High',
                    'source': 'remote',
                    'starred': True,
                },
                {
                    'label': 'Regular Remote Filter',
                    'expression': 'project = ENG ORDER BY updated DESC',
                    'source': 'remote',
                    'starred': False,
                },
            ],
        )

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_jql_filters_dropdown)

    @pytest.mark.asyncio
    async def test_search_button_stays_enabled_after_multiple_basic_searches(
        self,
        search_test_runner,
    ):
        async with search_test_runner() as pilot:
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
        search_test_runner,
    ):
        async with search_test_runner(perform_basic_search=True) as pilot:
            search_bar = await switch_mode(pilot, 'text')
            search_button = search_bar.query_one('#unified-search-button', Button)

            assert search_bar.search_mode == 'text'
            assert search_button.disabled

            await assert_ctrl_j_keeps_empty_search_idle(pilot, search_button)

    @pytest.mark.asyncio
    @with_basic_sortable_search_pilot()
    async def test_basic_search_then_jql_mode_disables_empty_search_and_results_controls(
        self, pilot
    ):
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

        await assert_ctrl_j_keeps_empty_search_idle(pilot, search_button)

    @pytest.mark.asyncio
    @with_basic_sortable_search_pilot()
    async def test_basic_search_sort_change_updates_first_result(self, pilot):
        assert_first_result_key(cast(JiraApp, pilot.app), 'ENG-8')
        sorted_keys = await change_search_order_and_wait(pilot, 'priority')
        assert sorted_keys[0] != 'ENG-8'

    @pytest.mark.asyncio
    @with_basic_sortable_search_pilot()
    async def test_basic_search_refresh_keeps_results_unchanged(self, pilot):
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
        sortable_search_runner,
    ):
        async with sortable_search_runner(perform_basic_search=False) as pilot:
            search_bar = await switch_mode(pilot, 'text')
            search_input = search_bar.query_one('#unified-search-input', Input)
            search_input.value = 'monster'
            await asyncio.sleep(0.2)

            await pilot.press('ctrl+j')
            await wait_for_search_and_results(pilot)

            assert_first_result_key(cast(JiraApp, pilot.app), 'ENG-8')
            updated_keys = await change_search_order_and_wait(pilot, 'updated')
            assert updated_keys[0] == 'ENG-1'
