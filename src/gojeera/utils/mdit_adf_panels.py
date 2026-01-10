from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token


def panels_plugin(md: MarkdownIt) -> None:
    """Detect and transform GitHub-style alert blockquotes into ADF panel."""

    def process_alerts(state: StateCore) -> None:
        tokens = state.tokens
        i = 0

        while i < len(tokens):
            token = tokens[i]

            if token.type == 'blockquote_open':
                if i + 1 < len(tokens) and is_alert_blockquote(tokens, i + 1):
                    alert_type = detect_alert_type(tokens, i + 1)
                    if alert_type:
                        token.attrSet('class', f'alert-{alert_type}')

                        split_alert_paragraph(tokens, i + 1, alert_type)

            i += 1

    def is_alert_blockquote(tokens: list[Token], start_index: int) -> bool:
        for i in range(start_index, min(start_index + 10, len(tokens))):
            token = tokens[i]
            if token.type == 'inline' and token.content:
                return bool(re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', token.content))
        return False

    def detect_alert_type(tokens: list[Token], start_index: int) -> str | None:
        for i in range(start_index, min(start_index + 10, len(tokens))):
            token = tokens[i]
            if token.type == 'inline' and token.content:
                match = re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', token.content)
                if match:
                    alert_name = match.group(1).lower()
                    return alert_name
        return None

    def split_alert_paragraph(tokens: list[Token], start_index: int, alert_type: str) -> None:
        alert_labels = {
            'note': 'Note',
            'tip': 'Tip',
            'important': 'Important',
            'warning': 'Warning',
            'caution': 'Caution',
        }

        label = alert_labels.get(alert_type, 'Note')

        for i in range(start_index, min(start_index + 10, len(tokens))):
            token = tokens[i]
            if token.type == 'inline' and token.content:
                match = re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*', token.content)
                if match:
                    para_open_idx = None
                    para_close_idx = None

                    for j in range(i - 1, max(start_index - 5, -1), -1):
                        if tokens[j].type == 'paragraph_open':
                            para_open_idx = j
                            break

                    for j in range(i + 1, min(i + 10, len(tokens))):
                        if tokens[j].type == 'paragraph_close':
                            para_close_idx = j
                            break

                    if para_open_idx is not None and para_close_idx is not None:
                        label_para_open = Token('paragraph_open', 'p', 1)
                        label_para_open.map = tokens[para_open_idx].map

                        label_inline = Token('inline', '', 0)
                        label_inline.content = label
                        label_inline.map = token.map
                        label_inline.children = [
                            Token('strong_open', 'strong', 1),
                            Token('text', '', 0),
                            Token('strong_close', 'strong', -1),
                        ]
                        label_inline.children[0].markup = '**'
                        label_inline.children[1].content = label
                        label_inline.children[2].markup = '**'

                        label_para_close = Token('paragraph_close', 'p', -1)

                        content_para_open = Token('paragraph_open', 'p', 1)
                        content_para_open.map = tokens[para_open_idx].map

                        content_inline = Token('inline', '', 0)
                        content_inline.map = token.map

                        new_children = []
                        cleaned_texts = []

                        if token.children:
                            idx = 0
                            found_marker = False

                            while idx < len(token.children):
                                child = token.children[idx]

                                if (
                                    not found_marker
                                    and child.type == 'text'
                                    and '[!' in child.content
                                ):
                                    found_marker = True
                                    idx += 1
                                    continue

                                if found_marker and child.type in ('softbreak', 'hardbreak'):
                                    idx += 1
                                    continue

                                if (
                                    found_marker
                                    and child.type == 'text'
                                    and not child.content.strip()
                                ):
                                    idx += 1
                                    continue

                                if found_marker and child.type == 'strong_open':
                                    if (
                                        idx + 2 < len(token.children)
                                        and token.children[idx + 1].type == 'text'
                                        and re.match(
                                            r'^(Note|Tip|Important|Warning|Caution):$',
                                            token.children[idx + 1].content,
                                        )
                                        and token.children[idx + 2].type == 'strong_close'
                                    ):
                                        idx += 3
                                        found_marker = False
                                        continue

                                if child.type == 'text' and child.content:
                                    cleaned = child.content.strip()
                                    if cleaned:
                                        child.content = cleaned
                                        new_children.append(child)
                                        cleaned_texts.append(cleaned)
                                else:
                                    new_children.append(child)

                                found_marker = False
                                idx += 1

                        content_inline.children = new_children

                        content_inline.content = ' '.join(cleaned_texts) if cleaned_texts else ''

                        content_para_close = Token('paragraph_close', 'p', -1)

                        tokens[para_open_idx : para_close_idx + 1] = [
                            label_para_open,
                            label_inline,
                            label_para_close,
                            content_para_open,
                            content_inline,
                            content_para_close,
                        ]

                    break

    md.core.ruler.after('inline', 'github-alerts', process_alerts)
