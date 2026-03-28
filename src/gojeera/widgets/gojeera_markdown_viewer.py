"""Extended MarkdownViewer using Gojeera markdown rendering."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Markdown, MarkdownViewer, Tree
from textual.widgets._markdown import MarkdownTableOfContents

from gojeera.widgets.gojeera_markdown import GojeeraMarkdown


class ExtendedMarkdownTableOfContentsTree(Tree[dict[str, str] | None]):
    """Tree with vim-style topic navigation for markdown TOCs."""

    BINDINGS = Tree.BINDINGS + [
        Binding('j', 'cursor_down', 'Next topic', show=False),
        Binding('k', 'cursor_up', 'Previous topic', show=False),
    ]

    def __init__(self, label: str) -> None:
        super().__init__(label)
        setattr(self, 'show_root', False)  # noqa: B010
        setattr(self, 'show_guides', True)  # noqa: B010
        setattr(self, 'guide_depth', 4)  # noqa: B010
        setattr(self, 'auto_expand', False)  # noqa: B010


class ExtendedMarkdownTableOfContents(MarkdownTableOfContents):
    """Markdown TOC widget using a vim-navigable tree."""

    def compose(self) -> ComposeResult:
        yield ExtendedMarkdownTableOfContentsTree('TOC')


class ExtendedMarkdownViewer(MarkdownViewer):
    """Markdown viewer using GojeeraMarkdown and vim-style TOC navigation."""

    @property
    def document(self) -> GojeeraMarkdown:
        return self.query_one(GojeeraMarkdown)

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.stop()
        if self._open_links:
            await self.go(message.href)

    def update(self, markdown: str) -> None:
        self.document.update(markdown)

    def compose(self) -> ComposeResult:
        markdown = GojeeraMarkdown(
            parser_factory=self._parser_factory,
            open_links=self._open_links,
        )
        markdown.can_focus = True
        yield markdown
        yield ExtendedMarkdownTableOfContents(markdown)
