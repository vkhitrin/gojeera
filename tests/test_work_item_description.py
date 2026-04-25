import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from gojeera.internal.models.jira import (
    Attachment,
    JiraUser,
)
from gojeera.utils.markdown.adf_helpers import (
    extract_media_attachment_details,
    replace_media_with_text,
)
from gojeera.widgets.layout.record_list import RecordList
from gojeera.widgets.markdown.gojeera_markdown import (
    ATTACHMENT_BROWSER_OPEN_HINT,
    AttachmentTooltipProvider,
    GojeeraMarkdownFence,
    build_attachment_tooltip,
)

from .test_helpers import (
    find_markdown_link_offset,
    load_work_item_from_search,
    wait_for_markdown_paragraph_containing_text,
    wait_for_mount,
    wait_until,
    with_snapshot_assertion,
)


def media_attachment_details(
    attachment_id: str,
    attachment_name: str,
    attachment_url: str | None,
) -> dict[str, tuple[str, str | None]]:
    return {attachment_id: (attachment_name, attachment_url)}


def attachment_url(attachment_name: str) -> str:
    return f'https://example.atlassian.acme.net/secure/attachment/1/{attachment_name}'


def build_adf_doc(*content: dict) -> dict:
    return {'type': 'doc', 'version': 1, 'content': list(content)}


def assert_replaced_media_text(
    adf: dict,
    *,
    text_node_index: int,
    attachment_id: str,
    attachment_name: str,
    attachment_url: str,
) -> None:
    replaced = replace_media_with_text(
        adf,
        media_attachment_details=media_attachment_details(
            attachment_id,
            attachment_name,
            attachment_url,
        ),
    )
    text_node = replaced['content'][0]['content'][text_node_index]
    assert text_node['text'] == f'[{attachment_name}]({attachment_url})'


def assert_default_attachment_media_text(
    adf: dict,
    *,
    text_node_index: int,
    attachment_name: str,
) -> None:
    assert_replaced_media_text(
        adf,
        text_node_index=text_node_index,
        attachment_id='1',
        attachment_name=attachment_name,
        attachment_url=attachment_url(attachment_name),
    )


async def open_description_and_hover_internal_link(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-8')

    internal_link_paragraph = await wait_for_markdown_paragraph_containing_text(
        pilot,
        'Depends on motion alert validation in',
    )
    link_offset = find_markdown_link_offset(internal_link_paragraph, '/browse/ENG-7')
    await pilot.hover(internal_link_paragraph, offset=link_offset)
    await pilot.pause(1.0)

    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: pilot.app.focused_work_item_link_key == 'ENG-7', timeout=3.0)
    await asyncio.sleep(0.3)


async def load_focused_internal_jira_link_from_keybind(pilot):
    await open_description_and_hover_internal_link(pilot)
    assert pilot.app.focused_work_item_link_key == 'ENG-7'

    await pilot.press('ctrl+g')
    await pilot.app.workers.wait_for_complete()
    await wait_until(lambda: pilot.app.current_loaded_work_item_key == 'ENG-7', timeout=3.0)

    assert pilot.app.current_loaded_work_item_key == 'ENG-7'


async def open_description_and_hover_wrapped_link(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-8')

    wrapped_link_paragraph = await wait_for_markdown_paragraph_containing_text(
        pilot,
        'Nightly checklist URL:',
    )
    link_offset = find_markdown_link_offset(
        wrapped_link_paragraph,
        '/animatronics/release-playbook/nightly-checklist',
    )
    await pilot.hover(wrapped_link_paragraph, offset=link_offset)
    await pilot.pause(0.3)


async def click_attachment_link_and_open_attachments_tab(pilot):
    await wait_for_mount(pilot)
    await load_work_item_from_search(pilot, 'ENG-1')

    attachment_paragraph = await wait_for_markdown_paragraph_containing_text(
        pilot,
        'image-20260205-112310.png',
    )
    attachment_paragraph.action_attachment('image-20260205-112310.png')

    await wait_until(lambda: pilot.app.tabs.active == 'tab-attachments', timeout=3.0)
    await wait_until(
        lambda: (
            (record_list := pilot.app.screen.query_one(RecordList)).selected_record is not None
            and record_list.selected_record.title.startswith('image-20260205-112310.png')
        ),
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

    @pytest.mark.parametrize(
        ('adf', 'text_node_index', 'attachment_name'),
        [
            (
                build_adf_doc(
                    {
                        'type': 'mediaSingle',
                        'content': [
                            {
                                'type': 'media',
                                'attrs': {
                                    'type': 'file',
                                    'id': '1',
                                    'alt': 'native-click.png',
                                },
                            }
                        ],
                    }
                ),
                0,
                'native-click.png',
            ),
            (
                build_adf_doc(
                    {
                        'type': 'paragraph',
                        'content': [
                            {'type': 'text', 'text': 'End result:'},
                            {'type': 'hardBreak'},
                            {'type': 'mediaInline', 'attrs': {'type': 'file', 'id': '1'}},
                        ],
                    }
                ),
                2,
                'Attachment',
            ),
        ],
    )
    def test_media_references_are_emitted_as_attachment_text(
        self,
        adf: dict,
        text_node_index: int,
        attachment_name: str,
    ):
        assert_default_attachment_media_text(
            adf,
            text_node_index=text_node_index,
            attachment_name=attachment_name,
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

    @with_snapshot_assertion(open_description_and_hover_wrapped_link, terminal_size=(80, 40))
    def test_wrapped_link_snapshot(self): ...

    @with_snapshot_assertion(
        open_description_and_hover_internal_link,
        configure_app=lambda app: setattr(app, '_disable_tooltips', False),
    )
    def test_internal_jira_link_tooltip_snapshot(self): ...

    @with_snapshot_assertion(
        load_focused_internal_jira_link_from_keybind,
        configure_app=lambda app: setattr(app, '_disable_tooltips', False),
    )
    def test_loads_focused_internal_jira_link_from_keybind(self): ...

    @with_snapshot_assertion(click_attachment_link_and_open_attachments_tab)
    def test_attachment_link_opens_attachments_tab(self): ...
