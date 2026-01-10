from datetime import datetime
import logging
import re

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, ItemGrid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Static, TextArea

from gojeera.components.decision_picker_screen import DecisionPickerScreen
from gojeera.components.panel_picker_screen import PanelPickerScreen
from gojeera.config import CONFIGURATION
from gojeera.utils.fields import FieldMode
from gojeera.utils.mention_helpers import insert_user_mention
from gojeera.widgets.date_input import DateInput
from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks

logger = logging.getLogger('gojeera')


class TimeSpentInput(Input):
    def __init__(self, initial_value: str | None = None):
        super().__init__(value=initial_value or '', placeholder='E.g. 1w 1d', valid_empty=False)
        self.tooltip = 'Enter the amount of time you work on this task'
        self.compact = True


class TimeRemainingInput(Input):
    def __init__(self, initial_value: str | None = None):
        super().__init__(value=initial_value, placeholder='E.g. 1d 1h 30m')
        self.tooltip = 'Optionally, enter the time remaining in the task'
        self.compact = True


class LogDateTimeInput(DateInput):
    TEMPLATE = '9999-99-99 99:99'
    PLACEHOLDER = '1970-01-01 00:00'

    def __init__(self, initial_value: str | None = None):
        super().__init__(
            mode=FieldMode.CREATE, field_id='log_datetime', title='Date Started', required=True
        )

        self.template = self.TEMPLATE
        self.placeholder = self.PLACEHOLDER
        self.tooltip = 'Enter the date/time on which the work was done'

        self.value = initial_value or datetime.now().strftime('%Y-%m-%d %H:%M')
        self.compact = True


class LogWorkScreen(ModalScreen[dict]):
    """A modal screen to allow the user to log work or edit existing worklog for a work item."""

    BINDINGS = [
        ('escape', 'dismiss_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(
        self,
        work_item_key: str,
        mode: str = 'new',
        current_remaining_estimate: str | None = None,
        worklog_id: str | None = None,
        time_spent: str | None = None,
        started: str | None = None,
        description: str | None = None,
    ):
        super().__init__()
        self._work_item_key = work_item_key
        self._mode = mode
        self._current_remaining_estimate = current_remaining_estimate
        self._worklog_id = worklog_id
        self._initial_time_spent = time_spent
        self._initial_started = started
        self._initial_description = description

        if mode == 'edit':
            self._modal_title: str = f'Edit Work Log - {work_item_key}'
        else:
            self._modal_title: str = f'Log Work - {work_item_key}'

    @property
    def work_log_items_container(self) -> VerticalScroll:
        return self.query_one(VerticalScroll)

    @property
    def time_spent_input(self) -> TimeSpentInput:
        return self.query_one(TimeSpentInput)

    @property
    def time_remaining_input(self) -> TimeRemainingInput:
        return self.query_one(TimeRemainingInput)

    @property
    def log_date_time_input(self) -> LogDateTimeInput:
        return self.query_one(LogDateTimeInput)

    @property
    def work_description_input(self) -> ExtendedADFMarkdownTextArea:
        return self.query_one(ExtendedADFMarkdownTextArea)

    @property
    def save_button(self) -> Button:
        return self.query_one('#log-work-button-save', expect_type=Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='log-work-form'):
                with ItemGrid(id='time-fields-grid'):
                    with Vertical(id='time-spent-container'):
                        yield Label('Time Spent (*)').add_class('field_label')
                        yield TimeSpentInput(initial_value=self._initial_time_spent)
                    with Vertical(id='time-remaining-container'):
                        yield Label('Time Remaining').add_class('field_label')
                        yield TimeRemainingInput(initial_value=self._current_remaining_estimate)

                with Vertical(id='datetime-container'):
                    yield Label('Date Started').add_class('field_label')
                    yield LogDateTimeInput(initial_value=self._initial_started)
                    yield Label('w = week | d = day | h = hour | m = minutes', id='time-hint')

                with Vertical(id='description-container'):
                    yield Label('Work Description').add_class('field_label')
                    yield ExtendedADFMarkdownTextArea(field_id='work_description', required=False)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Save',
                    variant='success',
                    id='log-work-button-save',
                    disabled=False if self._mode == 'edit' else True,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id='log-work-button-quit', compact=True)
        yield Footer()

    def on_mount(self) -> None:
        if self._mode == 'edit' and self._initial_description:
            self.work_description_input.text = self._initial_description

        if CONFIGURATION.get().jumper.enabled:
            self.time_spent_input.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.time_remaining_input.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.log_date_time_input.jump_mode = 'focus'  # type: ignore[attr-defined]

            self.work_description_input.make_jumpable()

            self.save_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#log-work-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    async def action_insert_mention(self) -> None:
        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
        except Exception:
            return

        await insert_user_mention(
            app=self.app,
            target_widget=description_widget,
            work_item_key=self._work_item_key,
        )

    async def action_insert_decision(self) -> None:
        try:
            description_widget = self.query_one(ExtendedADFMarkdownTextArea)
            textarea = description_widget.query_one(TextArea)
        except Exception:
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
        except Exception:
            return

        cursor_position = textarea.cursor_location

        result = await self.app.push_screen_wait(PanelPickerScreen())

        if result:
            marker, alert_type = result

            insertion_text = f'> {marker}\n> '

            textarea.focus()
            textarea.move_cursor(cursor_position)

            textarea.insert(insertion_text)

    def action_dismiss_screen(self) -> None:
        self.dismiss({})

    @on(Input.Changed, 'TimeSpentInput')
    def validate_time_spent(self, event: Input.Changed) -> None:
        self._toggle_widgets(
            time_spent_value=event.value,
            time_remaining_value=self.time_remaining_input.value,
        )

    @on(Input.Changed, 'TimeRemainingInput')
    def validate_time_remaining(self, event: Input.Changed) -> None:
        self._toggle_widgets(
            time_spent_value=self.time_spent_input.value,
            time_remaining_value=event.value,
        )

    @on(Input.Blurred, 'LogDateTimeInput')
    def validate_date_time(self, event: Input.Changed) -> None:
        if not event.value:
            self.save_button.disabled = True
        else:
            try:
                datetime.strptime(event.value, '%Y-%m-%d %H:%M')

                self._toggle_widgets(
                    time_spent_value=self.time_spent_input.value,
                    time_remaining_value=self.time_remaining_input.value,
                )
            except ValueError:
                self.save_button.disabled = True

    @on(TextArea.Changed, '#work_description-textarea')
    def validate_description(self, event: TextArea.Changed) -> None:
        pass

    def on_click(self) -> None:
        self.dismiss({})

    @staticmethod
    def _valid_time_expression(value: str) -> bool:
        if not value:
            return False
        if not (cleaned_value := value.strip()):
            return False
        if re.match(r'^\d+[wdhm](\s\d+[wdhm])*$', cleaned_value, re.IGNORECASE):
            return True
        return False

    def _toggle_widgets(
        self,
        time_spent_value: str,
        time_remaining_value: str,
    ) -> None:
        if not time_spent_value and not time_remaining_value:
            self.save_button.disabled = True
        elif time_spent_value and not time_remaining_value:
            valid_time_spent = self._valid_time_expression(time_spent_value)
            self.save_button.disabled = not valid_time_spent
        elif not time_spent_value and time_remaining_value:
            self.save_button.disabled = True
        else:
            valid_time_spent = self._valid_time_expression(time_spent_value)
            self.save_button.disabled = not valid_time_spent

            if (not self._current_remaining_estimate and time_remaining_value) or (
                self._current_remaining_estimate
                and time_remaining_value
                and time_remaining_value != self._current_remaining_estimate
            ):
                valid_time_remaining = self._valid_time_expression(time_remaining_value)
                self.save_button.disabled = self.save_button.disabled or not valid_time_remaining

    @on(Button.Pressed, '#log-work-button-quit')
    def handle_quit_button(self) -> None:
        self.dismiss({})

    @on(Button.Pressed, '#log-work-button-save')
    def handle_save_button(self) -> None:
        result = {
            'time_spent': self.time_spent_input.value,
            'time_remaining': self.time_remaining_input.value,
            'description': self.work_description_input.text,
            'started': (
                self.log_date_time_input.value.replace(' ', 'T')
                if self.log_date_time_input.value
                else None
            ),
            'current_remaining_estimate': self._current_remaining_estimate,
            'mode': self._mode,
        }
        if self._mode == 'edit':
            result['worklog_id'] = self._worklog_id
        self.dismiss(result)
