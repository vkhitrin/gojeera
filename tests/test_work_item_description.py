import asyncio

from gojeera.app import JiraApp
from gojeera.widgets.gojeera_markdown import (
    ExtendedMarkdownParagraph,
    get_markdown_link_href,
)

from .test_helpers import load_work_item_from_search, wait_for_mount, wait_until


def _find_link_offset(paragraph: ExtendedMarkdownParagraph, href_substring: str) -> tuple[int, int]:
    return next(
        (x, y)
        for y in range(paragraph.size.height)
        for x in range(paragraph.size.width)
        if (
            (href := get_markdown_link_href(paragraph.get_style_at(x, y))) is not None
            and href_substring in href
        )
    )


async def open_description_and_hover_internal_link(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-8')

    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: bool(list(pilot.app.screen.query(ExtendedMarkdownParagraph))),
        timeout=3.0,
    )
    await asyncio.sleep(0.3)

    paragraphs = list(pilot.app.screen.query(ExtendedMarkdownParagraph))
    internal_link_paragraph = next(
        paragraph
        for paragraph in paragraphs
        if 'Depends on motion alert validation in' in paragraph.content.plain
    )
    link_offset = _find_link_offset(internal_link_paragraph, '/browse/ENG-7')
    await pilot.hover(internal_link_paragraph, offset=link_offset)
    await pilot.pause(1.0)

    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: pilot.app.screen.focused_work_item_link_key == 'ENG-7', timeout=3.0)
    await asyncio.sleep(0.3)


async def load_focused_internal_jira_link_from_keybind(pilot):
    await open_description_and_hover_internal_link(pilot)
    assert pilot.app.screen.focused_work_item_link_key == 'ENG-7'

    await pilot.press('ctrl+g')
    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: pilot.app.screen.current_loaded_work_item_key == 'ENG-7', timeout=3.0)

    assert pilot.app.screen.current_loaded_work_item_key == 'ENG-7'


async def open_description_and_hover_wrapped_link(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-8')

    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: bool(list(pilot.app.screen.query(ExtendedMarkdownParagraph))),
        timeout=3.0,
    )
    await asyncio.sleep(0.3)

    paragraphs = list(pilot.app.screen.query(ExtendedMarkdownParagraph))
    wrapped_link_paragraph = next(
        paragraph for paragraph in paragraphs if 'Nightly checklist URL:' in paragraph.content.plain
    )
    link_offset = _find_link_offset(
        wrapped_link_paragraph,
        '/animatronics/release-playbook/nightly-checklist',
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
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
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
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app._disable_tooltips = False

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
