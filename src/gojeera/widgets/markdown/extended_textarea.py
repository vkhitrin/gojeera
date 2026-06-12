from textual.widgets import TextArea

from gojeera.widgets.markdown.external_editor_mixin import (
    EXTERNAL_EDITOR_BINDING,
    ExternalEditorMixin,
)


class ExtendedTextArea(ExternalEditorMixin, TextArea):
    """Text area widget with support for editing via an external editor."""

    BINDINGS = TextArea.BINDINGS + [EXTERNAL_EDITOR_BINDING]

    def __init__(self, *args, **kwargs):
        self._initial_wrap_width_hint = kwargs.pop('initial_wrap_width_hint', None)
        super().__init__(*args, **kwargs)

    @property
    def wrap_width(self) -> int:
        wrap_width = super().wrap_width
        if wrap_width <= 0 and self._initial_wrap_width_hint is not None:
            return self._initial_wrap_width_hint
        return wrap_width

    def action_open_external_editor(self) -> None:
        if getattr(self, 'read_only', False):
            return

        edited_text = self.run_external_editor(self.text, suffix='.gojeera.md')
        if edited_text is None:
            return

        self.text = edited_text
        self.focus()
