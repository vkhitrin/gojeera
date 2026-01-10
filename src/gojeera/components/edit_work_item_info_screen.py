import logging

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static, TextArea

from gojeera.components.decision_picker_screen import DecisionPickerScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen
from gojeera.config import CONFIGURATION
from gojeera.models import JiraWorkItem, JiraWorkItemGenericFields
from gojeera.utils.adf_helpers import convert_adf_to_markdown
from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

logger = logging.getLogger('gojeera')


class EditWorkItemInfoScreen(ModalScreen):
    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
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

    @property
    def summary_input(self) -> Input:
        return self.query_one('#edit-work-item-summary', Input)

    @property
    def description_field(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def save_button(self) -> Button:
        return self.query_one('#edit-work-item-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='edit-work-item-form'):
                with Vertical(id='summary-field-container'):
                    yield Label('Summary').add_class('field_label')
                    summary_widget = Input(
                        id='edit-work-item-summary',
                        placeholder='Enter a summary',
                        compact=True,
                        value=self.work_item.summary if self.work_item else '',
                    )
                    summary_widget.add_class('work_item_details_input_field')
                    yield summary_widget

                with Vertical(id='description-field-container'):
                    yield Label('Description').add_class('field_label')

                    yield ExtendedADFMarkdownTextArea(field_id='description', required=False)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='edit-work-item-button-save',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel', variant='error', id='edit-work-item-button-quit', compact=True
                )
        yield Footer()

    def on_mount(self) -> None:
        if self.work_item and self.work_item.description:
            description_value = self._extract_markdown_from_description(self.work_item.description)
            self.description_field.text = description_value

            self._original_description = description_value

        self._update_button_state()

        if CONFIGURATION.get().jumper.enabled:
            self.query_one('#edit-work-item-summary', Input).jump_mode = 'focus'  # type: ignore[attr-defined]

            self.description_field.make_jumpable()

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#edit-work-item-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

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
        summary = self.summary_input.value
        description = self.description_field.text

        if not summary or not summary.strip():
            self.notify('Summary cannot be empty', title='Edit Work Item', severity='error')
            return

        self.dismiss(
            {
                JiraWorkItemGenericFields.SUMMARY.value: summary,
                JiraWorkItemGenericFields.DESCRIPTION.value: description,
            }
        )

    @on(Button.Pressed, '#edit-work-item-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss({})

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
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
            textarea = description_widget.query_one(TextArea)
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
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
            textarea = description_widget.query_one(TextArea)
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

    def on_click(self) -> None:
        self.dismiss({})
