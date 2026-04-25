from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from textual.binding import Binding

from gojeera.utils.system.external_editor import ExternalEditorError, edit_text_in_external_editor

if TYPE_CHECKING:
    from textual.app import App


class SupportsExternalEditor(Protocol):
    @property
    def app(self) -> App: ...

    def notify(self, message: str, *, title: str = '', severity: str = 'information') -> None: ...


EXTERNAL_EDITOR_BINDING = Binding(
    key='f2',
    action='open_external_editor',
    description='Edit',
    show=True,
)


class ExternalEditorMixin:
    def run_external_editor(self, text: str, *, suffix: str) -> str | None:
        host = cast(SupportsExternalEditor, self)
        try:
            with host.app.suspend():
                return edit_text_in_external_editor(text, suffix=suffix)
        except ExternalEditorError as error:
            host.notify(str(error), title='External Editor', severity='error')
        except Exception as error:
            host.notify(
                f'Failed to open external editor: {error}',
                title='External Editor',
                severity='error',
            )
        return None
