import logging
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Select, Static, TextArea

from gojeera.components.screens.decision_picker_screen import DecisionPickerScreen
from gojeera.components.screens.panel_picker_screen import PanelPickerScreen
from gojeera.internal.models.jira import Attachment
from gojeera.internal.models.work_items import WorkItemComment
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.system.clipboard import prepare_staged_attachment_text
from gojeera.utils.system.clipboard_attachments import (
    cleanup_staged_clipboard_attachments,
    materialize_uploaded_attachment_references,
    stage_clipboard_attachments_into_textarea,
    upload_staged_clipboard_attachments_for_submission,
)
from gojeera.utils.ui.focus import focus_first_available
from gojeera.utils.ui.textarea_insertion import insert_picker_markup_from_getter
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.selection.vim_select import VimSelect

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
        ('ctrl+y', 'paste_clipboard_attachment', 'Clipboard'),
    ]

    def __init__(
        self,
        mode: str = 'new',
        work_item_key: str | None = None,
        comment_id: str | None = None,
        initial_text: str = '',
        work_item_is_service_desk: bool = False,
        jsd_public: bool = True,
    ):
        super().__init__()
        self.mode = mode
        self.work_item_key = work_item_key
        self.comment_id = comment_id
        self.initial_text = initial_text
        self.work_item_is_service_desk = work_item_is_service_desk
        self.jsd_public = jsd_public
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

    @property
    def show_service_desk_visibility_toggle(self) -> bool:
        return self.mode == 'new' and self.work_item_is_service_desk

    def compose(self) -> ComposeResult:
        save_button_id = (
            'edit-comment-button-save' if self.mode == 'edit' else 'add-comment-button-save'
        )
        cancel_button_id = (
            'edit-comment-button-quit' if self.mode == 'edit' else 'add-comment-button-quit'
        )

        save_disabled = False if self.mode == 'edit' else True

        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with Vertical(id='modal-form-scroll'):
                with Vertical(id='comment-field-container'):
                    if self.show_service_desk_visibility_toggle:
                        with Horizontal(id='comment-header-row'):
                            yield Label('Visibility', classes='field_label')
                            yield VimSelect(
                                options=[
                                    ('Public', 'public'),
                                    ('Internal', 'internal'),
                                ],
                                value='public' if self.jsd_public else 'internal',
                                id='comment-visibility-select',
                                allow_blank=False,
                                compact=True,
                            )

                    yield ExtendedADFMarkdownTextArea(field_id='comment', required=False)

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield build_modal_confirm_button(
                    Button, button_id=save_button_id, disabled=save_disabled
                )
                yield build_modal_cancel_button(Button, button_id=cancel_button_id)
        yield ExtendedFooter()

    def on_mount(self) -> None:
        if self.initial_text:
            self.comment_field.text = self.initial_text

        if CONFIGURATION.get().jumper.enabled:
            self.comment_field.make_jumpable()

            set_jump_mode(self.save_button, 'click')
            set_jump_mode(self.cancel_button, 'click')
            if self.show_service_desk_visibility_toggle:
                set_jump_mode(self.query_one('#comment-visibility-select', VimSelect), 'click')
        self.call_after_refresh(lambda: focus_first_available(self.comment_field))

    def action_insert_mention(self) -> None:
        from gojeera.utils.ui.mention_helpers import insert_user_mention

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

    async def _insert_comment_picker_markup(self, *, picker_screen, build_insertion_text) -> None:
        await insert_picker_markup_from_getter(
            app=self.app,
            get_textarea=lambda: self.comment_textarea,
            picker_screen=picker_screen,
            build_insertion_text=build_insertion_text,
            logger=logger,
            error_context='Comment field or TextArea',
        )

    async def _insert_decision_worker(self) -> None:
        await self._insert_comment_picker_markup(
            picker_screen=DecisionPickerScreen(),
            build_insertion_text=lambda result: f'> `{result[0]}` ',
        )

    def action_insert_alert(self) -> None:
        self.run_worker(self._insert_alert_worker(), exclusive=False)

    async def _insert_alert_worker(self) -> None:
        await self._insert_comment_picker_markup(
            picker_screen=PanelPickerScreen(),
            build_insertion_text=lambda result: f'> {result[0]}\n> ',
        )

    async def action_paste_clipboard_attachment(self) -> None:
        stage_clipboard_attachments_into_textarea(
            textarea=self.comment_textarea,
            clipboard_attachment_paths=self._clipboard_attachment_paths,
            clipboard_attachment_names=self._clipboard_attachment_names,
            notify=self.notify,
        )

    def on_unmount(self) -> None:
        cleanup_staged_clipboard_attachments(
            clipboard_attachment_paths=self._clipboard_attachment_paths,
            clipboard_attachment_names=self._clipboard_attachment_names,
            uploaded_clipboard_attachments=self._uploaded_clipboard_attachments,
        )

    def _set_submitting(self, submitting: bool) -> None:
        self.query_one('#modal_footer').loading = submitting
        self.save_button.disabled = submitting
        self.cancel_button.disabled = submitting

    def _build_final_comment_text(self, raw_text: str) -> str:
        application = cast('JiraApp', self.app)
        return materialize_uploaded_attachment_references(
            raw_text=raw_text,
            clipboard_attachment_names=self._clipboard_attachment_names,
            uploaded_clipboard_attachments=self._uploaded_clipboard_attachments,
            app=application,
        )

    async def _upload_clipboard_attachments(self) -> bool:
        if not self.work_item_key or not self._clipboard_attachment_paths:
            return True

        application = cast('JiraApp', self.app)
        uploaded_attachments = await upload_staged_clipboard_attachments_for_submission(
            application,
            self.work_item_key,
            self._clipboard_attachment_paths,
            self._uploaded_clipboard_attachments,
            self.notify,
            self._set_submitting,
            notify_success=False,
        )
        return uploaded_attachments is not None

    async def _create_comment(self, comment_text: str) -> WorkItemComment | None:
        if not self.work_item_key:
            return None

        application = cast('JiraApp', self.app)
        response = await application.api.add_comment(
            self.work_item_key,
            comment_text,
            jsd_public=self.jsd_public if self.show_service_desk_visibility_toggle else None,
        )
        if not response.success or not isinstance(response.result, WorkItemComment):
            return self._handle_comment_submit_failure('add', response.error)

        self._submitted_comment = response.result
        return response.result

    def _handle_comment_submit_failure(
        self, action: str, error: str | None
    ) -> WorkItemComment | None:
        self.notify(
            f'Failed to {action} the comment: {error}',
            severity='error',
            title=self.work_item_key or '',
        )
        self._set_submitting(False)
        return None

    async def _update_comment(
        self, comment_text: str, comment_id: str | None = None
    ) -> WorkItemComment | None:
        target_comment_id = comment_id or (
            self._submitted_comment.id if self._submitted_comment is not None else None
        )
        if not self.work_item_key or target_comment_id is None:
            return None

        application = cast('JiraApp', self.app)
        response = await application.api.update_comment(
            self.work_item_key,
            target_comment_id,
            comment_text,
        )
        if not response.success or not isinstance(response.result, WorkItemComment):
            return self._handle_comment_submit_failure('update', response.error)

        self._submitted_comment = response.result
        return response.result

    async def _submit_comment(self) -> None:
        if not self.work_item_key:
            return

        raw_text = self.comment_field.text or ''
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
            current_comment = await self._update_comment(base_text, comment_id=self.comment_id)
            if current_comment is None:
                return
        elif self._submitted_comment is None and base_text:
            current_comment = await self._create_comment(base_text)
            if current_comment is None:
                return

        if self._clipboard_attachment_paths:
            if not await self._upload_clipboard_attachments():
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
            current_comment = await self._create_comment(final_text)
            if current_comment is None:
                return
        elif final_text != base_text or self.mode == 'edit':
            current_comment = await self._update_comment(final_text)
            if current_comment is None:
                return

        self.dismiss(
            {
                'comment': current_comment,
                'comment_body_markdown': final_text,
                'uploaded_attachments': self._uploaded_clipboard_attachments,
                'mode': self.mode,
            }
        )

    @on(TextArea.Changed, '#comment-textarea')
    def validate_comment(self, _event: TextArea.Changed):
        value = self.comment_field.text
        self.save_button.disabled = False if (value and value.strip()) else True

    @on(Select.Changed, '#comment-visibility-select')
    def handle_comment_visibility_changed(self, event: Select.Changed) -> None:
        self.jsd_public = event.value != 'internal'

    @on(Button.Pressed, '#add-comment-button-save')
    def handle_save_new(self) -> None:
        self._start_submit_comment()

    @on(Button.Pressed, '#edit-comment-button-save')
    def handle_save_edit(self) -> None:
        self._start_submit_comment()

    @on(Button.Pressed, '#add-comment-button-quit')
    def handle_cancel_new(self) -> None:
        self._cancel()

    @on(Button.Pressed, '#edit-comment-button-quit')
    def handle_cancel_edit(self) -> None:
        self._cancel()

    def _start_submit_comment(self) -> None:
        self.run_worker(self._submit_comment(), exclusive=True)

    def _cancel(self) -> None:
        self.dismiss()
