import asyncio

from httpx import Response
import pytest
import respx

from gojeera.app import JiraApp
from gojeera.components.work_item.work_item_comments import CommentsScrollView
from gojeera.utils.jira.reference import parse_work_item_reference
from gojeera.utils.jira.urls import (
    extract_focused_comment_id,
    extract_focused_work_log_id,
    extract_work_item_key,
)
from gojeera.widgets.markdown.gojeera_markdown import (
    build_markdown_link_style,
    get_markdown_link_tooltip,
    get_markdown_link_work_item_key,
)
from gojeera.widgets.navigation.extended_palette import ExtendedPalette


async def open_quick_navigation_palette(pilot):
    pilot.app.action_command_palette()
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, ExtendedPalette)


async def submit_browse_work_item_reference(pilot, reference: str) -> None:
    await open_quick_navigation_palette(pilot)
    pilot.app.action_show_browse_work_item_palette()
    await asyncio.sleep(0.3)

    await pilot.press(*reference)
    await asyncio.sleep(0.2)

    await pilot.press('enter')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


async def load_work_item_via_quick_navigation(
    pilot,
    *,
    reference: str,
    expected_key: str,
):
    await submit_browse_work_item_reference(pilot, reference)

    main_screen = pilot.app
    assert main_screen.current_loaded_work_item_key == expected_key
    assert main_screen.information_panel.work_item is not None
    assert main_screen.information_panel.work_item.key == expected_key
    return main_screen


async def quick_navigation_load_valid_work_item(pilot):
    await load_work_item_via_quick_navigation(
        pilot,
        reference='ENG-1',
        expected_key='ENG-1',
    )


async def quick_navigation_loads_work_item_from_url(pilot):
    await load_work_item_via_quick_navigation(
        pilot,
        reference='https://example.atlassian.acme.net/browse/ENG-1',
        expected_key='ENG-1',
    )


async def quick_navigation_loads_focused_comment_from_url(pilot):
    main_screen = await load_work_item_via_quick_navigation(
        pilot,
        reference='https://example.atlassian.acme.net/browse/ENG-3?focusedCommentId=231668',
        expected_key='ENG-3',
    )
    assert main_screen.tabs.active == 'tab-comments'

    comments_scroll = main_screen.query_one(CommentsScrollView)
    assert comments_scroll.selected_comment is not None
    assert comments_scroll.selected_comment._comment_id == '231668'


async def quick_navigation_rejects_missing_work_item(pilot):
    await submit_browse_work_item_reference(pilot, 'ENG-0')

    main_screen = pilot.app
    assert main_screen.current_loaded_work_item_key is None
    assert main_screen.information_panel.work_item is None
    assert main_screen._active_work_item_load_key is None


async def run_quick_navigation_check(mock_configuration, mock_user_info, check):
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
    async with app.run_test(size=(120, 40)) as pilot:
        await check(pilot)


class TestQuickNavigationScreen:
    def test_extract_work_item_key_accepts_browse_url(self, mock_configuration):
        base_url = mock_configuration.jira.api_base_url

        assert extract_work_item_key(f'{base_url}/browse/ENG-1') == 'ENG-1'
        assert extract_work_item_key(f'{base_url}/browse/ENG-1?foo=bar') == 'ENG-1'
        assert extract_work_item_key('ENG-1') == 'ENG-1'
        assert extract_work_item_key(f'{base_url}/jira/software/projects/ENG') is None
        assert extract_work_item_key(f'{base_url}/browse/ENG-1', base_url) == 'ENG-1'
        assert extract_work_item_key('https://other.atlassian.net/browse/ENG-1', base_url) is None
        assert (
            extract_focused_comment_id(f'{base_url}/browse/ENG-1?focusedCommentId=245054')
            == '245054'
        )
        reference = parse_work_item_reference(f'{base_url}/browse/ENG-1?focusedCommentId=245054')
        assert reference is not None
        assert reference.work_item_key == 'ENG-1'
        assert reference.navigation_target is not None
        assert reference.navigation_target.focused_comment_id == '245054'
        assert reference.navigation_target.focused_work_log_id is None
        assert (
            extract_focused_work_log_id(f'{base_url}/browse/ENG-1?focusedWorklogId=5321') == '5321'
        )
        assert extract_focused_comment_id(f'{base_url}/browse/ENG-1?focusedCommentId=abc') is None

    def test_browse_url_markdown_link_gets_gojeera_tooltip(self, mock_configuration):
        base_url = mock_configuration.jira.api_base_url

        browse_style = build_markdown_link_style(
            f'{base_url}/browse/ENG-1',
            jira_base_url=base_url,
        )
        regular_style = build_markdown_link_style('https://github.com')

        assert (
            get_markdown_link_tooltip(browse_style)
            == 'Can be loaded inside gojeera using CTRL+mouse click'
        )
        assert get_markdown_link_work_item_key(browse_style) == 'ENG-1'
        assert get_markdown_link_tooltip(regular_style) is None

    @pytest.mark.parametrize(
        'check',
        [
            open_quick_navigation_palette,
            quick_navigation_load_valid_work_item,
            quick_navigation_loads_work_item_from_url,
            quick_navigation_loads_focused_comment_from_url,
        ],
    )
    async def test_quick_navigation_actions(
        self,
        check,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        await run_quick_navigation_check(
            mock_configuration,
            mock_user_info,
            check,
        )

    async def test_quick_navigation_rejects_missing_work_item(
        self,
        monkeypatch,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        notifications: list[dict] = []

        def capture_notification(message, **kwargs):
            notifications.append({'message': message, **kwargs})

        monkeypatch.setattr(app, 'notify', capture_notification)

        with respx.mock:
            missing_work_item_route = respx.get(
                url__regex=r'https://example\.atlassian\.acme\.net/rest/api/3/issue/ENG-0(?:\?.*)?$'
            ).mock(return_value=Response(404, json={'errorMessages': ['Issue does not exist']}))

            async with app.run_test(size=(120, 40)) as pilot:
                await quick_navigation_rejects_missing_work_item(pilot)

            assert missing_work_item_route.called
            assert notifications == [
                {
                    'message': 'Work item not found',
                    'severity': 'warning',
                }
            ]
