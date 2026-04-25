from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from markdown_it.token import Token

from gojeera.utils.markdown.mdit_token_utils import build_labeled_paragraph_tokens


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
                                    next_children = token.children[idx + 1 : idx + 3]
                                    if (
                                        len(next_children) == 2
                                        and next_children[0].type == 'text'
                                        and re.match(
                                            r'^(Note|Tip|Important|Warning|Caution):$',
                                            next_children[0].content,
                                        )
                                        and next_children[1].type == 'strong_close'
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

                        replace_end = para_close_idx + 1
                        tokens[para_open_idx:replace_end] = build_labeled_paragraph_tokens(
                            label,
                            paragraph_map=tokens[para_open_idx].map,
                            inline_map=token.map,
                            content_children=new_children,
                            content_text=' '.join(cleaned_texts) if cleaned_texts else '',
                        )

                    break

    md.core.ruler.after('inline', 'github-alerts', process_alerts)
