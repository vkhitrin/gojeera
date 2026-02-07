import logging

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from gojeera.components.decision_picker_screen import DecisionPickerScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen
from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

logger = logging.getLogger('gojeera')


class CommentScreen(ModalScreen[str]):
    """Unified screen for creating and editing comments.

    Args:
        mode: Either 'new' or 'edit' to determine the screen mode.
        work_item_key: The work item key for the comment.
        comment_id: The comment ID (only used in edit mode).
        initial_text: Initial text for the comment (only used in edit mode).
    """

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
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

    @property
    def comment_field(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def save_button(self) -> Button:
        button_id = (
            '#edit-comment-button-save' if self.mode == 'edit' else '#add-comment-button-save'
        )
        return self.query_one(button_id, expect_type=Button)

    def compose(self) -> ComposeResult:
        form_id = 'edit-comment-form' if self.mode == 'edit' else 'add-comment-form'
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
            with VerticalScroll(id=form_id):
                with Vertical(id='comment-field-container'):
                    yield Label('Comment').add_class('field_label')

                    yield ExtendedADFMarkdownTextArea(field_id='comment', required=False)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id=save_button_id,
                    disabled=save_disabled,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id=cancel_button_id, compact=True)
        yield Footer()

    def on_mount(self) -> None:
        if self.initial_text:
            self.comment_field.text = self.initial_text

        if CONFIGURATION.get().jumper.enabled:
            self.comment_field.make_jumpable()

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            cancel_button_id = (
                '#edit-comment-button-quit' if self.mode == 'edit' else '#add-comment-button-quit'
            )
            self.query_one(cancel_button_id, Button).jump_mode = 'click'  # type: ignore[attr-defined]

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
        textarea = self.comment_field.query_one(TextArea)
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
        textarea = self.comment_field.query_one(TextArea)
        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(PanelPickerScreen())

        if result:
            marker, alert_type = result

            insertion_text = f'> {marker}\n> '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    @on(TextArea.Changed, '#comment-textarea')
    def validate_comment(self, event: TextArea.Changed):
        value = self.comment_field.text
        self.save_button.disabled = False if (value and value.strip()) else True

    @on(Button.Pressed, '#add-comment-button-save')
    def handle_save_new(self) -> None:
        self.dismiss(self.comment_field.text or '')

    @on(Button.Pressed, '#edit-comment-button-save')
    def handle_save_edit(self) -> None:
        self.dismiss(self.comment_field.text or '')

    @on(Button.Pressed, '#add-comment-button-quit')
    def handle_cancel_new(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, '#edit-comment-button-quit')
    def handle_cancel_edit(self) -> None:
        self.app.pop_screen()

    def on_click(self) -> None:
        self.app.pop_screen()
