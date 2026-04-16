import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Static, TextArea

from gojeera.components.decision_picker_screen import DecisionPickerScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen
from gojeera.config import CONFIGURATION
from gojeera.models import Attachment, JiraWorkItem, JiraWorkItemGenericFields
from gojeera.utils.adf_helpers import convert_adf_to_markdown
from gojeera.utils.clipboard import (
    ClipboardAttachmentError,
    build_staged_attachment_reference_text,
    materialize_staged_attachment_references,
    prepare_staged_attachment_text,
    stage_clipboard_attachments,
)
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_input import ExtendedInput
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class EditWorkItemInfoScreen(ExtendedModalScreen[dict[str, str]]):
    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
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
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
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

                with Vertical(id='description-field-container'):
                    description_label = Label('Description')
                    description_label.add_class('field_label')
                    yield description_label

                    yield ExtendedADFMarkdownTextArea(field_id='description', required=False)

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Save',
                    variant='success',
                    id='edit-work-item-button-save',
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='edit-work-item-button-quit',
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )
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

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def _extract_markdown_from_description(self, description) -> str:
        if isinstance(description, dict):
            try:
                base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)
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
    def validate_summary(self, event: Input.Changed):
        self._update_button_state()

    @on(TextArea.Changed, '#description-textarea')
    def validate_description(self, event: TextArea.Changed):
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
        from gojeera.utils.mention_helpers import insert_user_mention

        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
        except Exception as e:
            logger.error(f'Failed to get Description widget: {e}')
            return

        work_item_key = self.work_item.key if self.work_item else None

        await insert_user_mention(
            app=self.app,
            target_widget=description_widget,
            work_item_key=work_item_key,
        )

    async def action_insert_decision(self) -> None:
        try:
            textarea = self.description_textarea
        except Exception as e:
            logger.error(f'Failed to get Description widget or TextArea: {e}')
            return

        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(DecisionPickerScreen())

        if result:
            marker, label = result

            insertion_text = f'> `{marker}` '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    async def action_insert_alert(self) -> None:
        try:
            textarea = self.description_textarea
        except Exception as e:
            logger.error(f'Failed to get Description widget or TextArea: {e}')
            return

        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(PanelPickerScreen())

        if result:
            marker, alert_type = result

            insertion_text = f'> {marker}\n> '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    async def action_paste_clipboard_attachment(self) -> None:
        try:
            staged_paths = stage_clipboard_attachments()
        except ClipboardAttachmentError as error:
            self.notify(str(error), severity='warning')
            return

        if not staged_paths:
            self.notify(
                'Clipboard does not contain a supported file path or text payload.',
                severity='warning',
            )
            return

        self.handle_staged_clipboard_attachments(staged_paths)

    def handle_staged_clipboard_attachments(self, staged_paths: list[Path]) -> None:
        self._clipboard_attachment_paths.extend(staged_paths)
        self._clipboard_attachment_names.extend(path.name for path in staged_paths)

        references = '\n'.join(
            build_staged_attachment_reference_text(path.name) for path in staged_paths
        )
        textarea = self.description_textarea
        textarea.focus()
        textarea.insert(references)

        attachment_label = 'attachment' if len(staged_paths) == 1 else 'attachments'
        if self.work_item:
            self.notify(
                f'Staged {len(staged_paths)} clipboard {attachment_label} for upload.',
                title=self.work_item.key,
            )
        else:
            self.notify(f'Staged {len(staged_paths)} clipboard {attachment_label} for upload.')

    def _cleanup_staged_attachments(self) -> None:
        for path in self._clipboard_attachment_paths:
            try:
                path.unlink(missing_ok=True)
                parent_dir = path.parent
                if parent_dir.name.startswith('gojeera-clipboard-'):
                    parent_dir.rmdir()
            except OSError:
                pass
        self._clipboard_attachment_paths.clear()
        self._clipboard_attachment_names.clear()
        self._uploaded_clipboard_attachments.clear()

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
                uploaded_by_name = {
                    attachment.filename: attachment
                    for attachment in self._uploaded_clipboard_attachments
                }
                ordered_uploaded_attachments = [
                    uploaded_by_name.get(filename) for filename in self._clipboard_attachment_names
                ]
                description_to_save = prepare_staged_attachment_text(
                    materialize_staged_attachment_references(
                        description_template,
                        self._clipboard_attachment_names,
                        ordered_uploaded_attachments,
                        app=application,
                    )
                ).strip()

        self.dismiss(
            {
                JiraWorkItemGenericFields.SUMMARY.value: summary,
                JiraWorkItemGenericFields.DESCRIPTION.value: description_to_save,
            }
        )
