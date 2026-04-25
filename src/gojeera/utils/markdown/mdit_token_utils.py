from markdown_it.token import Token


def create_labeled_paragraph_pair(
    label: str, *, paragraph_map: list[int] | None, inline_map: list[int] | None
) -> tuple[Token, Token, Token, Token, Token, Token]:
    """Create a bold label paragraph followed by an empty content paragraph."""

    label_para_open = Token('paragraph_open', 'p', 1)
    label_para_open.map = paragraph_map

    label_inline = Token('inline', '', 0)
    label_inline.content = label
    label_inline.map = inline_map
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
    content_para_open.map = paragraph_map

    content_inline = Token('inline', '', 0)
    content_inline.map = inline_map

    content_para_close = Token('paragraph_close', 'p', -1)

    return (
        label_para_open,
        label_inline,
        label_para_close,
        content_para_open,
        content_inline,
        content_para_close,
    )


def build_labeled_paragraph_tokens(
    label: str,
    *,
    paragraph_map: list[int] | None,
    inline_map: list[int] | None,
    content_children: list[Token],
    content_text: str,
) -> list[Token]:
    tokens = list(
        create_labeled_paragraph_pair(
            label,
            paragraph_map=paragraph_map,
            inline_map=inline_map,
        )
    )
    content_inline = tokens[4]
    content_inline.children = content_children
    content_inline.content = content_text
    return tokens
