import asyncio

from gojeera.app import JiraApp
from gojeera.components.unified_search import UnifiedSearchBar

from .test_helpers import wait_for_mount


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


async def fill_basic_work_item_key(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab')
    await asyncio.sleep(0.1)

    for char in 'EXAMPLE-1234':
        if char == ' ':
            await pilot.press('space')
        else:
            await pilot.press(char)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    work_item_input = search_bar.query_one('#basic-work-item-key')
    assert not work_item_input.has_class('-invalid'), (
        f"Expected valid work item key but input has -invalid class. Value: '{work_item_input.value}'"
    )


async def fill_invalid_work_item_key(pilot):
    await wait_for_mount(pilot)

    await pilot.press('tab')
    await asyncio.sleep(0.1)

    for char in 'invalid-key':
        await pilot.press(char)
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.2)

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)
    work_item_input = search_bar.query_one('#basic-work-item-key')
    assert work_item_input.has_class('-invalid'), (
        f"Expected invalid work item key to be marked with -invalid class. Value: '{work_item_input.value}'"
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

    for char in 'project = EXAMPLE':
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


class TestUnifiedSearch:
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

    def test_unified_search_basic_with_work_item_key(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_basic_work_item_key)

    def test_unified_search_basic_with_invalid_key(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        config = mock_configuration

        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=fill_invalid_work_item_key)

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
