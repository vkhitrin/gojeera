import inspect
import os

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Footer, LoadingIndicator, Markdown, Static

from gojeera.widgets.gojeera_markdown_viewer import GojeeraMarkdownViewer
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks


class HelpScreen(ModalScreen):
    """The screen that displays help."""

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close Help'),
        ('question_mark', 'app.pop_screen', 'Close Help'),
    ]
    TITLE = 'gojeera Help'

    def __init__(self, anchor: str | None = None):
        super().__init__()
        self._anchor = anchor
        self._content: str = ''
        try:
            in_app_help_filename = self._get_in_app_help_filename()
            with open(in_app_help_filename, 'r', encoding='utf-8') as file:
                self._content = file.read()
        except FileNotFoundError:
            self._content = 'Unable to load the contents of the help. Please refer to https://github.com/vkhitrin/gojeera'

    def compose(self) -> ComposeResult:
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('gojeera Help', id='modal_title')

            yield LoadingIndicator(id='help_loading')
        yield Footer(show_command_palette=False)

    @staticmethod
    def _get_in_app_help_filename() -> str:
        filename = inspect.getfile(HelpScreen)
        directory = os.path.dirname(filename)
        directories = directory.split('/')[:-1]
        directories.append('/usage.md')
        return '/'.join(directories)

    async def on_mount(self):
        self.call_after_refresh(self._load_content)

    async def _load_content(self) -> None:
        viewer = GojeeraMarkdownViewer(
            self._content, show_table_of_contents=True, id='help_viewer', open_links=False
        )

        loading = self.query_one('#help_loading', LoadingIndicator)
        await loading.remove()
        await self.query_one('#modal_outer').mount(viewer)

        if self._anchor:
            await viewer.go(self._anchor.strip())

    def on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.stop()

    def on_click(self) -> None:
        self.app.pop_screen()
