from inspect import isawaitable
import logging
import re
from typing import TYPE_CHECKING, Callable, Protocol, cast
from urllib.parse import unquote, urlparse

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich.segment import Segment
from rich.style import Style as RichStyle
from rich.text import Text
from textual import events
from textual.app import App
from textual.await_complete import AwaitComplete
from textual.content import Content, Span
from textual.strip import Strip
from textual.style import Style
from textual.widgets import Markdown
from textual.widgets._markdown import MarkdownBlockQuote, MarkdownParagraph

from gojeera.utils.adf_helpers import DATE_INLINE_SENTINEL
from gojeera.utils.mdit_adf_decision import decision_plugin
from gojeera.utils.mdit_adf_panels import panels_plugin
from gojeera.utils.urls import WORK_ITEM_BROWSE_TOOLTIP, extract_work_item_key

logger = logging.getLogger('gojeera')

if TYPE_CHECKING:
    from gojeera.app import MainScreen
    from gojeera.models import Attachment

WORK_ITEM_BROWSE_TOOLTIP_META_KEY = 'gojeera_work_item_browse_tooltip'
WORK_ITEM_BROWSE_KEY_META_KEY = 'gojeera_work_item_key'
MARKDOWN_LINK_HREF_META_KEY = 'gojeera_link_href'
ATTACHMENT_REFERENCE_FILENAME_META_KEY = 'gojeera_attachment_filename'
ATTACHMENT_REFERENCE_TOOLTIP_META_KEY = 'gojeera_attachment_tooltip'
INLINE_CODE_META_KEY = 'gojeera_inline_code'
WORK_ITEM_OPEN_HINT = 'CTRL+Left Mouse Click to open in gojeera'
ATTACHMENT_OPEN_HINT = 'Click to open attachments tab'
ATTACHMENT_BROWSER_OPEN_HINT = 'CTRL+O to open attachment in browser'
WORK_ITEM_TOOLTIP_FIELDS = ['summary', 'status', 'issuetype']


class _AttachmentTooltipMarkdown(Protocol):
    app: App


def build_work_item_tooltip(
    work_item_type: str,
    summary: str,
    status: str,
) -> Text:
    """Build a rich tooltip for a Jira work item browse link."""
    tooltip = Text()
    title = summary.strip() or 'Unknown work item'
    issue_type = work_item_type.strip() or 'Work Item'
    tooltip.append(f'[{issue_type}] {title}', style='bold')
    tooltip.append('\n')
    tooltip.append(status.strip() or 'Unknown', style='dim')
    tooltip.append('\n\n')
    tooltip.append(WORK_ITEM_OPEN_HINT, style='dim')
    return tooltip


def build_loading_work_item_tooltip() -> Text:
    """Build a temporary tooltip shown while work item details are loading."""
    tooltip = Text()
    tooltip.append('Loading work item...', style='bold blue')
    tooltip.append('\n')
    tooltip.append(WORK_ITEM_OPEN_HINT)
    return tooltip


def build_attachment_tooltip(
    filename: str | None,
    mime_type: str | None = None,
    size_kb: str | None = None,
    created_date: str | None = None,
    author: str | None = None,
) -> Text:
    """Build a rich tooltip for an attachment reference."""
    tooltip = Text()
    tooltip.append(filename.strip() if filename else 'Attachment', style='bold')

    detail_parts = [part for part in [mime_type, size_kb, created_date] if part]
    if detail_parts:
        tooltip.append('\n')
        tooltip.append(' • '.join(detail_parts), style='dim')

    if author:
        tooltip.append('\n')
        tooltip.append(author, style='dim')

    tooltip.append('\n\n')
    tooltip.append(ATTACHMENT_OPEN_HINT, style='dim')
    tooltip.append('\n')
    tooltip.append(ATTACHMENT_BROWSER_OPEN_HINT, style='dim')
    return tooltip


def build_markdown_link_style(href: str, jira_base_url: str | None = None) -> Style:
    """Build style metadata for markdown links, including gojeera-specific tooltips."""
    meta: dict[str, str] = {
        '@click': f'link({href!r})',
        MARKDOWN_LINK_HREF_META_KEY: href,
    }
    work_item_key = extract_work_item_key(href, jira_base_url)
    if work_item_key is not None:
        meta[WORK_ITEM_BROWSE_TOOLTIP_META_KEY] = WORK_ITEM_BROWSE_TOOLTIP
        meta[WORK_ITEM_BROWSE_KEY_META_KEY] = work_item_key
    return Style.from_meta(meta)


def get_markdown_link_tooltip(style: RichStyle | Style) -> str | None:
    """Extract a gojeera-specific tooltip from a rendered link style."""
    meta = style.meta or {}
    tooltip = meta.get(WORK_ITEM_BROWSE_TOOLTIP_META_KEY)
    return tooltip if isinstance(tooltip, str) else None


def get_markdown_link_work_item_key(style: RichStyle | Style) -> str | None:
    """Extract a gojeera work item key from rendered link style metadata."""
    meta = style.meta or {}
    work_item_key = meta.get(WORK_ITEM_BROWSE_KEY_META_KEY)
    return work_item_key if isinstance(work_item_key, str) else None


def get_markdown_link_href(style: RichStyle | Style) -> str | None:
    """Extract a rendered markdown link href from style metadata."""
    meta = style.meta or {}
    href = meta.get(MARKDOWN_LINK_HREF_META_KEY)
    return href if isinstance(href, str) else None


def get_attachment_reference_filename(style: RichStyle | Style) -> str | None:
    """Extract an attachment filename from rendered style metadata."""
    meta = style.meta or {}
    filename = meta.get(ATTACHMENT_REFERENCE_FILENAME_META_KEY)
    return filename if isinstance(filename, str) else None


def get_attachment_filename_from_href(href: str) -> str | None:
    """Extract an attachment filename from a Jira attachment URL."""
    if not href:
        return None

    parsed = urlparse(href)
    if parsed.scheme == 'attachment':
        return unquote(parsed.path) or 'Attachment'

    path_parts = [part for part in parsed.path.split('/') if part]
    if len(path_parts) >= 3 and path_parts[-3] == 'attachment' and path_parts[-2] == 'content':
        return None

    if len(path_parts) >= 4 and path_parts[-4] == 'secure' and path_parts[-3] == 'attachment':
        return unquote(path_parts[-1]) or None

    if len(path_parts) >= 2 and path_parts[-2] == 'attachment':
        return None
    return None


def build_attachment_reference_style(filename: str | None) -> Style:
    """Build style metadata for an internal attachment reference."""
    attachment_target = filename or ''
    return Style.from_meta(
        {
            ATTACHMENT_REFERENCE_FILENAME_META_KEY: attachment_target,
            ATTACHMENT_REFERENCE_TOOLTIP_META_KEY: ATTACHMENT_OPEN_HINT,
        }
    )


def build_attachment_reference_chip_label(filename: str | None) -> str:
    """Build the inline attachment chip label shown in markdown widgets."""
    label = filename.strip() if filename else 'Attachment'
    return f' {label} '


def build_inline_code_style() -> Style:
    """Build style metadata for inline code spans rendered inside markdown."""
    return Style.from_meta({INLINE_CODE_META_KEY: True})


def trim_interactive_span_whitespace(content: Content) -> Content:
    """Trim leading and trailing whitespace from interactive spans."""
    if not content.spans:
        return content

    new_spans: list[Span] = []
    for span in content.spans:
        style = span.style
        meta = style.meta if isinstance(style, Style) else None
        if not isinstance(meta, dict) or '@click' not in meta:
            new_spans.append(span)
            continue

        span_text = content.plain[span.start : span.end]
        leading_trim = len(span_text) - len(span_text.lstrip())
        trailing_trim = len(span_text.rstrip())
        trimmed_start = span.start + leading_trim
        trimmed_end = span.start + trailing_trim

        if trimmed_start < trimmed_end:
            new_spans.append(Span(trimmed_start, trimmed_end, style))

    return Content(content.plain, spans=new_spans)


def apply_focused_link_style_to_strip(
    strip: Strip,
    focused_link_href: str | None,
    link_hover_style: RichStyle,
) -> Strip:
    """Apply the active hover style to all rendered segments of the focused link."""
    if not focused_link_href:
        return strip

    segments = [
        Segment(
            text,
            (
                style + RichStyle(underline=False)
                if style is not None
                and style.meta is not None
                and style.meta.get(ATTACHMENT_REFERENCE_FILENAME_META_KEY) is not None
                else style + link_hover_style
                if style is not None
                and style.meta is not None
                and style.meta.get(MARKDOWN_LINK_HREF_META_KEY) == focused_link_href
                else style
            ),
            control,
        )
        for text, style, control in strip
    ]
    return Strip(segments, strip.cell_length)


def apply_attachment_hover_style_to_strip(
    strip: Strip,
    focused_attachment_filename: str | None,
    attachment_hover_style: RichStyle,
) -> Strip:
    """Apply hover styling to the active attachment chip."""
    if not focused_attachment_filename:
        return strip

    segments = [
        Segment(
            text,
            (
                style + attachment_hover_style
                if style is not None
                and style.meta is not None
                and style.meta.get(ATTACHMENT_REFERENCE_FILENAME_META_KEY)
                == focused_attachment_filename
                else style
            ),
            control,
        )
        for text, style, control in strip
    ]
    return Strip(segments, strip.cell_length)


def apply_attachment_chip_style_to_strip(
    strip: Strip,
    attachment_chip_style: RichStyle,
) -> Strip:
    """Apply base styling to attachment chip segments."""
    segments = [
        Segment(
            text,
            (
                style + attachment_chip_style
                if style is not None
                and style.meta is not None
                and style.meta.get(ATTACHMENT_REFERENCE_FILENAME_META_KEY) is not None
                else style
            ),
            control,
        )
        for text, style, control in strip
    ]
    return Strip(segments, strip.cell_length)


def apply_inline_code_style_to_strip(
    strip: Strip,
    inline_code_style: RichStyle,
) -> Strip:
    """Apply base styling to inline code segments."""
    segments = [
        Segment(
            text,
            (
                style + inline_code_style
                if style is not None
                and style.meta is not None
                and style.meta.get(INLINE_CODE_META_KEY) is True
                else style
            ),
            control,
        )
        for text, style, control in strip
    ]
    return Strip(segments, strip.cell_length)


class WorkItemLinkTooltipProvider:
    """Fetch, cache, and compose tooltip content for internal Jira links."""

    def __init__(self, markdown: 'GojeeraMarkdown') -> None:
        self.markdown = markdown
        self._cache: dict[str, tuple[str, str, str]] = {}
        self._loading: set[str] = set()

    def get_cached(self, work_item_key: str) -> Text | None:
        tooltip_data = self._cache.get(work_item_key)
        if tooltip_data is None:
            return None

        work_item_type, summary, status = tooltip_data
        return build_work_item_tooltip(work_item_type, summary, status)

    def mark_loading(self, work_item_key: str) -> bool:
        if work_item_key in self._loading:
            return False

        self._loading.add(work_item_key)
        return True

    async def load(self, work_item_key: str) -> Text | None:
        try:
            api = getattr(self.markdown.app, 'api', None)
            if api is None:
                return None

            response = await api.get_work_item(
                work_item_id_or_key=work_item_key,
                fields=WORK_ITEM_TOOLTIP_FIELDS,
            )
            if not response.success or not response.result or not response.result.work_items:
                return None

            work_item = response.result.work_items[0]
            summary = getattr(work_item, 'summary', '') or work_item_key
            work_item_type = getattr(work_item, 'work_item_type_name', '') or 'Work Item'
            status = getattr(getattr(work_item, 'status', None), 'name', '') or 'Unknown'
            self._cache[work_item_key] = (work_item_type, summary, status)
            return build_work_item_tooltip(work_item_type, summary, status)
        finally:
            self._loading.discard(work_item_key)


class AttachmentTooltipProvider:
    """Compose tooltip content for attachment references from loaded attachment data."""

    def __init__(self, markdown: _AttachmentTooltipMarkdown) -> None:
        self.markdown = markdown

    def _find_attachment(self, filename: str | None) -> 'Attachment | None':
        if not filename:
            return None

        screen = getattr(self.markdown.app, 'screen', None)
        attachments_widget = getattr(screen, 'work_item_attachments_widget', None)
        attachments = getattr(attachments_widget, 'attachments', None)
        if not attachments:
            return None

        return next((item for item in attachments if item.filename == filename), None)

    def get(self, filename: str | None) -> Text:
        attachment = self._find_attachment(filename)
        if attachment is None:
            return build_attachment_tooltip(filename or None)

        size = attachment.get_size()
        size_text = f'{size} KB' if size is not None else None
        return build_attachment_tooltip(
            attachment.filename,
            mime_type=attachment.get_mime_type() or None,
            size_kb=size_text,
            created_date=attachment.created_date or None,
            author=attachment.display_author or None,
        )


class ExtendedMarkdownParagraph(MarkdownParagraph):
    """Markdown paragraph with checkbox, date, status, and decision styling."""

    COMPONENT_CLASSES = MarkdownParagraph.COMPONENT_CLASSES | {
        'gojeera-inline-code',
        'gojeera-inline-date',
        'gojeera-inline-status-neutral',
        'gojeera-inline-status-error',
        'gojeera-inline-status-info',
        'gojeera-inline-status-success',
        'gojeera-inline-status-warning',
        'gojeera-inline-status-accent',
        'gojeera-inline-status-muted',
        'gojeera-attachment-chip',
        'gojeera-attachment-chip-hover',
        'gojeera-checkbox-unchecked',
        'gojeera-checkbox-checked',
    }

    DEFAULT_CSS = """
    ExtendedMarkdownParagraph {
        & > .gojeera-inline-code {
            background: $surface;
            color: $text-muted;
        }

        & > .gojeera-inline-date {
            background: $surface;
            color: $text;
        }

        & > .gojeera-inline-status-neutral {
            background: $surface;
            color: $text;
            text-style: bold;
        }

        & > .gojeera-inline-status-error {
            background: $error;
            color: $text;
            text-style: bold;
        }

        & > .gojeera-inline-status-info {
            background: $accent-muted;
            color: $text-primary;
            text-style: bold;
        }

        & > .gojeera-inline-status-success {
            background: $success;
            color: $text;
            text-style: bold;
        }

        & > .gojeera-inline-status-warning {
            background: $warning;
            color: $text;
            text-style: bold;
        }

        & > .gojeera-inline-status-accent {
            background: $accent;
            color: $text;
            text-style: bold;
        }

        & > .gojeera-inline-status-muted {
            background: $accent-muted;
            color: $text-primary;
            text-style: bold;
        }

        & > .gojeera-attachment-chip {
            background: $primary-muted;
            color: $text-primary;
            text-style: bold not italic not underline;
        }

        /* This class is used only for render_line hover styling. */
        & > .gojeera-attachment-chip-hover {
            background: $primary-darken-2;
            color: $primary-lighten-2;
            text-style: bold not italic not underline;
        }

        & > .gojeera-checkbox-unchecked {
            color: $accent;
        }

        & > .gojeera-checkbox-checked {
            color: $success;
            text-style: bold;
        }
    }
    """

    _whitespace_pattern = re.compile(r'\s+')
    _date_pattern = re.compile(rf'{re.escape(DATE_INLINE_SENTINEL)}\[date\](.+)')
    _status_pattern = re.compile(r'\[status:([nrbgypt])\](.+)')
    _decision_pattern = re.compile(r'\[decision:([dau])\](.+)')

    def __init__(self, markdown: Markdown, token: Token) -> None:
        super().__init__(markdown, token)
        self._focused_link_href: str | None = None
        self._focused_attachment_filename: str | None = None

    def _token_to_content(self, token: Token) -> Content:
        """Convert token to content with styling."""
        markdown = self._markdown

        if token.children is None:
            return Content('')

        tokens: list[str] = []
        spans: list[Span] = []
        style_stack: list[tuple[Style | str | tuple[Style | str, ...], int]] = []
        position: int = 0

        def add_content(text: str) -> None:
            """Add text to the tokens list, and advance the position."""
            nonlocal position
            tokens.append(text)
            position += len(text)

        def add_style(style: Style | str | tuple[Style | str, ...]) -> None:
            """Add a style to the stack."""
            style_stack.append((style, position))

        def get_active_attachment_filename() -> str | None:
            for style, _start in reversed(style_stack):
                if isinstance(style, tuple):
                    styles = cast(tuple[Style | str, ...], style)
                else:
                    styles = (style,)
                for item in styles:
                    if isinstance(item, Style):
                        if filename := get_attachment_reference_filename(item):
                            return filename
            return None

        def close_tag() -> None:
            style, start = style_stack.pop()
            if isinstance(style, tuple):
                styles = cast(tuple[Style | str, ...], style)
            else:
                styles = (style,)
            for item in styles:
                spans.append(Span(start, position, item))

        status_class_map = {
            'n': 'gojeera-inline-status-neutral',
            'r': 'gojeera-inline-status-error',
            'b': 'gojeera-inline-status-info',
            'g': 'gojeera-inline-status-success',
            'y': 'gojeera-inline-status-warning',
            'p': 'gojeera-inline-status-accent',
            't': 'gojeera-inline-status-muted',
        }

        for child in token.children:
            child_type = child.type

            if child_type == 'text':
                active_attachment_filename = get_active_attachment_filename()
                if active_attachment_filename is not None:
                    add_content(build_attachment_reference_chip_label(active_attachment_filename))
                else:
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
                    add_style('.gojeera-inline-date')
                    add_content(date_text)
                    close_tag()
                    continue

                status_match = self._status_pattern.match(content_text)
                if status_match:
                    color_code = status_match.group(1)
                    status_text = status_match.group(2)

                    add_style(
                        f'.{status_class_map.get(color_code, "gojeera-inline-status-neutral")}'
                    )
                    add_content(status_text)
                    close_tag()
                    continue

                decision_match = self._decision_pattern.match(content_text)
                if decision_match:
                    decision_text = decision_match.group(2)

                    add_content(f'⤷ {decision_text}')
                    continue

                add_style(build_inline_code_style())
                add_content(content_text)
                close_tag()

            elif child_type == 'em_open':
                add_style('.em')

            elif child_type == 'strong_open':
                add_style('.strong')

            elif child_type == 's_open':
                add_style('.s')

            elif child_type == 'link_open':
                href_attr = child.attrs.get('href', '') if child.attrs else ''
                href = href_attr if isinstance(href_attr, str) else str(href_attr)
                attachment_filename = get_attachment_filename_from_href(href)
                if attachment_filename is not None:
                    add_style(build_attachment_reference_style(attachment_filename))
                else:
                    jira_base_url = (
                        markdown.jira_base_url if isinstance(markdown, GojeeraMarkdown) else None
                    )
                    add_style(build_markdown_link_style(href, jira_base_url=jira_base_url))

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
                for i, char in enumerate(plain_text):
                    if has_unchecked and char == '☐':
                        content = content.stylize('.gojeera-checkbox-unchecked', i, i + 1)
                    elif has_checked and char == '☑':
                        content = content.stylize('.gojeera-checkbox-checked', i, i + 1)

        return trim_interactive_span_whitespace(content)

    def set_content(self, content: Content) -> None:
        super().set_content(content)

    def render_line(self, y: int) -> Strip:
        line = super().render_line(y)
        line = apply_inline_code_style_to_strip(
            line,
            self.get_component_rich_style('gojeera-inline-code'),
        )
        line = apply_focused_link_style_to_strip(
            line,
            self._focused_link_href,
            self.link_style_hover,
        )
        line = apply_attachment_chip_style_to_strip(
            line,
            self.get_component_rich_style('gojeera-attachment-chip'),
        )
        return apply_attachment_hover_style_to_strip(
            line,
            self._focused_attachment_filename,
            self.get_component_rich_style('gojeera-attachment-chip-hover'),
        )

    def watch_hover_style(self, previous_hover_style: RichStyle, hover_style: RichStyle) -> None:
        self.highlight_link_id = ''
        focused_link_href = get_markdown_link_href(hover_style)
        if self._focused_link_href != focused_link_href:
            self._focused_link_href = focused_link_href
            self.refresh()

        attachment_filename = get_attachment_reference_filename(hover_style)
        if self._focused_attachment_filename != attachment_filename:
            self._focused_attachment_filename = attachment_filename
            self.refresh()
        if attachment_filename is not None:
            markdown = self._markdown
            if isinstance(markdown, GojeeraMarkdown):
                self.tooltip = markdown.attachment_tooltip_provider.get(attachment_filename or None)
            else:
                self.tooltip = build_attachment_tooltip(attachment_filename or None)
            cast('MainScreen', self.screen).focused_work_item_link_key = None
            return

        work_item_key = get_markdown_link_work_item_key(hover_style)
        cast('MainScreen', self.screen).focused_work_item_link_key = work_item_key
        if work_item_key is None:
            self.tooltip = get_markdown_link_tooltip(hover_style)
            return

        markdown = self._markdown
        if not isinstance(markdown, GojeeraMarkdown):
            self.tooltip = get_markdown_link_tooltip(hover_style)
            return

        cached_tooltip = markdown.work_item_tooltip_provider.get_cached(work_item_key)
        if cached_tooltip is not None:
            self.tooltip = cached_tooltip
            return

        self.tooltip = build_loading_work_item_tooltip()

        if markdown.work_item_tooltip_provider.mark_loading(work_item_key):
            self.run_worker(
                self._load_work_item_tooltip_data(work_item_key),
                exclusive=False,
                thread=False,
            )

    async def _on_click(self, event: events.Click) -> None:
        style_at_pointer = self.get_style_at(event.x, event.y)
        attachment_filename = get_attachment_reference_filename(style_at_pointer)
        if attachment_filename is not None:
            event.prevent_default()
            event.stop()
            self.action_attachment(attachment_filename)
            return

        if event.ctrl:
            work_item_key = get_markdown_link_work_item_key(style_at_pointer)
            if work_item_key is not None:
                fetch_work_items = getattr(self.screen, 'fetch_work_items', None)
                if callable(fetch_work_items):
                    result = fetch_work_items(work_item_key)
                    if isawaitable(result):
                        event.prevent_default()
                        event.stop()
                        self.screen.run_worker(result, exclusive=True)
                        return

        await super()._on_click(event)

    async def _load_work_item_tooltip_data(self, work_item_key: str) -> None:
        """Fetch work item details for tooltips and update the active hover tooltip if needed."""
        markdown = self._markdown
        if not isinstance(markdown, GojeeraMarkdown):
            return

        tooltip = await markdown.work_item_tooltip_provider.load(work_item_key)
        if (
            tooltip is not None
            and get_markdown_link_work_item_key(self.hover_style) == work_item_key
        ):
            self.tooltip = tooltip

    def action_attachment(self, filename: str) -> None:
        screen = self.screen
        navigate_to_attachment = getattr(screen, 'navigate_to_attachment', None)
        if callable(navigate_to_attachment):
            navigate_to_attachment(filename)


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

    GojeeraMarkdown MarkdownH1 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $surface-lighten-1;
    }

    GojeeraMarkdown MarkdownH2 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $surface-lighten-1;
    }

    GojeeraMarkdown MarkdownH3 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $boost;
    }

    GojeeraMarkdown MarkdownH4 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $boost;
    }

    GojeeraMarkdown MarkdownH5 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $boost;
    }

    GojeeraMarkdown MarkdownH6 {
        margin: 0 0 1 0;
        width: auto;
        content-align: left top;
        padding-left: 1;
        padding-right: 1;
        color: $text;
        text-style: bold;
        background: $boost;
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

    GojeeraMarkdown MarkdownBulletList {
        margin: 0 0 1 0;
        padding: 0;
    }

    GojeeraMarkdown MarkdownOrderedList {
        margin: 0 0 1 0;
        padding: 0;
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

    GojeeraMarkdown MarkdownHorizontalRule {
        border-bottom: solid $surface-lighten-1;
    }

    GojeeraMarkdown MarkdownTableContent > .header {
        color: $text-accent;
    }

    GojeeraMarkdown MarkdownTableContent > .markdown-table--header {
        text-style: bold;
    }
    """

    BLOCKS = {
        **Markdown.BLOCKS,
        'paragraph_open': ExtendedMarkdownParagraph,
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
        jira_base_url: str | None = None,
    ) -> None:
        self._last_markdown_content: str | None = None
        self.jira_base_url = jira_base_url
        self.work_item_tooltip_provider = WorkItemLinkTooltipProvider(self)
        self.attachment_tooltip_provider = AttachmentTooltipProvider(self)

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
