from textual.binding import Binding
from textual.widgets import Input

from gojeera.utils.external_editor import (
    ExternalEditorError,
    edit_text_in_external_editor,
)


class ExtendedInput(Input):
    """Input widget with support for editing via an external editor."""

    DEFAULT_CSS = """
    ExtendedInput {
        background: $surface;
        width: 100%;
        height: auto;
    }
    """

    BINDINGS = Input.BINDINGS + [
        Binding(
            key='f2',
            action='open_external_editor',
            description='Edit',
            show=True,
        )
    ]

    @staticmethod
    def _flatten_external_editor_text(text: str) -> str:
        return ' '.join(text.splitlines())

    def action_open_external_editor(self) -> None:
        if self.disabled:
            return

        try:
            with self.app.suspend():
                edited_text = edit_text_in_external_editor(self.value, suffix='.txt')
        except ExternalEditorError as error:
            self.notify(str(error), title='External Editor', severity='error')
            return
        except Exception as error:
            self.notify(
                f'Failed to open external editor: {error}',
                title='External Editor',
                severity='error',
            )
            return

        self.value = self._flatten_external_editor_text(edited_text)
        self.focus()
