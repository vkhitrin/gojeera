from textual import events
from textual.widgets import TextArea

from gojeera.utils.system.clipboard import (
    stage_non_text_clipboard_attachments,
)
from gojeera.widgets.markdown.external_editor_mixin import (
    EXTERNAL_EDITOR_BINDING,
    ExternalEditorMixin,
)


class ExtendedTextArea(ExternalEditorMixin, TextArea):
    """Text area widget with support for editing via an external editor."""

    BINDINGS = TextArea.BINDINGS + [EXTERNAL_EDITOR_BINDING]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._suppressed_paste_insert: str | None = None

    def action_open_external_editor(self) -> None:
        if getattr(self, 'read_only', False):
            return

        edited_text = self.run_external_editor(self.text, suffix='.gojeera.md')
        if edited_text is None:
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
