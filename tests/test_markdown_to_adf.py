from gojeera.utils.adf_helpers import text_to_adf


class TestMarkdownToAdfConversion:
    def test_convert_markdown(self, work_item_markdown_description):
        adf = text_to_adf(work_item_markdown_description)

        assert adf['type'] == 'doc'
        assert adf['version'] == 1

        content = adf['content']

        heading_types = [node for node in content if node.get('type') == 'heading']
        assert len(heading_types) >= 7

        heading_texts = []
        for heading in heading_types:
            if heading.get('content'):
                for text_node in heading['content']:
                    if text_node.get('type') == 'text':
                        heading_texts.append(text_node['text'])

        assert 'GitHub Flavored Markdown (GFM) All-in-One Test' in heading_texts
        assert '1. Alerts (Admonitions)' in heading_texts
        assert '2. Text Formatting' in heading_texts
        assert '3. Lists' in heading_texts
        assert '4. Code Blocks' in heading_texts
        assert '5. Table' in heading_texts
        assert 'Atlassian Document Format Test' in heading_texts

        panels = [node for node in content if node.get('type') == 'panel']
        panel_types = [p.get('attrs', {}).get('panelType') for p in panels]

        assert 'info' in panel_types
        assert 'success' in panel_types
        assert 'note' in panel_types
        assert 'warning' in panel_types
        assert 'error' in panel_types

        paragraphs = [node for node in content if node.get('type') == 'paragraph']
        all_text_nodes = []
        for para in paragraphs:
            if para.get('content'):
                all_text_nodes.extend(para['content'])

        bold_nodes = [
            n for n in all_text_nodes if any(m.get('type') == 'strong' for m in n.get('marks', []))
        ]
        assert len(bold_nodes) > 0

        italic_nodes = [
            n for n in all_text_nodes if any(m.get('type') == 'em' for m in n.get('marks', []))
        ]
        assert len(italic_nodes) > 0

        strike_nodes = [
            n for n in all_text_nodes if any(m.get('type') == 'strike' for m in n.get('marks', []))
        ]
        assert len(strike_nodes) > 0

        code_nodes = [
            n for n in all_text_nodes if any(m.get('type') == 'code' for m in n.get('marks', []))
        ]
        assert len(code_nodes) > 0

        task_lists = [node for node in content if node.get('type') == 'taskList']
        assert len(task_lists) > 0

        all_task_items = []
        for task_list in task_lists:
            all_task_items.extend(task_list.get('content', []))

        states = [item.get('attrs', {}).get('state') for item in all_task_items]
        assert 'DONE' in states
        assert 'TODO' in states

        def find_nodes_recursive(nodes, node_type):
            found = []
            for node in nodes:
                if node.get('type') == node_type:
                    found.append(node)
                if 'content' in node:
                    found.extend(find_nodes_recursive(node['content'], node_type))
            return found

        bullet_lists = find_nodes_recursive(content, 'bulletList')
        assert len(bullet_lists) > 0

        ordered_lists = find_nodes_recursive(content, 'orderedList')
        assert len(ordered_lists) > 0

        code_blocks = [node for node in content if node.get('type') == 'codeBlock']
        assert len(code_blocks) > 0

        code_languages = [cb.get('attrs', {}).get('language') for cb in code_blocks]
        assert 'javascript' in code_languages
        assert 'diff' in code_languages

        tables = [node for node in content if node.get('type') == 'table']
        assert len(tables) > 0

        rules = [node for node in content if node.get('type') == 'rule']
        assert len(rules) > 0

    def test_convert_compact_single_cell_table(self):
        markdown = '| A |\n|-|'

        adf = text_to_adf(markdown)

        assert adf['type'] == 'doc'
        assert adf['version'] == 1
        assert len(adf['content']) == 1

        table = adf['content'][0]
        assert table['type'] == 'table'
        assert len(table['content']) == 1

        table_row = table['content'][0]
        assert table_row['type'] == 'tableRow'
        assert len(table_row['content']) == 1

        cell = table_row['content'][0]
        assert cell['type'] == 'tableHeader'
        assert cell['content'][0]['type'] == 'paragraph'
        assert cell['content'][0]['content'][0]['text'] == 'A'
