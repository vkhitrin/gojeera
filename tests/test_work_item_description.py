import asyncio
import copy

import pytest

from gojeera.app import JiraApp
from gojeera.widgets.gojeera_markdown import (
    ExtendedMarkdownParagraph,
    get_markdown_link_href,
)

from .test_helpers import wait_for_mount


@pytest.fixture
def mock_jira_search_with_results(mock_jira_search_with_description_links):
    return copy.deepcopy(mock_jira_search_with_description_links)


async def open_description_and_hover_internal_link(pilot):
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    paragraph = pilot.app.screen.query(ExtendedMarkdownParagraph).first()
    await pilot.hover(paragraph, offset=(35, 0))
    await pilot.pause(1.0)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


async def load_focused_internal_jira_link_from_keybind(pilot):
    await open_description_and_hover_internal_link(pilot)
    assert pilot.app.screen.focused_work_item_link_key == 'EXAMPLE-19538'

    await pilot.press('ctrl+g')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    assert pilot.app.screen.current_loaded_work_item_key == 'EXAMPLE-19538'


async def open_description_and_hover_wrapped_link(pilot):
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    paragraphs = list(pilot.app.screen.query(ExtendedMarkdownParagraph))
    wrapped_link_paragraph = next(
        paragraph for paragraph in paragraphs if 'Rollout checklist URL:' in paragraph.content.plain
    )
    link_offset = next(
        (x, y)
        for y in range(wrapped_link_paragraph.size.height)
        for x in range(wrapped_link_paragraph.size.width)
        if get_markdown_link_href(wrapped_link_paragraph.get_style_at(x, y)) is not None
    )
    await pilot.hover(wrapped_link_paragraph, offset=link_offset)
    await pilot.pause(0.3)


class TestWorkItemDescription:
    def test_wrapped_link_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        mock_configuration.theme = 'dracula'
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app.theme = 'dracula'
        assert snap_compare(
            app,
            terminal_size=(80, 40),
            run_before=open_description_and_hover_wrapped_link,
        )

    def test_internal_jira_link_tooltip_snapshot(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        mock_configuration.theme = 'dracula'
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app._disable_tooltips = False
        app.theme = 'dracula'

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_description_and_hover_internal_link,
        )

    def test_loads_focused_internal_jira_link_from_keybind(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app._disable_tooltips = False

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=load_focused_internal_jira_link_from_keybind,
        )
