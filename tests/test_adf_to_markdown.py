from gojeera.utils.adf_helpers import convert_adf_to_markdown


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
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'table',
                    'content': [
                        {
                            'type': 'tableRow',
                            'content': [
                                {
                                    'type': 'tableCell',
                                    'content': [
                                        {
                                            'type': 'paragraph',
                                            'content': [{'type': 'text', 'text': 'A'}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        markdown = convert_adf_to_markdown(adf)

        assert markdown.strip() == '| A |\n|-|'

    def test_single_cell_table_with_escaped_pipe_renders_parseable_markdown(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'table',
                    'content': [
                        {
                            'type': 'tableRow',
                            'content': [
                                {
                                    'type': 'tableCell',
                                    'content': [
                                        {
                                            'type': 'paragraph',
                                            'content': [
                                                {
                                                    'type': 'text',
                                                    'text': 'Sample field | Sample value',
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        markdown = convert_adf_to_markdown(adf)

        assert markdown.strip() == '| Sample field \\| Sample value |\n|-|'

    def test_single_cell_table_is_terminated_before_next_paragraph(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'table',
                    'content': [
                        {
                            'type': 'tableRow',
                            'content': [
                                {
                                    'type': 'tableCell',
                                    'content': [
                                        {
                                            'type': 'paragraph',
                                            'content': [{'type': 'text', 'text': 'A'}],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
                {
                    'type': 'paragraph',
                    'content': [{'type': 'text', 'text': 'Follow-up details go here'}],
                },
            ],
        }

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

    def test_media_single_renders_internal_attachment_link(self):
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'mediaSingle',
                    'content': [
                        {
                            'type': 'media',
                            'attrs': {
                                'type': 'file',
                                'id': 'attachment-1',
                                'alt': 'image-20260205-112310.png',
                            },
                        }
                    ],
                }
            ],
        }

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
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [
                        {'type': 'text', 'text': 'End result:'},
                        {'type': 'hardBreak'},
                        {
                            'type': 'mediaInline',
                            'attrs': {'id': 'media-1', 'collection': '', 'type': 'file'},
                        },
                    ],
                }
            ],
        }

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
        adf = {
            'type': 'doc',
            'version': 1,
            'content': [
                {
                    'type': 'paragraph',
                    'content': [
                        {'type': 'text', 'text': 'End result:'},
                        {'type': 'hardBreak'},
                        {
                            'type': 'mediaInline',
                            'attrs': {
                                'id': 'e2efe69b-4f1f-4ee0-a223-b915c960bbb5',
                                'collection': '',
                                'type': 'file',
                            },
                        },
                    ],
                }
            ],
        }
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
