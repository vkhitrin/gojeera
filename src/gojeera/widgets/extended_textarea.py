from textual.binding import Binding
from textual.widgets import TextArea

from gojeera.utils.external_editor import (
    ExternalEditorError,
    edit_text_in_external_editor,
)


class ExtendedTextArea(TextArea):
    """Text area widget with support for editing via an external editor."""

    BINDINGS = TextArea.BINDINGS + [
        Binding(
            key='f2',
            action='open_external_editor',
            description='Edit',
            show=True,
        )
    ]

    def action_open_external_editor(self) -> None:
        if getattr(self, 'read_only', False):
            return

        try:
            with self.app.suspend():
                edited_text = edit_text_in_external_editor(self.text, suffix='.gojeera.md')
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

        self.text = edited_text
        self.focus()
