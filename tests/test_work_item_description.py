import asyncio
from datetime import datetime
from types import SimpleNamespace

from gojeera.app import JiraApp
from gojeera.components.work_item_attachments import AttachmentsDataTable
from gojeera.models import Attachment, JiraUser
from gojeera.utils.adf_helpers import extract_media_attachment_details, replace_media_with_text
from gojeera.widgets.gojeera_markdown import (
    ATTACHMENT_BROWSER_OPEN_HINT,
    AttachmentTooltipProvider,
    ExtendedMarkdownParagraph,
    GojeeraMarkdownFence,
    build_attachment_tooltip,
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


async def click_attachment_link_and_open_attachments_tab(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-1')

    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: bool(list(pilot.app.screen.query(ExtendedMarkdownParagraph))),
        timeout=3.0,
    )
    await asyncio.sleep(0.3)

    paragraphs = list(pilot.app.screen.query(ExtendedMarkdownParagraph))
    attachment_paragraph = next(
        paragraph
        for paragraph in paragraphs
        if 'image-20260205-112310.png' in paragraph.content.plain
    )
    attachment_paragraph.action_attachment('image-20260205-112310.png')

    await wait_until(lambda: pilot.app.screen.tabs.active == 'tab-attachments', timeout=3.0)
    await wait_until(
        lambda: pilot.app.screen.query_one(AttachmentsDataTable).cursor_row == 0,
        timeout=3.0,
    )
    await asyncio.sleep(0.3)


class TestWorkItemDescription:
    def test_markdown_fence_normalizes_prism_language_aliases(self):
        assert GojeeraMarkdownFence.normalize_language('docker') == 'dockerfile'
        assert GojeeraMarkdownFence.normalize_language('markup') == 'html'
        assert GojeeraMarkdownFence.normalize_language('objectivec') == 'objective-c'
        assert GojeeraMarkdownFence.normalize_language('shellSession') == 'console'
        assert GojeeraMarkdownFence.normalize_language('diff') == 'diff'

    def test_markdown_fence_treats_missing_language_as_plain_text(self):
        assert GojeeraMarkdownFence.normalize_language('') is None
        assert GojeeraMarkdownFence.normalize_language('   ') is None

    def test_markdown_fence_falls_back_to_text_for_unsupported_prism_languages(self):
        assert GojeeraMarkdownFence.normalize_language('markupTemplating') == 'html'
        assert GojeeraMarkdownFence.normalize_language('plantUml') == 'text'
        assert GojeeraMarkdownFence.normalize_language('tremor') == 'text'

    def test_build_attachment_tooltip_includes_attachment_metadata(self):
        tooltip = build_attachment_tooltip(
            'report.pdf',
            mime_type='application/pdf',
            size_kb='416.74 KB',
            created_date='2026-04-05 17:32',
            author='vadim.khitrin@plainid.com',
        )

        assert 'report.pdf' in tooltip.plain
        assert 'application/pdf' in tooltip.plain
        assert '416.74 KB' in tooltip.plain
        assert '2026-04-05 17:32' in tooltip.plain
        assert 'vadim.khitrin@plainid.com' in tooltip.plain

    def test_attachment_tooltip_provider_uses_loaded_attachment_metadata(self):
        attachment = Attachment(
            id='74914',
            filename='report.pdf',
            mime_type='application/pdf',
            size=426744,
            created=datetime(2026, 4, 5, 17, 32),
            author=JiraUser(
                account_id='user-1',
                active=True,
                display_name='Vadim Khitrin',
                email='vadim.khitrin@plainid.com',
            ),
        )
        markdown = SimpleNamespace(
            app=SimpleNamespace(
                screen=SimpleNamespace(
                    work_item_attachments_widget=SimpleNamespace(attachments=[attachment])
                )
            )
        )

        tooltip = AttachmentTooltipProvider(markdown).get('report.pdf')

        assert 'report.pdf' in tooltip.plain
        assert 'application/pdf' in tooltip.plain
        assert '416.74 KB' in tooltip.plain
        assert 'vadim.khitrin@plainid.com' in tooltip.plain

    def test_attachment_tooltip_provider_falls_back_when_attachment_is_unknown(self):
        markdown = SimpleNamespace(
            app=SimpleNamespace(
                screen=SimpleNamespace(work_item_attachments_widget=SimpleNamespace(attachments=[]))
            )
        )

        tooltip = AttachmentTooltipProvider(markdown).get(None)

        assert (
            tooltip.plain
            == f'Attachment\n\nClick to open attachments tab\n{ATTACHMENT_BROWSER_OPEN_HINT}'
        )

    def test_media_reference_is_not_emitted_as_markdown_link(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'mediaSingle',
                    'content': [
                        {
                            'type': 'media',
                            'attrs': {'type': 'file', 'id': '1', 'alt': 'native-click.png'},
                        }
                    ],
                }
            ],
        }

        replaced = replace_media_with_text(
            adf,
            media_attachment_details={
                '1': (
                    'native-click.png',
                    'https://example.atlassian.acme.net/secure/attachment/1/native-click.png',
                )
            },
        )
        text_node = replaced['content'][0]['content'][0]
        assert (
            text_node['text']
            == '[native-click.png](https://example.atlassian.acme.net/secure/attachment/1/native-click.png)'
        )

    def test_media_inline_without_filename_is_emitted_as_generic_attachment_text(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [
                        {'type': 'text', 'text': 'End result:'},
                        {'type': 'hardBreak'},
                        {'type': 'mediaInline', 'attrs': {'type': 'file', 'id': '1'}},
                    ],
                }
            ],
        }

        replaced = replace_media_with_text(
            adf,
            media_attachment_details={
                '1': (
                    'Attachment',
                    'https://example.atlassian.acme.net/secure/attachment/1/Attachment',
                )
            },
        )
        text_node = replaced['content'][0]['content'][2]
        assert (
            text_node['text']
            == '[Attachment](https://example.atlassian.acme.net/secure/attachment/1/Attachment)'
        )

    def test_extract_media_attachment_details_from_rendered_body(self):
        rendered_body = (
            '<a href="/rest/api/3/attachment/content/74914" '
            'data-attachment-name="API Telemetry_2026-03-29-2026-04-05.pdf" '
            'data-media-services-id="e2efe69b-4f1f-4ee0-a223-b915c960bbb5">'
            'API Telemetry_2026-03-29-2026-04-05.pdf</a>'
        )

        mappings = extract_media_attachment_details(
            rendered_body,
            base_url='https://example.atlassian.acme.net',
        )

        assert mappings == {
            'e2efe69b-4f1f-4ee0-a223-b915c960bbb5': (
                'API Telemetry_2026-03-29-2026-04-05.pdf',
                'https://example.atlassian.acme.net/secure/attachment/74914/API%20Telemetry_2026-03-29-2026-04-05.pdf',
            )
        }

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

    def test_attachment_link_opens_attachments_tab(
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
            run_before=click_attachment_link_and_open_attachments_tab,
        )
