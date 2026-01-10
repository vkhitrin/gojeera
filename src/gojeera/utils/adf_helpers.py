import re
from typing import cast

from atlas_doc_parser.api import parse_node
from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin


def replace_media_with_text(adf: dict) -> dict:
    """Replace mediaSingle nodes with inline text nodes showing attachment reference.

    Args:
        adf: ADF document structure

    Returns:
        Modified ADF with mediaSingle replaced by text nodes
    """
    if not isinstance(adf, dict):
        return adf

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for node in adf['content']:
            if node.get('type') == 'mediaSingle':
                media_content = node.get('content', [])
                for media in media_content:
                    if isinstance(media, dict) and media.get('type') == 'media':
                        attrs = media.get('attrs', {})
                        filename = attrs.get('alt', 'unknown')

                        para_node = {
                            'type': 'paragraph',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': f'(See file "{filename}" in attachments tab)',
                                    'marks': [{'type': 'em'}],
                                }
                            ],
                        }
                        new_content.append(para_node)
                        break
            else:
                new_content.append(replace_media_with_text(node))

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def replace_mentions_with_links(adf: dict, base_url: str | None) -> dict:
    """Replace mention nodes with text nodes containing Markdown links.
    Args:
        adf: ADF document structure
        base_url: Base URL of Jira instance (e.g., 'https://example.atlassian.net')
                  Used to construct the full profile URL

    Returns:
        Modified ADF with mention nodes replaced by text nodes with Markdown link syntax
    """
    if not isinstance(adf, dict):
        return adf

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for node in adf['content']:
            if node.get('type') == 'mention':
                attrs = node.get('attrs', {})
                account_id = attrs.get('id', '')

                text = attrs.get('text') or attrs.get('displayName', '')

                if account_id and text:
                    if base_url:
                        url = f'{base_url.rstrip("/")}/jira/people/{account_id}'
                    else:
                        url = f'/jira/people/{account_id}'

                    markdown_link = f'[{text}]({url})'
                    text_node = {
                        'type': 'text',
                        'text': markdown_link,
                    }

                    if 'marks' in node:
                        text_node['marks'] = node['marks']

                    new_content.append(text_node)
                else:
                    new_content.append(replace_mentions_with_links(node, base_url))
            else:
                new_content.append(replace_mentions_with_links(node, base_url))

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def fix_adf_text_with_marks(adf: dict) -> dict:
    """Preprocess ADF to fix atlas_doc_parser issues.

    Args:
        adf: ADF structure (dict or any type)

    Returns:
        Fixed ADF structure with trailing spaces removed from marked text
    """
    if not isinstance(adf, dict):
        return adf

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for i, node in enumerate(adf['content']):
            node = fix_adf_text_with_marks(node)

            if node.get('type') == 'text' and 'marks' in node and 'text' in node:
                marks = node.get('marks', [])
                has_strong_or_em = any(
                    m.get('type') in ('strong', 'em') for m in marks if isinstance(m, dict)
                )

                if has_strong_or_em:
                    original_text = node['text']
                    stripped_text = original_text.strip()
                    had_trailing_space = original_text.endswith(' ')
                    had_leading_space = original_text.startswith(' ')

                    if stripped_text != original_text:
                        node = node.copy()
                        node['text'] = stripped_text

                        if had_leading_space and i > 0:
                            new_content.append({'type': 'text', 'text': ' '})

                        new_content.append(node)

                        if had_trailing_space and i < len(adf['content']) - 1:
                            new_content.append({'type': 'text', 'text': ' '})
                        continue

            new_content.append(node)

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def fix_codeblock_in_list(adf: dict) -> dict:
    """Fix codeBlock nodes nested inside listItem nodes due to atlas_doc_parser issues.
    Args:
        adf: ADF document structure

    Returns:
        Modified ADF with codeBlocks extracted from listItems and empty items removed
    """
    if not isinstance(adf, dict):
        return adf

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []
        extracted_codeblocks = []

        for node in adf['content']:
            node = fix_codeblock_in_list(node)

            if node.get('type') in ('bulletList', 'orderedList'):
                list_items = node.get('content', [])
                new_list_items = []

                for item in list_items:
                    if item.get('type') == 'listItem':
                        item_content = item.get('content', [])
                        new_item_content = []
                        has_codeblock = False

                        for child in item_content:
                            if child.get('type') == 'codeBlock':
                                has_codeblock = True

                                extracted_codeblocks.append(child)
                            else:
                                new_item_content.append(child)

                        if not has_codeblock or new_item_content:
                            item = item.copy()
                            item['content'] = new_item_content
                            new_list_items.append(item)
                    else:
                        new_list_items.append(item)

                if new_list_items:
                    node = node.copy()
                    node['content'] = new_list_items
                    new_content.append(node)
            else:
                new_content.append(node)

            new_content.extend(extracted_codeblocks)
            extracted_codeblocks = []

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def _render_task_checkboxes(text: str) -> str:
    """Replace GFM task list markers with UTF-8 checkbox characters.
    Args:
        text: Markdown text with task list markers

    Returns:
        Text with task list markers replaced by UTF-8 checkboxes in separate paragraphs
    """

    text = re.sub(r'([^\n\s-])(-\s+\[[ xX]\])', r'\1\n    \2', text)

    text = re.sub(r'([^\n\s-])(-\s+(?!\[))', r'\1\n    \2', text)

    lines = text.split('\n')
    fixed_lines = []
    in_nested_context = False

    for i, line in enumerate(lines):
        is_unindented_bullet = re.match(r'^-\s+', line)

        is_root_ordered = re.match(r'^\d+\.\s+', line)

        is_already_indented = line.startswith(' ')

        if is_unindented_bullet:
            if in_nested_context:
                fixed_lines.append('    ' + line)
                continue
            elif i > 0:
                prev_line = lines[i - 1]
                if re.match(r'^\d+\.\s+', prev_line):
                    in_nested_context = True
                    fixed_lines.append('    ' + line)
                    continue
        elif is_root_ordered:
            in_nested_context = False
        elif not is_already_indented and line.strip() == '':
            pass
        elif not is_already_indented and line.strip() != '' and not is_unindented_bullet:
            in_nested_context = False

        fixed_lines.append(line)
    text = '\n'.join(fixed_lines)

    lines = text.split('\n')
    result_lines = []

    for i, line in enumerate(lines):
        match = re.match(r'^(\s*)-\s+\[([ xX])\](.*)$', line)
        if match:
            indent, checkbox_state, rest = match.groups()

            if checkbox_state == ' ':
                result_lines.append(f'{indent}☐{rest}')
            else:
                result_lines.append(f'{indent}☑{rest}')

            if i < len(lines) - 1:
                result_lines.append('')
        else:
            result_lines.append(line)

    return '\n'.join(result_lines)


def _convert_status_markers_to_inline_code(markdown: str) -> str:
    """Convert invisible status markers to inline code format.

    Args:
        markdown: Markdown text with invisible status markers

    Returns:
        Markdown with status markers converted to inline code format
    """

    def replace_match(match):
        color_code = match.group(1)
        status_text = match.group(2)
        return f'`[status:{color_code}]{status_text}`'

    return re.sub(r'\u200c([nrbgypt])\u200d([^\u200c]+)\u200c', replace_match, markdown)


def _convert_date_markers_to_inline_code(markdown: str) -> str:
    """Convert invisible date markers to inline code format.

    Args:
        markdown: Markdown text with invisible date markers

    Returns:
        Markdown with date markers converted to inline code format
    """

    def replace_match(match):
        date_text = match.group(1)
        return f'`[date]{date_text}`'

    return re.sub(r'\u200b([^\u200b]+)\u200b', replace_match, markdown)


def _convert_decision_markers_to_inline_code(markdown: str) -> str:
    """Convert invisible decision markers to inline code format with ⤷ prefix.

    Args:
        markdown: Markdown text with invisible decision markers

    Returns:
        Markdown with decision markers converted to inline code format
    """

    def replace_match(match):
        state_code = match.group(1)
        decision_text = match.group(2)
        return f'`[decision:{state_code}]{decision_text}`'

    return re.sub(r'\u200e([dau])\u200f([^\u200e]+)\u200e', replace_match, markdown)


def _convert_panels_to_alerts(markdown: str) -> str:
    """Convert atlas_doc_parser panel blockquotes to alert blockquotes.

    Args:
        markdown: Markdown text potentially containing panel blockquotes

    Returns:
        Markdown with panels converted to alert format
    """

    panel_to_alert = {
        'INFO': 'NOTE',
        'SUCCESS': 'TIP',
        'NOTE': 'IMPORTANT',
        'WARNING': 'WARNING',
        'ERROR': 'CAUTION',
    }

    lines = markdown.split('\n')
    result_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        match = re.match(r'^>\s*\*\*(INFO|SUCCESS|NOTE|WARNING|ERROR)\*\*\s*$', line)
        if match:
            panel_type = match.group(1)
            alert_type = panel_to_alert.get(panel_type, 'NOTE')

            result_lines.append(f'> [!{alert_type}]')

            if i + 1 < len(lines) and re.match(r'^>\s*$', lines[i + 1]):
                i += 1

            i += 1
            continue

        result_lines.append(line)
        i += 1

    return '\n'.join(result_lines)


def fix_ordered_list_attrs(adf: dict) -> dict:
    """Add missing attrs to orderedList elements.

    Args:
        adf: ADF structure (dict or any type)

    Returns:
        Fixed ADF structure with attrs added to orderedList elements
    """
    if not isinstance(adf, dict):
        return adf

    if adf.get('type') == 'orderedList' and 'attrs' not in adf:
        adf['attrs'] = {}

    if 'content' in adf and isinstance(adf['content'], list):
        adf['content'] = [fix_ordered_list_attrs(node) for node in adf['content']]

    return adf


def replace_status_with_colored_text(adf: dict) -> dict:
    """Replace status nodes with text nodes that will be styled with color-specific backgrounds.

    Args:
        adf: ADF document structure

    Returns:
        Modified ADF with status nodes replaced by marked text nodes
    """
    if not isinstance(adf, dict):
        return adf

    color_map = {
        'neutral': 'n',
        'red': 'r',
        'blue': 'b',
        'green': 'g',
        'yellow': 'y',
        'purple': 'p',
        'teal': 't',
    }

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for node in adf['content']:
            if node.get('type') == 'status':
                attrs = node.get('attrs', {})
                status_text = attrs.get('text', '')
                status_color = attrs.get('color', 'neutral')

                if status_text:
                    color_code = color_map.get(status_color, 'n')

                    text_node = {
                        'type': 'text',
                        'text': f'\u200c{color_code}\u200d{status_text}\u200c',
                    }

                    if 'marks' in node:
                        text_node['marks'] = node['marks']

                    new_content.append(text_node)
                else:
                    fallback_node = {'type': 'text', 'text': '\u200cn\u200d[no status]\u200c'}
                    if 'marks' in node:
                        fallback_node['marks'] = node['marks']
                    new_content.append(fallback_node)
            else:
                new_content.append(replace_status_with_colored_text(node))

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def replace_date_with_colored_text(adf: dict) -> dict:
    """Replace date nodes with text nodes that will be styled with background.

    Args:
        adf: ADF document structure

    Returns:
        Modified ADF with date nodes replaced by marked text nodes
    """
    from datetime import datetime

    if not isinstance(adf, dict):
        return adf

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for node in adf['content']:
            if node.get('type') == 'date':
                attrs = node.get('attrs', {})
                timestamp_ms = attrs.get('timestamp')

                if timestamp_ms:
                    try:
                        timestamp_s = int(timestamp_ms) / 1000
                        date_str = datetime.fromtimestamp(timestamp_s).strftime('%Y-%m-%d')

                        text_node = {'type': 'text', 'text': f'\u200b{date_str}\u200b'}

                        if 'marks' in node:
                            text_node['marks'] = node['marks']

                        new_content.append(text_node)
                    except (ValueError, OSError, OverflowError):
                        fallback_node = {
                            'type': 'text',
                            'text': '\u200b[invalid date]\u200b',
                        }
                        if 'marks' in node:
                            fallback_node['marks'] = node['marks']
                        new_content.append(fallback_node)
                else:
                    fallback_node = {'type': 'text', 'text': '\u200b[no date]\u200b'}
                    if 'marks' in node:
                        fallback_node['marks'] = node['marks']
                    new_content.append(fallback_node)
            else:
                new_content.append(replace_date_with_colored_text(node))

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def replace_decision_with_styled_text(adf: dict) -> dict:
    """Replace decisionItem nodes with text nodes marked with ⤷ prefix.

    Args:
        adf: ADF document structure

    Returns:
        Modified ADF with decisionItem nodes replaced by marked text nodes
        and decisionList nodes converted to blockquote
    """
    if not isinstance(adf, dict):
        return adf

    state_map = {
        'DECIDED': 'd',
        'ACKNOWLEDGED': 'a',
        'UP_FOR_DISCUSSION': 'u',
    }

    if adf.get('type') == 'decisionList':
        decision_items = adf.get('content', [])
        paragraphs = []

        for item in decision_items:
            if item.get('type') == 'decisionItem':
                attrs = item.get('attrs', {})
                state = attrs.get('state', 'DECIDED')
                state_code = state_map.get(state, 'd')

                decision_content = item.get('content', [])
                decision_text = ''

                for subitem in decision_content:
                    if subitem.get('type') == 'text':
                        decision_text += subitem.get('text', '')
                    elif isinstance(subitem, dict) and 'content' in subitem:
                        for nested in subitem.get('content', []):
                            if nested.get('type') == 'text':
                                decision_text += nested.get('text', '')

                if decision_text:
                    paragraph = {
                        'type': 'paragraph',
                        'content': [
                            {
                                'type': 'text',
                                'text': f'\u200e{state_code}\u200f{decision_text.strip()}\u200e',
                            }
                        ],
                    }
                    paragraphs.append(paragraph)

        return {'type': 'blockquote', 'content': paragraphs}

    if 'content' in adf and isinstance(adf['content'], list):
        new_content = []

        for node in adf['content']:
            if node.get('type') == 'decisionItem':
                attrs = node.get('attrs', {})
                state = attrs.get('state', 'DECIDED')
                state_code = state_map.get(state, 'd')

                decision_content = node.get('content', [])
                decision_text = ''

                for item in decision_content:
                    if item.get('type') == 'text':
                        decision_text += item.get('text', '')
                    elif isinstance(item, dict) and 'content' in item:
                        for subitem in item.get('content', []):
                            if subitem.get('type') == 'text':
                                decision_text += subitem.get('text', '')

                if decision_text:
                    text_node = {
                        'type': 'text',
                        'text': f'\u200e{state_code}\u200f{decision_text.strip()}\u200e',
                    }

                    if 'marks' in node:
                        text_node['marks'] = node['marks']

                    new_content.append(text_node)
                else:
                    fallback_node = {'type': 'text', 'text': '\u200ed\u200f[no decision]\u200e'}
                    if 'marks' in node:
                        fallback_node['marks'] = node['marks']
                    new_content.append(fallback_node)
            else:
                new_content.append(replace_decision_with_styled_text(node))

        adf = adf.copy()
        adf['content'] = new_content

    return adf


def convert_adf_to_markdown(value: dict, base_url: str | None = None) -> str:
    """Convert Atlassian Document Format (ADF) to Markdown.

    Args:
        value: The value to convert - can be ADF dict, string, or None
        base_url: Optional base URL of Jira instance for formatting mentions as links
                  (e.g., 'https://example.atlassian.net')
                  Note: base_url is stored in invisible markers and used by the
                  mdit_adf_mentions plugin during rendering

    Returns:
        Markdown string representation with visual checkboxes for task lists
        and invisible mention markers that will be converted to links during rendering
    """

    fixed_value = replace_media_with_text(value)
    fixed_value = fix_adf_text_with_marks(fixed_value)
    fixed_value = fix_codeblock_in_list(fixed_value)
    fixed_value = fix_ordered_list_attrs(fixed_value)
    fixed_value = replace_mentions_with_links(fixed_value, base_url)
    fixed_value = replace_date_with_colored_text(fixed_value)
    fixed_value = replace_status_with_colored_text(fixed_value)
    fixed_value = replace_decision_with_styled_text(fixed_value)
    markdown = parse_node(fixed_value).to_markdown(ignore_error=True)

    markdown = re.sub(r'(```\w*\n.*?)\n\n```', r'\1\n```', markdown, flags=re.DOTALL)

    markdown = markdown.lstrip('\n')

    markdown = _convert_status_markers_to_inline_code(markdown)

    markdown = _convert_date_markers_to_inline_code(markdown)

    markdown = _convert_decision_markers_to_inline_code(markdown)

    markdown = _render_task_checkboxes(markdown)

    markdown = _convert_panels_to_alerts(markdown)

    return markdown


def _is_task_list(tokens: list, start_index: int) -> bool:
    """Check if a bullet list is a task list using tasklists plugin attributes.

    The tasklists plugin adds 'class="contains-task-list"' attribute to
    bullet_list_open tokens that contain task list items.

    Args:
        tokens: List of markdown-it Token objects
        start_index: Index of bullet_list_open token

    Returns:
        True if the list is a task list (has contains-task-list class)
    """
    if start_index < len(tokens):
        token = tokens[start_index]
        if token.type == 'bullet_list_open':
            class_attr = token.attrGet('class')
            return class_attr == 'contains-task-list'
    return False


def _convert_task_list_tokens(
    tokens: list, start_index: int, track_warnings: bool = False
) -> tuple[list[dict], int] | tuple[list[dict], int, list[str]]:
    """Convert markdown task list tokens to ADF taskItem nodes.

    Args:
        tokens: List of markdown-it Token objects
        start_index: Starting index in tokens list
        track_warnings: If True, returns tuple of (task_items, end_index, warnings)

    Returns:
        Tuple of (task_items, end_index), or (task_items, end_index, warnings) if track_warnings=True
    """
    task_items = []
    warnings: list[str] = []
    i = start_index + 1

    while i < len(tokens):
        token = tokens[i]

        if token.type == 'bullet_list_close':
            break
        elif token.type == 'list_item_open':
            class_attr = token.attrGet('class')
            if class_attr != 'task-list-item':
                i += 1
                depth = 1
                while i < len(tokens) and depth > 0:
                    if tokens[i].type == 'list_item_open':
                        depth += 1
                    elif tokens[i].type == 'list_item_close':
                        depth -= 1
                    i += 1
                continue

            i += 1
            item_content = []
            task_state = 'TODO'

            while i < len(tokens) and tokens[i].type != 'list_item_close':
                inner_token = tokens[i]

                if inner_token.type == 'paragraph_open':
                    i += 1
                    inline_token = tokens[i]

                    text_children = []
                    if inline_token.children and len(inline_token.children) > 0:
                        first_child = inline_token.children[0]
                        if first_child.type == 'html_inline':
                            if 'checked="checked"' in first_child.content:
                                task_state = 'DONE'
                            else:
                                task_state = 'TODO'

                            text_children = inline_token.children[1:]
                        else:
                            text_children = inline_token.children
                    else:
                        text_children = []

                    if text_children:
                        if track_warnings:
                            inline_result = cast(
                                tuple[list[dict], list[str]],
                                _convert_inline_tokens(text_children, track_warnings=True),
                            )
                            para_content, inline_warnings = inline_result
                            warnings.extend(inline_warnings)
                        else:
                            para_content = _convert_inline_tokens(text_children)

                        if para_content:
                            item_content.extend(para_content)

                    i += 2

                else:
                    i += 1

            task_items.append(
                {
                    'type': 'taskItem',
                    'attrs': {'localId': '', 'state': task_state},
                    'content': item_content,
                }
            )
            i += 1

        else:
            i += 1

    if track_warnings:
        return (task_items, i + 1, warnings)
    else:
        return (task_items, i + 1)


def _convert_blockquote_tokens(
    tokens: list, start_index: int, track_warnings: bool = False
) -> tuple[dict, int] | tuple[dict, int, list[str]]:
    """Convert markdown blockquote tokens to ADF blockquote or panel nodes.

    Args:
        tokens: List of markdown-it Token objects
        start_index: Starting index in tokens list
        track_warnings: If True, returns tuple of (node, end_index, warnings)

    Returns:
        Tuple of (blockquote_node, end_index), or (node, end_index, warnings) if track_warnings=True
    """
    warnings: list[str] = []
    i = start_index + 1
    blockquote_content = []

    is_alert = False
    alert_type = None
    alert_content_starts_at = -1

    temp_i = i
    while temp_i < len(tokens):
        token = tokens[temp_i]
        if token.type == 'blockquote_close':
            break
        if token.type == 'paragraph_open':
            if temp_i + 1 < len(tokens) and tokens[temp_i + 1].type == 'inline':
                inline_content = tokens[temp_i + 1].content.strip()

                alert_match = re.match(r'\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', inline_content)
                if alert_match:
                    is_alert = True
                    alert_type_text = alert_match.group(1)

                    alert_type_map = {
                        'NOTE': 'info',
                        'TIP': 'success',
                        'IMPORTANT': 'note',
                        'WARNING': 'warning',
                        'CAUTION': 'error',
                    }
                    alert_type = alert_type_map.get(alert_type_text, 'info')
                    alert_content_starts_at = temp_i
                    break
        temp_i += 1

    while i < len(tokens):
        token = tokens[i]

        if token.type == 'blockquote_close':
            break

        if is_alert and i == alert_content_starts_at and token.type == 'paragraph_open':
            i += 1
            inline_token = tokens[i]

            if inline_token.children:
                filtered_children = []
                skip_next_softbreak = False

                for child in inline_token.children:
                    if child.type == 'text' and child.content.strip().startswith('[!'):
                        skip_next_softbreak = True
                        continue
                    if skip_next_softbreak and child.type == 'softbreak':
                        skip_next_softbreak = False
                        continue
                    filtered_children.append(child)

                if filtered_children:
                    if track_warnings:
                        inline_result = cast(
                            tuple[list[dict], list[str]],
                            _convert_inline_tokens(filtered_children, track_warnings=True),
                        )
                        para_content, inline_warnings = inline_result
                        warnings.extend(inline_warnings)
                    else:
                        para_content = _convert_inline_tokens(filtered_children)

                    if para_content:
                        blockquote_content.append({'type': 'paragraph', 'content': para_content})

            i += 2
            continue

        if token.type in (
            'paragraph_open',
            'heading_open',
            'bullet_list_open',
            'ordered_list_open',
            'fence',
            'blockquote_open',
        ):
            if track_warnings:
                nested_result = cast(
                    tuple[list[dict], list[str]],
                    _convert_tokens_to_adf([token] + tokens[i + 1 : i + 100], track_warnings=True),
                )
                nested_content, nested_warnings = nested_result
                warnings.extend(nested_warnings)
                if nested_content:
                    blockquote_content.extend(nested_content)
            else:
                nested_content = _convert_tokens_to_adf([token] + tokens[i + 1 : i + 100])
                if nested_content:
                    blockquote_content.extend(nested_content)

            if token.type == 'paragraph_open':
                i += 3
            else:
                i += 1
        else:
            i += 1

    if is_alert:
        node = {'type': 'panel', 'attrs': {'panelType': alert_type}, 'content': blockquote_content}
    else:
        node = {'type': 'blockquote', 'content': blockquote_content}

    if track_warnings:
        return (node, i + 1, warnings)
    else:
        return (node, i + 1)


def _convert_table_tokens(
    tokens: list, start_index: int, track_warnings: bool = False
) -> tuple[dict, int] | tuple[dict, int, list[str]]:
    """Convert markdown table tokens to ADF table nodes.

    Args:
        tokens: List of markdown-it Token objects
        start_index: Starting index in tokens list
        track_warnings: If True, returns tuple of (table_node, end_index, warnings)

    Returns:
        Tuple of (table_node, end_index), or (table_node, end_index, warnings) if track_warnings=True
    """
    warnings: list[str] = []
    i = start_index + 1
    table_rows = []

    while i < len(tokens):
        token = tokens[i]

        if token.type == 'table_close':
            break

        if token.type == 'thead_open':
            i += 1
            i += 1
            header_cells = []

            while i < len(tokens) and tokens[i].type != 'tr_close':
                if tokens[i].type == 'th_open':
                    i += 1
                    inline_token = tokens[i]
                    if track_warnings:
                        cell_result = cast(
                            tuple[list[dict], list[str]],
                            _convert_inline_tokens(
                                inline_token.children if inline_token.children else [],
                                track_warnings=True,
                            ),
                        )
                        cell_content, cell_warnings = cell_result
                        warnings.extend(cell_warnings)
                    else:
                        cell_content = (
                            _convert_inline_tokens(inline_token.children)
                            if inline_token.children
                            else []
                        )

                    header_cells.append(
                        {
                            'type': 'tableHeader',
                            'content': [{'type': 'paragraph', 'content': cell_content}]
                            if cell_content
                            else [],
                        }
                    )
                    i += 2
                else:
                    i += 1

            if header_cells:
                table_rows.append({'type': 'tableRow', 'content': header_cells})
            i += 2

        elif token.type == 'tbody_open':
            i += 1

            while i < len(tokens) and tokens[i].type != 'tbody_close':
                if tokens[i].type == 'tr_open':
                    i += 1
                    row_cells = []

                    while i < len(tokens) and tokens[i].type != 'tr_close':
                        if tokens[i].type == 'td_open':
                            i += 1
                            inline_token = tokens[i]
                            if track_warnings:
                                cell_result = cast(
                                    tuple[list[dict], list[str]],
                                    _convert_inline_tokens(
                                        inline_token.children if inline_token.children else [],
                                        track_warnings=True,
                                    ),
                                )
                                cell_content, cell_warnings = cell_result
                                warnings.extend(cell_warnings)
                            else:
                                cell_content = (
                                    _convert_inline_tokens(inline_token.children)
                                    if inline_token.children
                                    else []
                                )

                            row_cells.append(
                                {
                                    'type': 'tableCell',
                                    'content': [{'type': 'paragraph', 'content': cell_content}]
                                    if cell_content
                                    else [],
                                }
                            )
                            i += 2
                        else:
                            i += 1

                    if row_cells:
                        table_rows.append({'type': 'tableRow', 'content': row_cells})
                    i += 1
                else:
                    i += 1

            i += 1
        else:
            i += 1

    table_node = {'type': 'table', 'content': table_rows}

    if track_warnings:
        return (table_node, i + 1, warnings)
    else:
        return (table_node, i + 1)


def _detect_malformed_markdown(text: str, tokens: list) -> list[str]:
    """Detect malformed Markdown by analyzing what markdown-it-py parsed as plain text.

    Args:
        text: The Markdown text to check
        tokens: Already-parsed tokens from markdown-it-py

    Returns:
        List of warning messages for detected malformed syntax
    """
    warnings = []

    for token in tokens:
        if token.type == 'inline' and token.content:
            line_num = token.map[0] + 1 if token.map else None

            if hasattr(token, 'children') and token.children:
                for child in token.children:
                    if child.type == 'text' and child.content:
                        text_content = child.content

                        if '**' in text_content:
                            count = text_content.count('**')
                            if count % 2 != 0:
                                if line_num:
                                    warnings.append(
                                        f'Line {line_num}: Unclosed bold marker (**) in "{text_content[:50]}"'
                                    )

                        if text_content.count('`') % 2 != 0:
                            if line_num:
                                warnings.append(
                                    f'Line {line_num}: Unclosed code marker (`) in "{text_content[:50]}"'
                                )

                        if re.search(r'!\[[^\]]*$', text_content):
                            if line_num:
                                warnings.append(
                                    f'Line {line_num}: Incomplete image syntax in "{text_content[:50]}"'
                                )

                        if re.search(r'\[[^\]]+\](?!\()', text_content):
                            is_task_marker = re.match(
                                r'^-?\s*\[([ xX])\](\s|$)', text_content.strip()
                            )

                            is_alert_marker = re.search(
                                r'\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', text_content
                            )

                            is_decision_marker = re.search(r'\[decision:[dau]\]', text_content)

                            if (
                                not is_task_marker
                                and not is_alert_marker
                                and not is_decision_marker
                                and line_num
                            ):
                                warnings.append(
                                    f'Line {line_num}: Incomplete link syntax - missing URL in "{text_content[:50]}"'
                                )

        if token.type == 'paragraph_open':
            idx = tokens.index(token)
            if idx + 1 < len(tokens) and tokens[idx + 1].type == 'inline':
                inline_content = tokens[idx + 1].content.strip()

                if re.match(r'^(-{3,}|_{3,}|\*{3,})[^\s\-_*]', inline_content):
                    line_num = token.map[0] + 1 if token.map else None
                    if line_num:
                        warnings.append(
                            f'Line {line_num}: Malformed horizontal rule - "{inline_content}" '
                            f'(should be "---", "***", or "___" alone on a line)'
                        )

    return warnings


def text_to_adf(text: str, track_warnings: bool = False) -> dict | tuple[dict, list[str]]:
    """Convert markdown text to ADF (Atlassian Document Format).

    Uses markdown-it-py with GitHub Flavored Markdown (GFM) preset to parse markdown into an AST,
    then converts to ADF structure.

    Args:
        text: Markdown or plain text string
        track_warnings: If True, returns tuple of (adf_dict, warnings_list)

    Returns:
        ADF document structure, or tuple of (ADF document, list of warning messages) if track_warnings=True
    """
    if not text or not text.strip():
        result = {'type': 'doc', 'version': 1, 'content': []}
        return (result, []) if track_warnings else result

    md = MarkdownIt('gfm-like')
    md.use(tasklists_plugin)
    tokens = md.parse(text)

    malformed_warnings = []
    if track_warnings:
        malformed_warnings = _detect_malformed_markdown(text, tokens)

    if track_warnings:
        result = _convert_tokens_to_adf(tokens, track_warnings=True)

        if isinstance(result, tuple):
            content, conversion_warnings = result

            all_warnings = malformed_warnings + conversion_warnings
            return {'type': 'doc', 'version': 1, 'content': content}, all_warnings
        else:
            return {'type': 'doc', 'version': 1, 'content': result}, malformed_warnings
    else:
        content = _convert_tokens_to_adf(tokens)
        return {'type': 'doc', 'version': 1, 'content': content}


def _convert_tokens_to_adf(
    tokens: list, track_warnings: bool = False
) -> list[dict] | tuple[list[dict], list[str]]:
    """Convert markdown-it tokens to ADF content nodes.

    Args:
        tokens: List of markdown-it Token objects
        track_warnings: If True, returns tuple of (content, warnings)

    Returns:
        List of ADF content nodes, or tuple of (content, warnings) if track_warnings=True
    """
    content = []
    warnings: list[str] = []
    unsupported_types = set()
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token.type == 'heading_open':
            level = int(token.tag[1])
            i += 1
            inline_token = tokens[i]
            if track_warnings:
                result = cast(
                    tuple[list[dict], list[str]],
                    _convert_inline_tokens(
                        inline_token.children if inline_token.children else [], track_warnings=True
                    ),
                )
                heading_content, inline_warnings = result
                warnings.extend(inline_warnings)
            else:
                heading_content = (
                    _convert_inline_tokens(inline_token.children) if inline_token.children else []
                )
            content.append(
                {'type': 'heading', 'attrs': {'level': level}, 'content': heading_content}
            )
            i += 2

        elif token.type == 'paragraph_open':
            i += 1
            inline_token = tokens[i]
            if track_warnings:
                result = cast(
                    tuple[list[dict], list[str]],
                    _convert_inline_tokens(
                        inline_token.children if inline_token.children else [], track_warnings=True
                    ),
                )
                para_content, inline_warnings = result
                warnings.extend(inline_warnings)
            else:
                para_content = (
                    _convert_inline_tokens(inline_token.children) if inline_token.children else []
                )
            if para_content:
                content.append({'type': 'paragraph', 'content': para_content})
            i += 2

        elif token.type == 'blockquote_open':
            if track_warnings:
                blockquote_result = cast(
                    tuple[dict, int, list[str]],
                    _convert_blockquote_tokens(tokens, i, track_warnings=True),
                )
                blockquote_node, i, blockquote_warnings = blockquote_result
                warnings.extend(blockquote_warnings)
            else:
                blockquote_result = cast(tuple[dict, int], _convert_blockquote_tokens(tokens, i))
                blockquote_node, i = blockquote_result
            content.append(blockquote_node)

        elif token.type == 'hr':
            content.append({'type': 'rule'})
            i += 1

        elif token.type == 'bullet_list_open':
            is_task_list = _is_task_list(tokens, i)

            if is_task_list:
                if track_warnings:
                    list_result = cast(
                        tuple[list[dict], int, list[str]],
                        _convert_task_list_tokens(tokens, i, track_warnings=True),
                    )
                    list_content, i, list_warnings = list_result
                    warnings.extend(list_warnings)
                else:
                    list_result = cast(tuple[list[dict], int], _convert_task_list_tokens(tokens, i))
                    list_content, i = list_result
                content.append(
                    {'type': 'taskList', 'attrs': {'localId': ''}, 'content': list_content}
                )
            else:
                if track_warnings:
                    list_result = cast(
                        tuple[list[dict], int, list[str]],
                        _convert_list_tokens(tokens, i, 'bulletList', track_warnings=True),
                    )
                    list_content, i, list_warnings = list_result
                    warnings.extend(list_warnings)
                else:
                    list_result = cast(
                        tuple[list[dict], int], _convert_list_tokens(tokens, i, 'bulletList')
                    )
                    list_content, i = list_result
                content.append({'type': 'bulletList', 'content': list_content})

        elif token.type == 'ordered_list_open':
            if track_warnings:
                list_result = cast(
                    tuple[list[dict], int, list[str]],
                    _convert_list_tokens(tokens, i, 'orderedList', track_warnings=True),
                )
                list_content, i, list_warnings = list_result
                warnings.extend(list_warnings)
            else:
                list_result = cast(
                    tuple[list[dict], int], _convert_list_tokens(tokens, i, 'orderedList')
                )
                list_content, i = list_result
            content.append({'type': 'orderedList', 'content': list_content})

        elif token.type == 'fence':
            attrs: dict[str, str] = {}

            if token.info:
                attrs['language'] = token.info
            code_node = {
                'type': 'codeBlock',
                'attrs': attrs,
                'content': [{'type': 'text', 'text': token.content}],
            }
            content.append(code_node)
            i += 1

        elif token.type == 'table_open':
            if track_warnings:
                table_result = cast(
                    tuple[dict, int, list[str]],
                    _convert_table_tokens(tokens, i, track_warnings=True),
                )
                table_node, i, table_warnings = table_result
                warnings.extend(table_warnings)
            else:
                table_result = cast(tuple[dict, int], _convert_table_tokens(tokens, i))
                table_node, i = table_result
            content.append(table_node)

        else:
            if track_warnings and token.type not in [
                'inline',
                'paragraph_close',
                'heading_close',
                'bullet_list_close',
                'ordered_list_close',
                'list_item_close',
                'blockquote_close',
                'softbreak',
                'hardbreak',
            ]:
                type_name = (
                    token.type.replace('_', ' ').replace('open', '').replace('close', '').strip()
                )
                if type_name and type_name not in unsupported_types:
                    unsupported_types.add(type_name)
                    warnings.append(f'Unsupported markdown element: {type_name}')
            i += 1

    return (content, warnings) if track_warnings else content


def _convert_list_tokens(
    tokens: list, start_index: int, list_type: str, track_warnings: bool = False
) -> tuple[list[dict], int] | tuple[list[dict], int, list[str]]:
    """Convert markdown list tokens to ADF list items.

    Args:
        tokens: List of markdown-it Token objects
        start_index: Starting index in tokens list
        list_type: 'bulletList' or 'orderedList'
        track_warnings: If True, returns tuple of (list_items, end_index, warnings)

    Returns:
        Tuple of (list_items, end_index), or (list_items, end_index, warnings) if track_warnings=True
    """
    list_items = []
    warnings: list[str] = []
    i = start_index + 1

    while i < len(tokens):
        token = tokens[i]

        if token.type == f'{list_type.replace("List", "")}_list_close':
            break
        elif token.type == 'list_item_open':
            i += 1
            item_content = []

            while i < len(tokens) and tokens[i].type != 'list_item_close':
                inner_token = tokens[i]

                if inner_token.type == 'paragraph_open':
                    i += 1
                    inline_token = tokens[i]
                    if track_warnings:
                        inline_result = cast(
                            tuple[list[dict], list[str]],
                            _convert_inline_tokens(
                                inline_token.children if inline_token.children else [],
                                track_warnings=True,
                            ),
                        )
                        para_content, inline_warnings = inline_result
                        warnings.extend(inline_warnings)
                    else:
                        para_content = (
                            _convert_inline_tokens(inline_token.children)
                            if inline_token.children
                            else []
                        )
                    if para_content:
                        item_content.append({'type': 'paragraph', 'content': para_content})
                    i += 2

                elif inner_token.type == 'bullet_list_open':
                    if track_warnings:
                        nested_result = cast(
                            tuple[list[dict], int, list[str]],
                            _convert_list_tokens(tokens, i, 'bulletList', track_warnings=True),
                        )
                        nested_content, i, nested_warnings = nested_result
                        warnings.extend(nested_warnings)
                    else:
                        nested_result = cast(
                            tuple[list[dict], int],
                            _convert_list_tokens(tokens, i, 'bulletList'),
                        )
                        nested_content, i = nested_result
                    item_content.append({'type': 'bulletList', 'content': nested_content})

                elif inner_token.type == 'ordered_list_open':
                    if track_warnings:
                        nested_result = cast(
                            tuple[list[dict], int, list[str]],
                            _convert_list_tokens(tokens, i, 'orderedList', track_warnings=True),
                        )
                        nested_content, i, nested_warnings = nested_result
                        warnings.extend(nested_warnings)
                    else:
                        nested_result = cast(
                            tuple[list[dict], int],
                            _convert_list_tokens(tokens, i, 'orderedList'),
                        )
                        nested_content, i = nested_result
                    item_content.append({'type': 'orderedList', 'content': nested_content})

                else:
                    i += 1

            list_items.append({'type': 'listItem', 'content': item_content})
            i += 1

        else:
            i += 1

    if track_warnings:
        return (list_items, i + 1, warnings)
    else:
        return (list_items, i + 1)


def _convert_inline_tokens(
    tokens: list, track_warnings: bool = False
) -> list[dict] | tuple[list[dict], list[str]]:
    """Convert markdown-it inline tokens to ADF text nodes with marks.

    Args:
        tokens: List of markdown-it inline Token objects
        track_warnings: If True, returns tuple of (content, warnings)

    Returns:
        List of ADF text nodes, or tuple of (content, warnings) if track_warnings=True
    """
    if not tokens:
        return ([], []) if track_warnings else []

    content = []
    warnings: list[str] = []
    unsupported_types = set()
    i = 0
    active_marks = []

    while i < len(tokens):
        token = tokens[i]

        if token.type == 'text':
            text_node = {'type': 'text', 'text': token.content}
            if active_marks:
                text_node['marks'] = [{'type': mark} for mark in active_marks]
            content.append(text_node)
            i += 1

        elif token.type == 'strong_open':
            active_marks.append('strong')
            i += 1
        elif token.type == 'strong_close':
            if 'strong' in active_marks:
                active_marks.remove('strong')
            i += 1

        elif token.type == 'em_open':
            active_marks.append('em')
            i += 1
        elif token.type == 'em_close':
            if 'em' in active_marks:
                active_marks.remove('em')
            i += 1

        elif token.type == 'code_inline':
            text_node = {'type': 'text', 'text': token.content, 'marks': [{'type': 'code'}]}
            content.append(text_node)
            i += 1

        elif token.type == 'link_open':
            href = token.attrGet('href')
            i += 1

            link_text = ''
            while i < len(tokens) and tokens[i].type != 'link_close':
                if tokens[i].type == 'text':
                    link_text += tokens[i].content
                i += 1

            mention_match = re.search(r'/jira/people/([^/]+)$', href or '')
            if mention_match:
                account_id = mention_match.group(1)
                mention_node = {
                    'type': 'mention',
                    'attrs': {
                        'id': account_id,
                        'text': link_text,
                    },
                }
                content.append(mention_node)
            else:
                text_node = {
                    'type': 'text',
                    'text': link_text,
                    'marks': [{'type': 'link', 'attrs': {'href': href}}],
                }
                content.append(text_node)
            i += 1

        elif token.type == 's_open':
            active_marks.append('strike')
            i += 1
        elif token.type == 's_close':
            if 'strike' in active_marks:
                active_marks.remove('strike')
            i += 1

        else:
            if track_warnings and token.type not in ['softbreak', 'hardbreak']:
                type_name = (
                    token.type.replace('_', ' ').replace('open', '').replace('close', '').strip()
                )
                if type_name and type_name not in unsupported_types:
                    unsupported_types.add(type_name)
                    warnings.append(f'Unsupported inline markdown: {type_name}')
            i += 1

    return (content, warnings) if track_warnings else content
