"""Markdown-it-py plugin for decision patterns in blockquotes.

Transforms decision items for visual display in the TUI.
See docs/markdown_to_adf_conversion.md for full documentation.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token


def decision_plugin(md: MarkdownIt) -> None:
    """Detect and transform decision item blockquotes.

    See docs/markdown_to_adf_conversion.md for details.
    """

    # Map decision state codes to display labels
    DECISION_LABELS = {
        'd': 'DECIDED',
        'a': 'ACKNOWLEDGED',
        'u': 'UP FOR DISCUSSION',
    }

    def process_tokens(tokens):
        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Check if this is a blockquote
            if token.type == 'blockquote_open':
                # Look ahead to find the content tokens
                # Structure: blockquote_open, [...content tokens...], blockquote_close
                if i + 1 < len(tokens):
                    # Find blockquote_close index
                    close_idx = find_blockquote_close(tokens, i + 1)
                    if close_idx > 0:
                        # Check if this blockquote contains decisions
                        if has_decision_patterns(tokens, i + 1, close_idx):
                            # Add 'decision' class to the blockquote token
                            if not hasattr(token, 'attrs') or token.attrs is None:
                                token.attrs = {}
                            token.attrs['class'] = 'decision'
                            # Process all decision paragraphs in this blockquote
                            process_decision_blockquote(tokens, i + 1, close_idx)

            # Recursively process children
            if hasattr(token, 'children') and token.children:
                process_tokens(token.children)

            i += 1

    def find_blockquote_close(tokens, start_index):
        for i in range(start_index, len(tokens)):
            if tokens[i].type == 'blockquote_close':
                return i
        return -1

    def has_decision_patterns(tokens, start_idx, end_idx):
        for i in range(start_idx, end_idx):
            token = tokens[i]
            if token.type == 'inline' and hasattr(token, 'children') and token.children:
                for child in token.children:
                    if child.type == 'code_inline':
                        content = getattr(child, 'content', '')
                        if re.match(r'\[decision:[dau]\]', content):
                            return True
        return False

    def process_decision_blockquote(tokens, start_idx, end_idx):
        # Find all paragraphs with decision patterns
        i = start_idx
        while i < end_idx:
            token = tokens[i]

            # Look for inline tokens with decision patterns
            if token.type == 'inline' and hasattr(token, 'children') and token.children:
                # Find decision code_inline
                for child_idx, child in enumerate(token.children):
                    if child.type == 'code_inline':
                        content = getattr(child, 'content', '')
                        match = re.match(r'\[decision:([dau])\]', content)
                        if match:
                            state_code = match.group(1)
                            # Found a decision - split this paragraph
                            para_open_idx, para_close_idx = find_paragraph_bounds(
                                tokens, i, start_idx, end_idx
                            )
                            if para_open_idx >= 0 and para_close_idx >= 0:
                                # Split the paragraph
                                new_tokens = create_decision_paragraph_split(
                                    tokens, para_open_idx, i, para_close_idx, child_idx, state_code
                                )
                                # Replace original paragraph with split version
                                tokens[para_open_idx : para_close_idx + 1] = new_tokens
                                # Adjust indices: we added tokens (label para has 3 tokens)
                                adjustment = len(new_tokens) - (para_close_idx - para_open_idx + 1)
                                end_idx += adjustment
                                i = para_open_idx + len(new_tokens) - 1
                            break  # Process next inline token
            i += 1

    def find_paragraph_bounds(tokens, inline_idx, start_idx, end_idx):
        # Search backwards for paragraph_open
        para_open_idx = -1
        for j in range(inline_idx - 1, max(start_idx - 1, -1), -1):
            if tokens[j].type == 'paragraph_open':
                para_open_idx = j
                break

        # Search forwards for paragraph_close
        para_close_idx = -1
        for j in range(inline_idx + 1, min(end_idx + 1, len(tokens))):
            if tokens[j].type == 'paragraph_close':
                para_close_idx = j
                break

        return para_open_idx, para_close_idx

    def create_decision_paragraph_split(
        tokens, para_open_idx, inline_idx, para_close_idx, child_idx, state_code
    ):
        inline_token = tokens[inline_idx]
        label = f'DECISION {DECISION_LABELS.get(state_code, "DECIDED")}'

        # Create label paragraph tokens
        label_para_open = Token('paragraph_open', 'p', 1)
        label_para_open.map = tokens[para_open_idx].map

        label_inline = Token('inline', '', 0)
        label_inline.content = label
        label_inline.map = inline_token.map
        label_inline.children = [
            Token('strong_open', 'strong', 1),
            Token('text', '', 0),
            Token('strong_close', 'strong', -1),
        ]
        label_inline.children[0].markup = '**'
        label_inline.children[1].content = label
        label_inline.children[2].markup = '**'

        label_para_close = Token('paragraph_close', 'p', -1)

        # Create content paragraph tokens (with modified inline children)
        content_para_open = Token('paragraph_open', 'p', 1)
        content_para_open.map = tokens[para_open_idx].map

        content_inline = Token('inline', '', 0)
        content_inline.map = inline_token.map

        # Copy children but remove the [decision:x] marker from code_inline
        new_children = []
        for idx, child in enumerate(inline_token.children):
            if idx == child_idx and child.type == 'code_inline':
                # Extract text after [decision:x]
                content = getattr(child, 'content', '')
                text_after = re.sub(r'^\[decision:[dau]\]', '', content)
                if text_after:
                    # Create a plain text token instead of code_inline
                    text_token = Token('text', '', 0)
                    text_token.content = text_after
                    new_children.append(text_token)
            else:
                new_children.append(child)

        content_inline.children = new_children
        # Update content field
        content_inline.content = ''.join(
            getattr(child, 'content', '') for child in new_children if child.type == 'text'
        )

        content_para_close = Token('paragraph_close', 'p', -1)

        # Return the new token sequence
        return [
            label_para_open,
            label_inline,
            label_para_close,
            content_para_open,
            content_inline,
            content_para_close,
        ]

    # Add the core rule to process tokens after parsing
    def decision_rule(state):
        process_tokens(state.tokens)

    md.core.ruler.after('inline', 'decision', decision_rule)
