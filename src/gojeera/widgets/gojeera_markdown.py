import logging
import re
from typing import Callable

from markdown_it import MarkdownIt
from markdown_it.token import Token
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.content import Content, Span
from textual.markup import parse_style
from textual.style import Style
from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownBlockQuote, MarkdownParagraph

from gojeera.utils.mdit_adf_decision import decision_plugin
from gojeera.utils.mdit_adf_panels import panels_plugin

logger = logging.getLogger('gojeera')


class CheckboxStyledParagraph(MarkdownParagraph):
    """Markdown paragraph with checkbox, date, status, and decision styling."""

    _style_cache: dict[str, Style] = {}

    _whitespace_pattern = re.compile(r'\s+')
    _date_pattern = re.compile(r'\[date\](.+)')
    _status_pattern = re.compile(r'\[status:([nrbgypt])\](.+)')
    _decision_pattern = re.compile(r'\[decision:([dau])\](.+)')

    _global_css_cache: dict[str, str] | None = None
    _global_css_cache_id: int | None = None

    def _token_to_content(self, token: Token) -> Content:
        """Convert token to content with styling."""

        markdown = self._markdown

        css_variables: dict[str, str] = {}
        if isinstance(markdown, GojeeraMarkdown):
            try:
                if markdown._cached_app is None:
                    markdown._cached_app = markdown.app

                app_id = id(markdown._cached_app)

                if (
                    self.__class__._global_css_cache_id == app_id
                    and self.__class__._global_css_cache is not None
                ):
                    css_variables = self.__class__._global_css_cache
                else:
                    css_variables = markdown._cached_app.get_css_variables()
                    self.__class__._global_css_cache = css_variables
                    self.__class__._global_css_cache_id = app_id
            except Exception:
                css_variables = {}
        else:
            try:
                if hasattr(markdown, 'app'):
                    css_variables = markdown.app.get_css_variables()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

        if token.children is None:
            return Content('')

        tokens: list[str] = []
        spans: list[Span] = []
        style_stack: list[tuple[Style | str, int]] = []
        position: int = 0

        def add_content(text: str) -> None:
            """Add text to the tokens list, and advance the position."""
            nonlocal position
            tokens.append(text)
            position += len(text)

        def add_style(style: Style | str) -> None:
            """Add a style to the stack."""
            style_stack.append((style, position))

        def close_tag() -> None:
            style, start = style_stack.pop()
            spans.append(Span(start, position, style))

        def get_cached_style(style_str: str, fallback_str: str | None = None) -> Style:
            """Get a cached style or parse and cache it."""
            cache_key = f'{style_str}_{id(css_variables)}'
            if cache_key not in self._style_cache:
                try:
                    self._style_cache[cache_key] = parse_style(style_str, variables=css_variables)
                except Exception:
                    if fallback_str:
                        self._style_cache[cache_key] = parse_style(fallback_str)
                    else:
                        self._style_cache[cache_key] = parse_style(style_str)
            return self._style_cache[cache_key]

        status_color_map = {
            'n': get_cached_style('on $surface', 'on grey50'),
            'r': get_cached_style('on $error', 'on red'),
            'b': get_cached_style('on $primary', 'on blue'),
            'g': get_cached_style('on $success', 'on green'),
            'y': get_cached_style('on $warning', 'on yellow'),
            'p': get_cached_style('on $accent', 'on magenta'),
            't': get_cached_style('on $primary', 'on cyan'),
        }

        for child in token.children:
            child_type = child.type

            if child_type == 'text':
                add_content(self._whitespace_pattern.sub(' ', child.content))

            elif child_type == 'hardbreak':
                add_content('\n')

            elif child_type == 'softbreak':
                add_content(' ')

            elif child_type == 'code_inline':
                content_text = child.content

                date_match = self._date_pattern.match(content_text)
                if date_match:
                    date_text = date_match.group(1)
                    date_style = get_cached_style('on $surface', 'on cyan')
                    add_style(date_style)
                    add_content(date_text)
                    close_tag()
                    continue

                status_match = self._status_pattern.match(content_text)
                if status_match:
                    color_code = status_match.group(1)
                    status_text = status_match.group(2)

                    status_style = status_color_map.get(color_code, status_color_map['n'])
                    add_style(status_style)
                    add_content(status_text)
                    close_tag()
                    continue

                decision_match = self._decision_pattern.match(content_text)
                if decision_match:
                    decision_text = decision_match.group(2)

                    add_content(f'⤷ {decision_text}')
                    continue

                add_style('.code_inline')
                add_content(content_text)
                close_tag()

            elif child_type == 'em_open':
                add_style('.em')

            elif child_type == 'strong_open':
                add_style('.strong')

            elif child_type == 's_open':
                add_style('.s')

            elif child_type == 'link_open':
                href = child.attrs.get('href', '')
                action = f'link({href!r})'
                add_style(Style.from_meta({'@click': action}))

            elif child_type == 'image':
                href = child.attrs.get('src', '')
                alt = child.attrs.get('alt', '')
                action = f'link({href!r})'
                add_style(Style.from_meta({'@click': action}))
                add_content('🖼  ')
                if alt:
                    add_content(f'({alt})')
                if child.children is not None:
                    for grandchild in child.children:
                        add_content(grandchild.content)
                close_tag()

            elif child_type.endswith('_close'):
                close_tag()

        content = Content(''.join(tokens), spans=spans)

        plain_text = content.plain
        if plain_text:
            has_unchecked = '☐' in plain_text
            has_checked = '☑' in plain_text

            if has_unchecked or has_checked:
                if isinstance(markdown, GojeeraMarkdown):
                    unchecked_style_str = markdown.checkbox_unchecked_style
                    checked_style_str = markdown.checkbox_checked_style
                else:
                    unchecked_style_str = 'dim grey50'
                    checked_style_str = 'bold green'

                unchecked_style = get_cached_style(unchecked_style_str)
                checked_style = get_cached_style(checked_style_str)

                for i, char in enumerate(plain_text):
                    if has_unchecked and char == '☐':
                        content = content.stylize(unchecked_style, i, i + 1)
                    elif has_checked and char == '☑':
                        content = content.stylize(checked_style, i, i + 1)

        return content


class GojeeraBlockQuote(MarkdownBlockQuote):
    """Blockquote with support for GitHub-style alerts."""

    DEFAULT_CSS = """
    /* Base blockquote styling */
    GojeeraBlockQuote {
        background: $boost;
        border-left: outer $text-primary 50%;
        margin: 1 0;
        padding: 0 1;
    }

    /* Alert type-specific styling with colored labels */
    GojeeraBlockQuote.alert-note {
        border-left: thick $primary;
        background: $primary 10%;
    }

    GojeeraBlockQuote.alert-note > Paragraph {
        color: $primary;
    }

    GojeeraBlockQuote.alert-tip {
        border-left: thick $success;
        background: $success 10%;
    }

    GojeeraBlockQuote.alert-tip > Paragraph {
        color: $success;
    }

    GojeeraBlockQuote.alert-important {
        border-left: thick $accent;
        background: $accent 10%;
    }

    GojeeraBlockQuote.alert-important > Paragraph {
        color: $accent;
    }

    GojeeraBlockQuote.alert-warning {
        border-left: thick $warning;
        background: $warning 10%;
    }

    GojeeraBlockQuote.alert-warning > Paragraph {
        color: $warning;
    }

    GojeeraBlockQuote.alert-caution {
        border-left: thick $error;
        background: $error 10%;
    }

    GojeeraBlockQuote.alert-caution > Paragraph {
        color: $error;
    }

    /* Decision blockquote styling */
    GojeeraBlockQuote.decision {
        border-left: thick $success;
        background: $success-muted;
    }

    GojeeraBlockQuote.decision > Paragraph {
        color: $text-success;
    }
    """

    def __init__(self, markdown: Markdown, token: Token) -> None:
        super().__init__(markdown, token)

        if token.attrs and 'class' in token.attrs:
            css_class = token.attrs['class']
            if isinstance(css_class, str):
                self.add_class(css_class)

        if token.children:
            self._detect_decision_blockquote(token.children)

    _decision_detection_pattern = re.compile(r'\[decision:[dau]\]')

    def _detect_decision_blockquote(self, tokens: list) -> bool:
        """Detect if blockquote contains decision items and apply styling."""

        stack = list(tokens)

        while stack:
            token = stack.pop()

            if hasattr(token, 'type') and token.type == 'inline':
                if hasattr(token, 'children') and token.children:
                    for child in token.children:
                        if hasattr(child, 'type') and child.type == 'code_inline':
                            content = getattr(child, 'content', '')
                            if self._decision_detection_pattern.match(content):
                                self.add_class('decision')
                                return True

            if hasattr(token, 'children') and token.children:
                stack.extend(token.children)

        return False


class GojeeraMarkdown(Markdown):
    """
    Custom Markdown widget that extends GitHub Flavored Markdown
    with custom Atlassian Document Format logic.
    """

    DEFAULT_CSS = """
    GojeeraMarkdown MarkdownHeader {
        margin: 0;
        width: auto;
    }

    GojeeraMarkdown MarkdownH1,
    GojeeraMarkdown MarkdownH2,
    GojeeraMarkdown MarkdownH3,
    GojeeraMarkdown MarkdownH4,
    GojeeraMarkdown MarkdownH5,
    GojeeraMarkdown MarkdownH6 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        text-style: bold;
    }

    GojeeraMarkdown MarkdownH1 > MarkdownBlock,
    GojeeraMarkdown MarkdownH2 > MarkdownBlock,
    GojeeraMarkdown MarkdownH3 > MarkdownBlock,
    GojeeraMarkdown MarkdownH4 > MarkdownBlock,
    GojeeraMarkdown MarkdownH5 > MarkdownBlock,
    GojeeraMarkdown MarkdownH6 > MarkdownBlock {
        width: auto;
    }

    GojeeraMarkdown > MarkdownParagraph {
        margin: 0 0 1 0;
    }

    GojeeraMarkdown MarkdownBulletList,
    GojeeraMarkdown MarkdownOrderedList {
        margin: 0 0 1 0;
        padding: 0;
    }

    GojeeraMarkdown MarkdownOrderedList {
        margin-left: 0;
        padding-left: 0;
    }

    GojeeraMarkdown MarkdownListItem {
        margin: 0;
        padding: 0;
    }

    GojeeraMarkdown MarkdownListItem > Vertical > MarkdownParagraph {
        margin: 0;
    }

    GojeeraMarkdown MarkdownListItem > Vertical > MarkdownBlock {
        margin: 0;
    }

    GojeeraMarkdown MarkdownFence > Label {
        padding: 0;
    }

    GojeeraMarkdown MarkdownH1 {
        background: $primary 30%;
    }

    GojeeraMarkdown MarkdownH2 {
        background: $primary 20%;
    }

    GojeeraMarkdown MarkdownH3 {
        background: $primary 15%;
    }

    GojeeraMarkdown MarkdownH4 {
        background: $primary 10%;
    }

    GojeeraMarkdown MarkdownH5 {
        background: $primary 7%;
    }

    GojeeraMarkdown MarkdownH6 {
        background: $primary 5%;
    }
    """

    checkbox_unchecked_style: str = '$primary'

    checkbox_checked_style: str = 'bold $success'

    BLOCKS = {
        **Markdown.BLOCKS,
        'paragraph_open': CheckboxStyledParagraph,
        'blockquote_open': GojeeraBlockQuote,
    }

    _cached_parser: MarkdownIt | None = None

    @classmethod
    def _create_parser(cls) -> MarkdownIt:
        """Create a markdown-it parser with panels and decision plugins enabled."""
        if cls._cached_parser is None:
            parser = MarkdownIt('gfm-like')
            parser.use(panels_plugin)
            parser.use(decision_plugin)
            cls._cached_parser = parser
        return cls._cached_parser

    def __init__(
        self,
        markdown: str | None = None,
        *,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None,
        open_links: bool = True,
    ) -> None:
        self._last_markdown_content: str | None = None
        self._cached_app: App | None = None

        super().__init__(
            markdown=markdown,
            parser_factory=parser_factory or self._create_parser,
            name=name,
            id=id,
            classes=classes,
            open_links=open_links,
        )

    def update(self, markdown: str) -> AwaitComplete:
        if markdown == self._last_markdown_content:
            return AwaitComplete.nothing()

        self._last_markdown_content = markdown
        return super().update(markdown)
