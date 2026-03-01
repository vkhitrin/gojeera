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

        assert '@Test User' in markdown
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
