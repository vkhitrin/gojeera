from textual import events
from textual.binding import Binding
from textual.widgets import TextArea

from gojeera.utils.clipboard import (
    stage_non_text_clipboard_attachments,
)
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._suppressed_paste_insert: str | None = None

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

    def action_paste(self) -> None:
        if getattr(self, 'read_only', False):
            return
        return

    def _replace_via_keyboard(self, insert: str, start, end):
        if self._suppressed_paste_insert == insert:
            self._suppressed_paste_insert = None
            return None

        return super()._replace_via_keyboard(insert, start, end)

    async def _on_paste(self, event: events.Paste) -> None:
        if getattr(self, 'read_only', False):
            event.stop()
            return

        staged_paths = stage_non_text_clipboard_attachments(event.text)
        if staged_paths:
            screen_handler = getattr(self.screen, 'handle_staged_clipboard_attachments', None)
            if callable(screen_handler):
                self._suppressed_paste_insert = event.text
                screen_handler(staged_paths)
                event.stop()
                self.focus()
                return

        if result := self._replace_via_keyboard(event.text, *self.selection):
            self._suppressed_paste_insert = event.text
            self.move_cursor(result.end_location)
            self.focus()
        event.stop()
