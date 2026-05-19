from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown


def build_adf_doc(*content):
    return {'type': 'doc', 'version': 1, 'content': list(content)}


def build_media_node(media_id: str, *, alt: str | None = None):
    attrs = {'type': 'file', 'id': media_id}
    if alt is not None:
        attrs['alt'] = alt
    return {'type': 'media', 'attrs': attrs}


def build_media_inline_node(media_id: str):
    return {'type': 'mediaInline', 'attrs': {'id': media_id, 'collection': '', 'type': 'file'}}


def build_paragraph(*content):
    return {'type': 'paragraph', 'content': list(content)}


def build_text_node(text: str):
    return {'type': 'text', 'text': text}


def build_single_cell_table_doc(cell_text: str, *trailing_content: dict):
    return build_adf_doc(
        {
            'type': 'table',
            'content': [
                {
                    'type': 'tableRow',
                    'content': [
                        {
                            'type': 'tableCell',
                            'content': [build_paragraph(build_text_node(cell_text))],
                        }
                    ],
                }
            ],
        },
        *trailing_content,
    )


def build_media_single_doc(media_id: str, *, alt: str | None = None):
    return build_adf_doc({'type': 'mediaSingle', 'content': [build_media_node(media_id, alt=alt)]})


def build_media_group_doc(*media_ids: str):
    return build_adf_doc(
        {'type': 'mediaGroup', 'content': [build_media_node(media_id) for media_id in media_ids]}
    )


def build_media_inline_paragraph_doc(prefix_text: str, *media_ids: str):
    content: list[dict] = [build_text_node(prefix_text), {'type': 'hardBreak'}]
    for index, media_id in enumerate(media_ids):
        content.append(build_media_inline_node(media_id))
        if index < len(media_ids) - 1:
            content.append(build_text_node(' '))
    return build_adf_doc(build_paragraph(*content))


class TestAdfToMarkdownConversion:
    def test_convert_description(self, work_item_adf_description):
        markdown = convert_adf_to_markdown(work_item_adf_description)

        assert '# GitHub Flavored Markdown (GFM) All-in-One Test' in markdown
        assert '## 1. Alerts (Admonitions)' in markdown
        assert '## 2. Text Formatting' in markdown
        assert '## 3. Lists' in markdown
        assert '## 4. Code Blocks' in markdown
        assert '## 5. Table' in markdown
        assert '# Atlassian Document Format Test' in markdown

        assert '> [!NOTE]' in markdown
        assert '> [!TIP]' in markdown
        assert '> [!IMPORTANT]' in markdown
        assert '> [!WARNING]' in markdown
        assert '> [!CAUTION]' in markdown

        assert '**Bold Text**' in markdown
        assert '*Italic Text*' in markdown
        assert '~~Strikethrough~~' in markdown
        assert 'Inline Code' in markdown

        assert '☑  Completed task' in markdown
        assert '☐  Incomplete task' in markdown
        assert 'First item' in markdown
        assert 'Unordered sub-item' in markdown

        assert '```javascript' in markdown
        assert 'const greet = (name) =>' in markdown
        assert '```diff' in markdown

        assert 'Left Align' in markdown
        assert 'Center Align' in markdown
        assert 'Right Align' in markdown
        assert '|' in markdown

        assert '@Rook Hydra' in markdown
        assert '/jira/people/123456:abcd1234-1234-1234-1234-abcdef123456' in markdown

        assert '[date]2026-01-28' in markdown
        assert '[status:n]TEST' in markdown
        assert '[decision:d]Test' in markdown

        assert '😀' in markdown
        assert '🚀' in markdown

        assert '---' in markdown or '***' in markdown or '___' in markdown

    def test_single_row_single_cell_table_renders_parseable_markdown(self):
        adf = build_single_cell_table_doc('A')

        markdown = convert_adf_to_markdown(adf)

        assert markdown.strip() == '| A |\n|-|'

    def test_single_cell_table_with_escaped_pipe_renders_parseable_markdown(self):
        adf = build_single_cell_table_doc('Sample field | Sample value')

        markdown = convert_adf_to_markdown(adf)

        assert markdown.strip() == '| Sample field \\| Sample value |\n|-|'

    def test_single_cell_table_is_terminated_before_next_paragraph(self):
        adf = build_single_cell_table_doc(
            'A',
            build_paragraph(build_text_node('Follow-up details go here')),
        )

        markdown = convert_adf_to_markdown(adf)

        assert '| A |\n|-|\n\nFollow-up details go here' in markdown

    def test_jira_browse_link_markdown_is_preserved(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [
                        {
                            'type': 'text',
                            'text': 'ENG-1',
                            'marks': [
                                {
                                    'type': 'link',
                                    'attrs': {
                                        'href': 'https://example.atlassian.acme.net/browse/ENG-1'
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        markdown = convert_adf_to_markdown(adf, base_url='https://example.atlassian.acme.net')

        assert markdown.strip() == '[ENG-1](https://example.atlassian.acme.net/browse/ENG-1)'

    def test_zero_width_prefixed_link_text_is_not_misparsed_as_date(self):
        adf = build_adf_doc(
            build_paragraph(
                build_text_node('Source: '),
                {
                    'type': 'text',
                    'text': '\u200bhttps://global-services.us1.plainid.io/',
                    'marks': [
                        {
                            'type': 'link',
                            'attrs': {'href': 'https://global-services.us1.plainid.io/'},
                        }
                    ],
                },
            )
        )

        markdown = convert_adf_to_markdown(adf)

        assert '[date]https://global-services.us1.plainid.io/' not in markdown
        assert 'global-services.us1.plainid.io' in markdown

    def test_media_single_renders_internal_attachment_link(self):
        adf = build_media_single_doc('attachment-1', alt='image-20260205-112310.png')

        markdown = convert_adf_to_markdown(
            adf,
            media_attachment_details={
                'attachment-1': (
                    'image-20260205-112310.png',
                    'https://example.atlassian.acme.net/secure/attachment/66811/image-20260205-112310.png',
                )
            },
        )

        assert (
            markdown.strip()
            == '[image-20260205-112310.png](https://example.atlassian.acme.net/secure/attachment/66811/image-20260205-112310.png)'
        )

    def test_media_inline_without_filename_renders_generic_attachment_link(self):
        adf = build_media_inline_paragraph_doc('End result:', 'media-1')

        markdown = convert_adf_to_markdown(
            adf,
            media_attachment_details={
                'media-1': (
                    'Attachment',
                    'https://example.atlassian.acme.net/secure/attachment/66811/Attachment',
                )
            },
        )

        assert (
            markdown.strip()
            == 'End result:  \n[Attachment](https://example.atlassian.acme.net/secure/attachment/66811/Attachment)'
        )

    def test_media_inline_uses_rendered_body_to_resolve_attachment_filename(self):
        adf = build_media_inline_paragraph_doc(
            'End result:', 'e2efe69b-4f1f-4ee0-a223-b915c960bbb5'
        )
        rendered_body = (
            '<p>End result:<br/>'
            '<span class="nobr"><a href="/rest/api/3/attachment/content/74914" '
            'data-attachment-name="API Telemetry_2026-03-29-2026-04-05.pdf" '
            'data-media-services-id="e2efe69b-4f1f-4ee0-a223-b915c960bbb5" '
            'rel="noreferrer">API Telemetry_2026-03-29-2026-04-05.pdf</a></span></p>'
        )

        markdown = convert_adf_to_markdown(
            adf,
            base_url='https://example.atlassian.acme.net',
            rendered_body=rendered_body,
        )

        assert markdown.strip() == (
            'End result:  \n'
            '[API Telemetry_2026-03-29-2026-04-05.pdf](https://example.atlassian.acme.net/secure/attachment/74914/API%20Telemetry_2026-03-29-2026-04-05.pdf)'
        )

    def test_media_group_renders_one_attachment_link_per_media_node(self):
        adf = build_media_group_doc('attachment-1', 'attachment-2')

        markdown = convert_adf_to_markdown(
            adf,
            media_attachment_details={
                'attachment-1': (
                    'rollout-diagram.png',
                    'https://example.atlassian.acme.net/secure/attachment/20001/rollout-diagram.png',
                ),
                'attachment-2': (
                    'field-notes.pdf',
                    'https://example.atlassian.acme.net/secure/attachment/20002/field-notes.pdf',
                ),
            },
        )

        assert markdown.strip() == (
            '[rollout-diagram.png](https://example.atlassian.acme.net/secure/attachment/20001/rollout-diagram.png)\n\n'
            '[field-notes.pdf](https://example.atlassian.acme.net/secure/attachment/20002/field-notes.pdf)'
        )

    def test_media_inline_falls_back_to_ordered_attachment_details(self):
        adf = build_adf_doc(
            build_paragraph(
                build_text_node('Please review the logs'),
                {'type': 'hardBreak'},
                build_media_inline_node('inline-1'),
                build_text_node(' '),
                build_media_inline_node('inline-2'),
            ),
            {
                'type': 'mediaSingle',
                'attrs': {'layout': 'align-start'},
                'content': [build_media_node('image-1', alt='image-20260423-145323.png')],
            },
        )

        markdown = convert_adf_to_markdown(
            adf,
            media_attachment_details={
                'image-20260423-145323.png': (
                    'image-20260423-145323.png',
                    'https://example.atlassian.acme.net/secure/attachment/10003/image-20260423-145323.png',
                )
            },
            ordered_attachment_details=[
                (
                    'server_0422.zip',
                    'https://example.atlassian.acme.net/secure/attachment/10001/server_0422.zip',
                ),
                (
                    'pip_0422.zip',
                    'https://example.atlassian.acme.net/secure/attachment/10002/pip_0422.zip',
                ),
                (
                    'image-20260423-145323.png',
                    'https://example.atlassian.acme.net/secure/attachment/10003/image-20260423-145323.png',
                ),
            ],
        )

        assert markdown.strip() == (
            'Please review the logs  \n'
            '[server_0422.zip](https://example.atlassian.acme.net/secure/attachment/10001/server_0422.zip) '
            '[pip_0422.zip](https://example.atlassian.acme.net/secure/attachment/10002/pip_0422.zip)\n\n'
            '[image-20260423-145323.png](https://example.atlassian.acme.net/secure/attachment/10003/image-20260423-145323.png)'
        )

    def test_code_block_strips_ansi_escape_sequences_from_adf_text(self):
        adf = build_adf_doc(
            {
                'type': 'codeBlock',
                'content': [
                    build_text_node(
                        'Apr 29 13:23:51.815  \x1b[34mINFO\x1b[0;39m main\n'
                        'Apr 29 13:23:52.207  \x1b[31mWARN\x1b[0;39m main'
                    )
                ],
            },
            build_paragraph(
                build_text_node('status moves to'),
                {
                    'type': 'text',
                    'text': ' Waiting For Tag ',
                    'marks': [{'type': 'code'}],
                },
                build_text_node('.'),
            ),
        )

        markdown = convert_adf_to_markdown(adf)

        assert '\x1b' not in markdown
        assert 'INFO main' in markdown
        assert 'WARN main' in markdown
        assert 'status moves to `Waiting For Tag`.' in markdown
        assert '`` Waiting For Tag ``' not in markdown
