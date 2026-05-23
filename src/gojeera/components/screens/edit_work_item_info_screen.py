import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static, TextArea

from gojeera.components.screens.description_actions import DescriptionActionsMixin
from gojeera.internal.models.jira import (
    Attachment,
    JiraWorkItemGenericFields,
)
from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown
from gojeera.utils.system.clipboard import prepare_staged_attachment_text
from gojeera.utils.system.clipboard_attachments import (
    materialize_uploaded_attachment_references,
)
from gojeera.utils.ui.focus import focus_first_available
from gojeera.widgets.inputs.extended_input import ExtendedInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.navigation.extended_jumper import set_jump_mode

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class EditWorkItemInfoScreen(DescriptionActionsMixin, ExtendedModalScreen[dict[str, str]]):
    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('ctrl+y', 'paste_clipboard_attachment', 'Clipboard'),
    ]
    TITLE = 'Edit Work Item Info'

    def __init__(self, work_item: JiraWorkItem | None = None):
        super().__init__()
        self.work_item = work_item

        if self.work_item:
            work_item_key: str = self.work_item.key
            self._modal_title = f'{self.TITLE} - {work_item_key}'
        else:
            self._modal_title = self.TITLE

        self._original_summary = self.work_item.summary if self.work_item else ''
        self._original_description = ''
        self._clipboard_attachment_paths: list[Path] = []
        self._clipboard_attachment_names: list[str] = []
        self._uploaded_clipboard_attachments: list[Attachment] = []
        self._is_submitting = False

    @property
    def summary_input(self) -> Input:
        return self.query_one('#edit-work-item-summary', Input)

    @property
    def description_field(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def description_textarea(self) -> TextArea:
        return self.description_field.query_one(TextArea)

    @property
    def save_button(self) -> Button:
        return self.query_one('#edit-work-item-button-save', expect_type=Button)

    @property
    def cancel_button(self) -> Button:
        return self.query_one('#edit-work-item-button-quit', expect_type=Button)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with Vertical(id='edit-work-item-body'):
                with Vertical(id='summary-field-container'):
                    summary_label = Label('Summary')
                    summary_label.add_class('field_label')
                    yield summary_label
                    summary_widget = ExtendedInput(
                        id='edit-work-item-summary',
                        placeholder='Enter a summary',
                        compact=True,
                        value=self.work_item.summary if self.work_item else '',
                    )
                    yield summary_widget

                yield from self.compose_description_field()

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button, button_id='edit-work-item-button-save', disabled=True
                )
                yield build_modal_cancel_button(Button, button_id='edit-work-item-button-quit')
        yield ExtendedFooter()

    def on_mount(self) -> None:
        if self.work_item and self.work_item.description:
            description_value = self._extract_markdown_from_description(self.work_item.description)
            self.description_field.text = description_value

            self._original_description = description_value

        self._update_button_state()

        if CONFIGURATION.get().jumper.enabled:
            set_jump_mode(self.summary_input, 'focus')

            self.description_field.make_jumpable()

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.cancel_button, 'click')
        self.call_after_refresh(
            lambda: focus_first_available(self.summary_input, self.description_field)
        )

    def _extract_markdown_from_description(self, description) -> str:
        if isinstance(description, dict):
            try:
                base_url = getattr(
                    getattr(getattr(self.app, 'atlassian', None), 'server_info', None),
                    'base_url',
                    None,
                )
                return convert_adf_to_markdown(description, base_url=base_url)
            except Exception:
                return ''
        elif isinstance(description, str):
            return description
        return ''

    def _has_changes(self) -> bool:
        current_summary = self.summary_input.value.strip()
        current_description = self.description_field.text.strip()

        return (
            current_summary != self._original_summary.strip()
            or current_description != self._original_description.strip()
        )

    def _update_button_state(self) -> None:
        summary = self.summary_input.value.strip()
        has_summary = bool(summary)
        has_changes = self._has_changes()

        self.save_button.disabled = not (has_summary and has_changes)

    @on(Input.Changed, '#edit-work-item-summary')
    def validate_summary(self, _event: Input.Changed):
        self._update_button_state()

    @on(TextArea.Changed, '#description-textarea')
    def validate_description(self, _event: TextArea.Changed):
        self._update_button_state()

    @on(Button.Pressed, '#edit-work-item-button-save')
    def handle_save(self) -> None:
        if self._is_submitting:
            return

        summary = self.summary_input.value
        if not summary or not summary.strip():
            self.notify('Summary cannot be empty', title='Edit Work Item', severity='error')
            return

        self.run_worker(self._submit_work_item_updates(), exclusive=True)

    @on(Button.Pressed, '#edit-work-item-button-quit')
    def handle_cancel(self) -> None:
        if self._is_submitting:
            return
        self.dismiss()

    async def action_insert_mention(self) -> None:
        from gojeera.utils.ui.mention_helpers import insert_user_mention

        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
        except Exception:
            logger.error('Failed to get Description widget', exc_info=True)
            return

        work_item_key = self.work_item.key if self.work_item else None

        await insert_user_mention(
            app=self.app,
            target_widget=description_widget,
            work_item_key=work_item_key,
        )

    def _clipboard_attachment_title(self) -> str | None:
        return self.work_item.key if self.work_item else None

    def on_unmount(self) -> None:
        self._cleanup_staged_attachments()

    def _set_submitting(self, submitting: bool) -> None:
        self._is_submitting = submitting
        self.query_one('#modal_footer').loading = submitting
        self.save_button.disabled = submitting
        self.cancel_button.disabled = submitting

    async def _submit_work_item_updates(self) -> None:
        summary = self.summary_input.value
        description = self.description_field.text
        work_item = self.work_item

        if not work_item:
            return

        self._set_submitting(True)

        summary_changed = summary.strip() != self._original_summary.strip()
        description_changed = description.strip() != self._original_description.strip()
        description_to_save = description

        if self._clipboard_attachment_paths:
            application = cast('JiraApp', self.app)
            description_template = prepare_staged_attachment_text(description)
            (
                uploaded_attachments,
                upload_errors,
                failed_file_paths,
            ) = await application.upload_staged_attachments(
                work_item.key,
                [str(path) for path in self._clipboard_attachment_paths],
            )
            self._uploaded_clipboard_attachments.extend(uploaded_attachments)
            self._clipboard_attachment_paths = [Path(path) for path in failed_file_paths]

            if uploaded_attachments:
                self.notify(
                    f'Uploaded {len(uploaded_attachments)} clipboard attachment(s)',
                    title=work_item.key,
                )

            if upload_errors:
                self.notify(
                    f'Failed to upload clipboard attachments: {"; ".join(upload_errors)}',
                    severity='error',
                    title=work_item.key,
                )
                self._set_submitting(False)
                return

            if uploaded_attachments and description_template:
                description_to_save = materialize_uploaded_attachment_references(
                    raw_text=description_template,
                    clipboard_attachment_names=self._clipboard_attachment_names,
                    uploaded_clipboard_attachments=self._uploaded_clipboard_attachments,
                    app=application,
                )
                description_changed = (
                    description_to_save.strip() != self._original_description.strip()
                )

        updates = {}
        if summary_changed:
            updates[JiraWorkItemGenericFields.SUMMARY.value] = summary
        if description_changed:
            updates[JiraWorkItemGenericFields.DESCRIPTION.value] = description_to_save

        self.dismiss(updates)
