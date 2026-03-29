import asyncio

from gojeera.app import JiraApp
from gojeera.components.quick_navigation_screen import QuickNavigationScreen
from gojeera.utils.urls import extract_work_item_key
from gojeera.widgets.gojeera_markdown import (
    build_markdown_link_style,
    get_markdown_link_tooltip,
    get_markdown_link_work_item_key,
)


async def open_quick_navigation_screen(pilot):
    screen = QuickNavigationScreen()
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, QuickNavigationScreen)
    assert pilot.app.screen.work_item_key_input.has_focus
    assert pilot.app.screen.open_button.disabled


async def quick_navigation_load_valid_work_item(pilot):
    await open_quick_navigation_screen(pilot)

    await pilot.press(*'EXAMPLE-19539')
    await asyncio.sleep(0.2)

    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    main_screen = pilot.app.screen
    assert main_screen.current_loaded_work_item_key == 'EXAMPLE-19539'
    assert main_screen.information_panel.work_item is not None
    assert main_screen.information_panel.work_item.key == 'EXAMPLE-19539'


async def quick_navigation_loads_work_item_from_url(pilot):
    await open_quick_navigation_screen(pilot)

    await pilot.press(*'https://example.atlassian.net/browse/EXAMPLE-19539')
    await asyncio.sleep(0.2)

    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    main_screen = pilot.app.screen
    assert main_screen.current_loaded_work_item_key == 'EXAMPLE-19539'
    assert main_screen.information_panel.work_item is not None
    assert main_screen.information_panel.work_item.key == 'EXAMPLE-19539'


class TestQuickNavigationScreen:
    def test_extract_work_item_key_accepts_browse_url(self, mock_configuration):
        base_url = mock_configuration.jira.api_base_url

        assert extract_work_item_key(f'{base_url}/browse/EXAMPLE-19539') == 'EXAMPLE-19539'
        assert extract_work_item_key(f'{base_url}/browse/EXAMPLE-19539?foo=bar') == 'EXAMPLE-19539'
        assert extract_work_item_key('EXAMPLE-19539') == 'EXAMPLE-19539'
        assert extract_work_item_key(f'{base_url}/jira/software/projects/EXAMPLE') is None
        assert (
            extract_work_item_key(f'{base_url}/browse/EXAMPLE-19539', base_url) == 'EXAMPLE-19539'
        )
        assert (
            extract_work_item_key('https://other.atlassian.net/browse/EXAMPLE-19539', base_url)
            is None
        )

    def test_browse_url_markdown_link_gets_gojeera_tooltip(self, mock_configuration):
        base_url = mock_configuration.jira.api_base_url

        browse_style = build_markdown_link_style(
            f'{base_url}/browse/EXAMPLE-19539',
            jira_base_url=base_url,
        )
        regular_style = build_markdown_link_style('https://github.com')

        assert (
            get_markdown_link_tooltip(browse_style)
            == 'Can be loaded inside gojeera using CTRL+mouse click'
        )
        assert get_markdown_link_work_item_key(browse_style) == 'EXAMPLE-19539'
        assert get_markdown_link_tooltip(regular_style) is None

    def test_quick_navigation_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_sync, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_quick_navigation_screen,
        )

    def test_quick_navigation_loads_valid_work_item(
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
            run_before=quick_navigation_load_valid_work_item,
        )

    def test_quick_navigation_loads_work_item_from_url(
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
            run_before=quick_navigation_loads_work_item_from_url,
        )
