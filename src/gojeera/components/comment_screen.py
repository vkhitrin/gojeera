import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Static, TextArea

from gojeera.components.decision_picker_screen import DecisionPickerScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen
from gojeera.config import CONFIGURATION
from gojeera.models import Attachment, WorkItemComment
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
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

logger = logging.getLogger('gojeera')

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class CommentScreen(ExtendedModalScreen[dict[str, object] | None]):
    """Unified screen for creating and editing comments.

    Args:
        mode: Either 'new' or 'edit' to determine the screen mode.
        work_item_key: The work item key for the comment.
        comment_id: The comment ID (only used in edit mode).
        initial_text: Initial text for the comment (only used in edit mode).
    """

    BINDINGS = ExtendedModalScreen.BINDINGS + [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
        ('ctrl+y', 'paste_clipboard_attachment', 'Clipboard'),
    ]

    def __init__(
        self,
        mode: str = 'new',
        work_item_key: str | None = None,
        comment_id: str | None = None,
        initial_text: str = '',
    ):
        super().__init__()
        self.mode = mode
        self.work_item_key = work_item_key
        self.comment_id = comment_id
        self.initial_text = initial_text
        self._modal_title: str

        title_prefix = 'Edit Comment' if mode == 'edit' else 'New Comment'
        if work_item_key is not None:
            self._modal_title = f'{title_prefix} - Work Item {work_item_key}'
        else:
            self._modal_title = title_prefix
        self._clipboard_attachment_paths: list[Path] = []
        self._clipboard_attachment_names: list[str] = []
        self._uploaded_clipboard_attachments: list[Attachment] = []
        self._submitted_comment: WorkItemComment | None = None

    @property
    def comment_field(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def comment_textarea(self) -> TextArea:
        return self.comment_field.query_one(TextArea)

    @property
    def save_button(self) -> Button:
        button_id = (
            '#edit-comment-button-save' if self.mode == 'edit' else '#add-comment-button-save'
        )
        return self.query_one(button_id, expect_type=Button)

    @property
    def cancel_button(self) -> Button:
        button_id = (
            '#edit-comment-button-quit' if self.mode == 'edit' else '#add-comment-button-quit'
        )
        return self.query_one(button_id, expect_type=Button)

    def compose(self) -> ComposeResult:
        save_button_id = (
            'edit-comment-button-save' if self.mode == 'edit' else 'add-comment-button-save'
        )
        cancel_button_id = (
            'edit-comment-button-quit' if self.mode == 'edit' else 'add-comment-button-quit'
        )

        save_disabled = False if self.mode == 'edit' else True

        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='modal-form-scroll'):
                with Vertical(id='comment-field-container'):
                    comment_label = Label('Comment')
                    comment_label.add_class('field_label')
                    yield comment_label

                    yield ExtendedADFMarkdownTextArea(field_id='comment', required=False)

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Save',
                    variant='success',
                    id=save_button_id,
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=save_disabled,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id=cancel_button_id,
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )
        yield ExtendedFooter()

    def on_mount(self) -> None:
        if self.initial_text:
            self.comment_field.text = self.initial_text

        if CONFIGURATION.get().jumper.enabled:
            self.comment_field.make_jumpable()

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.cancel_button, 'click')
        self.call_after_refresh(lambda: focus_first_available(self.comment_field))

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    def action_insert_mention(self) -> None:
        from gojeera.utils.mention_helpers import insert_user_mention

        self.run_worker(
            insert_user_mention(
                app=self.app,
                target_widget=self.comment_field,
                work_item_key=self.work_item_key,
            ),
            exclusive=False,
        )

    def action_insert_decision(self) -> None:
        self.run_worker(self._insert_decision_worker(), exclusive=False)

    async def _insert_decision_worker(self) -> None:
        textarea = self.comment_textarea
        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(DecisionPickerScreen())

        if result:
            marker, label = result

            insertion_text = f'> `{marker}` '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    def action_insert_alert(self) -> None:
        self.run_worker(self._insert_alert_worker(), exclusive=False)

    async def _insert_alert_worker(self) -> None:
        textarea = self.comment_textarea
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
        textarea = self.comment_field.query_one(TextArea)
        textarea.focus()
        textarea.insert(references)

        attachment_label = 'attachment' if len(staged_paths) == 1 else 'attachments'
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
        self.query_one('#modal_footer').loading = submitting
        self.save_button.disabled = submitting
        self.cancel_button.disabled = submitting

    def _build_final_comment_text(self, raw_text: str) -> str:
        application = cast('JiraApp', self.app)
        uploaded_by_name = {
            attachment.filename: attachment for attachment in self._uploaded_clipboard_attachments
        }
        ordered_uploaded_attachments = [
            uploaded_by_name.get(filename) for filename in self._clipboard_attachment_names
        ]
        return prepare_staged_attachment_text(
            materialize_staged_attachment_references(
                raw_text,
                self._clipboard_attachment_names,
                ordered_uploaded_attachments,
                app=application,
            )
        ).strip()

    async def _upload_clipboard_attachments(self) -> tuple[list[Attachment], list[str], list[str]]:
        if not self.work_item_key or not self._clipboard_attachment_paths:
            return [], [], []

        application = cast('JiraApp', self.app)
        return await application.upload_staged_attachments(
            self.work_item_key,
            [str(path) for path in self._clipboard_attachment_paths],
        )

    async def _submit_comment(self) -> None:
        if not self.work_item_key:
            return

        raw_text = self.comment_field.text or ''
        application = cast('JiraApp', self.app)
        self._set_submitting(True)

        base_text = (
            prepare_staged_attachment_text(raw_text).strip()
            if self._clipboard_attachment_names
            else raw_text.strip()
        )
        if not base_text and not self._clipboard_attachment_names:
            self._set_submitting(False)
            return

        current_comment = self._submitted_comment
        if self.mode == 'edit':
            if not self.comment_id:
                self._set_submitting(False)
                return
            response = await application.api.update_comment(
                self.work_item_key,
                self.comment_id,
                base_text,
            )
            if not response.success or not isinstance(response.result, WorkItemComment):
                self.notify(
                    f'Failed to update the comment: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )
                self._set_submitting(False)
                return
            current_comment = response.result
            self._submitted_comment = response.result
        elif self._submitted_comment is None and base_text:
            response = await application.api.add_comment(
                self.work_item_key,
                base_text,
            )
            if not response.success or not isinstance(response.result, WorkItemComment):
                self.notify(
                    f'Failed to add the comment: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )
                self._set_submitting(False)
                return
            current_comment = response.result
            self._submitted_comment = response.result

        if self._clipboard_attachment_paths:
            (
                uploaded_attachments,
                upload_errors,
                failed_file_paths,
            ) = await self._upload_clipboard_attachments()
            self._uploaded_clipboard_attachments.extend(uploaded_attachments)
            self._clipboard_attachment_paths = [Path(path) for path in failed_file_paths]

            if upload_errors:
                self.notify(
                    f'Failed to upload clipboard attachments: {"; ".join(upload_errors)}',
                    severity='error',
                    title=self.work_item_key,
                )
                self._set_submitting(False)
                return

        final_text = (
            self._build_final_comment_text(raw_text)
            if self._clipboard_attachment_names
            else base_text
        )
        if not final_text:
            self._set_submitting(False)
            return

        if self._submitted_comment is None:
            response = await application.api.add_comment(
                self.work_item_key,
                final_text,
            )
            if not response.success or not isinstance(response.result, WorkItemComment):
                self.notify(
                    f'Failed to add the comment: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )
                self._set_submitting(False)
                return
            current_comment = response.result
            self._submitted_comment = response.result
        elif final_text != base_text or self.mode == 'edit':
            response = await application.api.update_comment(
                self.work_item_key,
                self._submitted_comment.id,
                final_text,
            )
            if not response.success or not isinstance(response.result, WorkItemComment):
                self.notify(
                    f'Failed to update the comment: {response.error}',
                    severity='error',
                    title=self.work_item_key,
                )
                self._set_submitting(False)
                return
            current_comment = response.result
            self._submitted_comment = response.result

        self.dismiss(
            {
                'comment': current_comment,
                'comment_body_markdown': final_text,
                'uploaded_attachments': self._uploaded_clipboard_attachments,
                'mode': self.mode,
            }
        )

    @on(TextArea.Changed, '#comment-textarea')
    def validate_comment(self, event: TextArea.Changed):
        value = self.comment_field.text
        self.save_button.disabled = False if (value and value.strip()) else True

    @on(Button.Pressed, '#add-comment-button-save')
    def handle_save_new(self) -> None:
        self.run_worker(self._submit_comment(), exclusive=True)

    @on(Button.Pressed, '#edit-comment-button-save')
    def handle_save_edit(self) -> None:
        self.run_worker(self._submit_comment(), exclusive=True)

    @on(Button.Pressed, '#add-comment-button-quit')
    def handle_cancel_new(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, '#edit-comment-button-quit')
    def handle_cancel_edit(self) -> None:
        self.app.pop_screen()
