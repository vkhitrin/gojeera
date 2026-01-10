"""Custom MarkdownViewer that uses GojeeraMarkdown for rendering."""

from pathlib import Path, PurePath
from typing import Callable

from markdown_it import MarkdownIt
from textual import events
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.reactive import reactive, var
from textual.widgets import Markdown
from textual.widgets._markdown import (
    MarkdownBlock,
    MarkdownTableOfContents,
    Navigator,
)

from gojeera.widgets.gojeera_markdown import GojeeraMarkdown


class GojeeraMarkdownViewer(VerticalScroll, can_focus=False, can_focus_children=True):
    """A Markdown viewer widget that uses GojeeraMarkdown for rendering."""

    DEFAULT_CSS = """
    GojeeraMarkdownViewer {
        height: 1fr;
        scrollbar-gutter: stable;
        background: $surface;
        & > MarkdownTableOfContents {
            display: none;
            dock: left;
        }
    }

    GojeeraMarkdownViewer.-show-table-of-contents > MarkdownTableOfContents {
        display: block;
    }
    """

    show_table_of_contents = reactive(True)

    navigator: var[Navigator] = var(Navigator)  # type: ignore[invalid-assignment]

    def __init__(
        self,
        markdown: str | None = None,
        *,
        show_table_of_contents: bool = True,
        name: str | None = None,
        id: str | None = None,  # noqa: A002
        classes: str | None = None,
        parser_factory: Callable[[], MarkdownIt] | None = None,
        open_links: bool = True,
    ):
        super().__init__(name=name, id=id, classes=classes)
        self.show_table_of_contents = show_table_of_contents
        self._markdown = markdown
        self._parser_factory = parser_factory
        self._open_links = open_links

    @property
    def document(self) -> GojeeraMarkdown:
        return self.query_one(GojeeraMarkdown)

    @property
    def table_of_contents(self) -> MarkdownTableOfContents:
        return self.query_one(MarkdownTableOfContents)

    def _on_mount(self, event: events.Mount) -> None:
        pass

    async def go(self, location: str | PurePath) -> None:
        path, anchor = self.document.sanitize_location(str(location))
        if path == Path('.') and anchor:
            self.document.goto_anchor(anchor)
        else:
            await self.document.load(self.navigator.go(location))

    async def back(self) -> None:
        if self.navigator.back():
            await self.document.load(self.navigator.location)

    async def forward(self) -> None:
        if self.navigator.forward():
            await self.document.load(self.navigator.location)

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.stop()

        if self._open_links:
            await self.go(message.href)

    def watch_show_table_of_contents(self, show_table_of_contents: bool) -> None:
        self.set_class(show_table_of_contents, '-show-table-of-contents')

    def compose(self) -> ComposeResult:
        markdown = GojeeraMarkdown(
            markdown=self._markdown,
            parser_factory=self._parser_factory,
            open_links=self._open_links,
        )
        markdown.can_focus = True
        yield markdown
        yield MarkdownTableOfContents(markdown)

    def _on_markdown_table_of_contents_updated(
        self, message: Markdown.TableOfContentsUpdated
    ) -> None:
        self.query_one(MarkdownTableOfContents).table_of_contents = message.table_of_contents
        message.stop()

    def _on_markdown_table_of_contents_selected(
        self, message: Markdown.TableOfContentsSelected
    ) -> None:
        block_selector = f'#{message.block_id}'
        block = self.query_one(block_selector, MarkdownBlock)
        self.scroll_to_widget(block, top=True)
        message.stop()
