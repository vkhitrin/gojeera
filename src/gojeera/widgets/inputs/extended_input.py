from textual.widgets import Input

from gojeera.widgets.markdown.external_editor_mixin import (
    EXTERNAL_EDITOR_BINDING,
    ExternalEditorMixin,
)


class ExtendedInput(ExternalEditorMixin, Input):
    """Input widget with support for editing via an external editor."""

    DEFAULT_CSS = """
    ExtendedInput {
        background: $surface;
        width: 100%;
        height: auto;
    }
    """

    BINDINGS = Input.BINDINGS + [EXTERNAL_EDITOR_BINDING]

    @staticmethod
    def _flatten_external_editor_text(text: str) -> str:
        return ' '.join(text.splitlines())

    def action_open_external_editor(self) -> None:
        if self.disabled:
            return

        edited_text = self.run_external_editor(self.value, suffix='.txt')
        if edited_text is None:
            return

        self.value = self._flatten_external_editor_text(edited_text)
        self.focus()
