import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from textual.containers import Vertical
from textual.widgets import Label

from gojeera.components.screens.decision_picker_screen import DecisionPickerScreen
from gojeera.components.screens.panel_picker_screen import PanelPickerScreen
from gojeera.internal.models.jira import Attachment
from gojeera.utils.system.clipboard_attachments import (
    cleanup_staged_clipboard_attachments,
    stage_clipboard_attachments_into_textarea,
)
from gojeera.utils.ui.textarea_insertion import insert_picker_markup_from_getter
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea

if TYPE_CHECKING:
    from textual.app import App
    from textual.widgets import TextArea


logger = logging.getLogger('gojeera')


class DescriptionActionsHost(Protocol):
    app: 'App'
    description_textarea: 'TextArea'

    def notify(self, message: str, *args, **kwargs) -> None: ...


class DescriptionActionsMixin:
    _clipboard_attachment_paths: list[Path]
    _clipboard_attachment_names: list[str]
    _uploaded_clipboard_attachments: list[Attachment]

    def _clipboard_attachment_title(self) -> str | None:
        raise NotImplementedError

    def compose_description_field(self):
        with Vertical(id='description-field-container'):
            description_label = Label('Description')
            description_label.add_class('field_label')
            yield description_label
            yield ExtendedADFMarkdownTextArea(field_id='description', required=False)

    async def action_insert_decision(self) -> None:
        host = cast(DescriptionActionsHost, self)
        await insert_picker_markup_from_getter(
            app=host.app,
            get_textarea=lambda: host.description_textarea,
            picker_screen=DecisionPickerScreen(),
            build_insertion_text=lambda result: f'> `{result[0]}` ',
            logger=logger,
            error_context='Description widget or TextArea',
        )

    async def action_insert_alert(self) -> None:
        host = cast(DescriptionActionsHost, self)
        await insert_picker_markup_from_getter(
            app=host.app,
            get_textarea=lambda: host.description_textarea,
            picker_screen=PanelPickerScreen(),
            build_insertion_text=lambda result: f'> {result[0]}\n> ',
            logger=logger,
            error_context='Description widget or TextArea',
        )

    async def action_paste_clipboard_attachment(self) -> None:
        host = cast(DescriptionActionsHost, self)
        stage_clipboard_attachments_into_textarea(
            textarea=host.description_textarea,
            clipboard_attachment_paths=self._clipboard_attachment_paths,
            clipboard_attachment_names=self._clipboard_attachment_names,
            notify=host.notify,
            title=self._clipboard_attachment_title(),
        )

    def _cleanup_staged_attachments(self) -> None:
        cleanup_staged_clipboard_attachments(
            clipboard_attachment_paths=self._clipboard_attachment_paths,
            clipboard_attachment_names=self._clipboard_attachment_names,
            uploaded_clipboard_attachments=self._uploaded_clipboard_attachments,
        )
