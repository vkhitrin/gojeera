import asyncio
from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from dateutil import parser
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.reactive import Reactive, reactive
from textual.widgets import Input, Label, ProgressBar, Select
from textual.widgets._select import SelectOverlay
from textual_tags import Tag, TagAutoComplete, Tags

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.work_item_summary import WorkItemInfoContainer
from gojeera.components.work_item_work_log_screen import WorkItemWorkLogScreen
from gojeera.components.work_log_screen import LogWorkScreen
from gojeera.config import CONFIGURATION
from gojeera.constants import (
    WorkItemManualUpdateFieldKeys,
    WorkItemUnsupportedUpdateFieldKeys,
)
from gojeera.exceptions import UpdateWorkItemException, ValidationError
from gojeera.models import JiraUser, JiraWorkItem, TimeTracking, WorkItemPriority
from gojeera.utils.fields import FieldMode
from gojeera.utils.styling import map_jira_status_color_to_textual
from gojeera.utils.widgets_factory_utils import (
    DynamicFieldsWidgets,
    DynamicFieldWrapper,
    StaticFieldsWidgets,
    build_dynamic_widgets,
)
from gojeera.utils.work_item_updates import (
    work_item_assignee_has_changed,
    work_item_priority_has_changed,
)
from gojeera.widgets.date_input import DateInput
from gojeera.widgets.date_time_input import DateTimeInput
from gojeera.widgets.multi_select import MultiSelect
from gojeera.widgets.numeric_input import NumericInput
from gojeera.widgets.read_only_input_field import ReadOnlyInputField
from gojeera.widgets.selection import SelectionWidget
from gojeera.widgets.text_input import TextInput
from gojeera.widgets.time_tracking import TimeTrackingWidget
from gojeera.widgets.url import URL
from gojeera.widgets.user_picker import UserPicker
from gojeera.widgets.user_selection_input import UserSelectionInput
from gojeera.widgets.work_item_labels import WorkItemLabels
from gojeera.widgets.work_item_status_selection_input import WorkItemStatusSelectionInput

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')


class WorkItemUpdated(Message):
    """Message posted when a work item has been successfully updated."""

    def __init__(self, work_item: JiraWorkItem) -> None:
        super().__init__()
        self.work_item = work_item


class DateMetadata(VerticalGroup):
    """Container for date/metadata field widgets."""

    DEFAULT_CSS = """
    DateMetadata {
        layout: vertical;
    }

    DateMetadata > * {
        height: auto;
        width: 100%;
    }

    DateMetadata > Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }

    DateMetadata > Horizontal > Label {
        width: 20%;
        min-width: 15;
        max-width: 30;
        padding-right: 2;
        text-style: bold;
    }

    DateMetadata > Horizontal > DateInput,
    DateMetadata > Horizontal > ReadOnlyInputField {
        width: 1fr;
    }
    """


class WorkItemFields(Container, can_focus=False):
    """Details panel container for work item fields."""

    DEFAULT_CSS = """
    WorkItemFields {
        padding: 0;
        margin: 0;
        height: 100%;
        layout: vertical;
    }

    #pending-changes-notification-label {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0 0 0 5;
        color: $warning;
        text-style: bold;
        background: $warning 20%;
        text-align: center;
        dock: bottom;
        visibility: hidden;
    }

    #pending-changes-notification-label.visible {
        visibility: visible;
    }

    /* Vertical layout for narrow screens */
    #work-item-fields-form.narrow Horizontal {
        layout: vertical;
    }

    #work-item-fields-form.narrow Horizontal > Label {
        width: 100%;
        padding-bottom: 0;
        padding-right: 0;
    }

    #work-item-fields-form.narrow Horizontal > * {
        width: 100%;
    }

    /* Dynamic field containers for read-only custom fields */
    .dynamic-field-container {
        width: 100%;
        height: auto;
        align: center middle;
    }

    .dynamic-field-container > Label {
        width: 20%;
        min-width: 15;
        max-width: 30;
        padding-right: 2;
        text-style: bold;
    }

    .dynamic-field-container > ReadOnlyInputField {
        width: 1fr;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)
    clear_form: Reactive[bool] = reactive(False, always_update=True)
    is_loading: Reactive[bool] = reactive(False, always_update=True)
    has_pending_changes: Reactive[bool] = reactive(False, always_update=True)
    _loading_form: bool = False

    BINDINGS = [
        ('ctrl+s', 'save_work_item', 'Save'),
    ]

    def __init__(self):
        super().__init__(id='work-item-fields-container')
        self.available_users: list[tuple[str, str]] | None = None
        self.can_focus = False
        self._current_loading_worker = None

    @property
    def help_anchor(self) -> str:
        return '#updating-work-items'

    @property
    def content_container(self) -> VerticalScroll:
        return self.query_one('#work-item-fields-form', expect_type=VerticalScroll)

    @property
    def work_item_status_selector(self) -> WorkItemStatusSelectionInput:
        return self.query_one(WorkItemStatusSelectionInput)

    @property
    def assignee_selector(self) -> UserSelectionInput:
        return self.query_one(UserSelectionInput)

    @property
    def priority_selector(self) -> SelectionWidget:
        return self.query_one('#priority', SelectionWidget)

    @property
    def reporter_field(self) -> ReadOnlyInputField:
        return self.query_one('#reporter', ReadOnlyInputField)

    @property
    def work_item_sprint_field(self) -> ReadOnlyInputField:
        return self.query_one('#sprint', ReadOnlyInputField)

    @property
    def sprint_field_container(self) -> Horizontal:
        return self.query_one('#sprint-field-container', expect_type=Horizontal)

    @property
    def work_item_resolution_field(self) -> ReadOnlyInputField:
        return self.query_one('#resolution', ReadOnlyInputField)

    @property
    def work_item_time_tracking(self) -> ProgressBar:
        return self.query_one(ProgressBar)

    @property
    def work_item_created_date_field(self) -> ReadOnlyInputField:
        return self.query_one('#created', ReadOnlyInputField)

    @property
    def work_item_last_update_date_field(self) -> ReadOnlyInputField:
        return self.query_one('#updated', ReadOnlyInputField)

    @property
    def work_item_due_date_field(self) -> DateInput:
        return self.query_one('#due-date', DateInput)

    @property
    def time_tracking_widget(self) -> TimeTrackingWidget:
        return self.query_one(TimeTrackingWidget)

    @property
    def work_item_labels_widget(self) -> WorkItemLabels:
        return self.query_one(WorkItemLabels)

    @property
    def labels_field_container(self) -> Horizontal:
        return self.query_one('#labels-field-container', expect_type=Horizontal)

    @property
    def work_item_components_widget(self) -> MultiSelect:
        return self.query_one('#components', MultiSelect)

    @property
    def components_field_container(self) -> Horizontal:
        return self.query_one('#components-field-container', expect_type=Horizontal)

    @property
    def work_item_affects_version_widget(self) -> MultiSelect:
        return self.query_one('#versions', MultiSelect)

    @property
    def affects_version_field_container(self) -> Horizontal:
        return self.query_one('#affects-version-field-container', expect_type=Horizontal)

    @property
    def work_item_fix_version_widget(self) -> MultiSelect:
        return self.query_one('#fixVersions', MultiSelect)

    @property
    def fix_version_field_container(self) -> Horizontal:
        return self.query_one('#fix-version-field-container', expect_type=Horizontal)

    @property
    def work_item_story_points_widget(self) -> NumericInput:
        return self.query_one('#story-points', NumericInput)

    @property
    def story_points_field_container(self) -> Horizontal:
        return self.query_one('#story-points-field-container', expect_type=Horizontal)

    @property
    def work_item_resolution_date_field(self) -> ReadOnlyInputField:
        return self.query_one('#resolution-date', ReadOnlyInputField)

    @property
    def resolution_field_container(self) -> Horizontal:
        return self.query_one('#resolution-field-container', expect_type=Horizontal)

    @property
    def resolution_date_container(self) -> Horizontal:
        return self.query_one('#resolution-date-container', expect_type=Horizontal)

    @property
    def pending_changes_notification_label(self) -> Label:
        try:
            return self.query_one('#pending-changes-notification-label', expect_type=Label)
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')
        raise ValueError('Notification label not found')

    @property
    def time_tracking_container(self) -> Vertical:
        return self.query_one('#time-tracking-container', expect_type=Vertical)

    @property
    def date_metadata_widgets_container(self) -> DateMetadata:
        return self.query_one(DateMetadata)

    @property
    def dynamic_fields_widgets_container(self) -> DynamicFieldsWidgets:
        return self.query_one(DynamicFieldsWidgets)

    def compose(self) -> ComposeResult:
        yield Vertical(id='time-tracking-container')
        with VerticalScroll(id='work-item-fields-form') as fields_form:
            fields_form.can_focus = False

            with Horizontal(id='sprint-field-container'):
                yield Label('Sprint').add_class('field_label')
                yield ReadOnlyInputField(id='sprint')

            with StaticFieldsWidgets():
                with Horizontal(id='status-field-container'):
                    yield Label('Status').add_class('field_label')
                    yield WorkItemStatusSelectionInput([])
                with Horizontal(id='resolution-field-container') as resolution_container:
                    resolution_container.display = False
                    yield Label('Resolution').add_class('field_label')
                    yield ReadOnlyInputField(id='resolution')
                with Horizontal(id='priority-field-container'):
                    yield Label('Priority').add_class('field_label')
                    yield SelectionWidget(
                        mode=FieldMode.UPDATE,
                        field_id='priority',
                        options=[],
                    )
                with Horizontal(id='assignee-field-container'):
                    yield Label('Assignee').add_class('field_label')
                    yield UserSelectionInput(users=[])
                with Horizontal():
                    yield Label('Reporter').add_class('field_label')
                    yield ReadOnlyInputField(id='reporter')
                with Horizontal(id='labels-field-container'):
                    yield Label('Labels').add_class('field_label')
                    yield WorkItemLabels(
                        mode=FieldMode.UPDATE,
                        field_id='labels',
                        title='Labels',
                    )
                with Horizontal(id='components-field-container'):
                    yield Label('Components').add_class('field_label')
                    yield MultiSelect(
                        mode=FieldMode.UPDATE,
                        field_id='components',
                        options=[],
                        title='Components',
                        required=False,
                    )
                with Horizontal(id='affects-version-field-container'):
                    yield Label('Affects Versions').add_class('field_label')
                    yield MultiSelect(
                        mode=FieldMode.UPDATE,
                        field_id='versions',
                        options=[],
                        title='Affects Versions',
                        required=False,
                    )
                with Horizontal(id='fix-version-field-container'):
                    yield Label('Fix Versions').add_class('field_label')
                    yield MultiSelect(
                        mode=FieldMode.UPDATE,
                        field_id='fixVersions',
                        options=[],
                        title='Fix Versions',
                        required=False,
                    )
                with Horizontal(id='story-points-field-container'):
                    yield Label('Story Points').add_class('field_label')
                    yield NumericInput(
                        mode=FieldMode.UPDATE,
                        field_id='story-points',
                        title='Story Points',
                    )

            yield DynamicFieldsWidgets()

            with DateMetadata():
                with Horizontal():
                    yield Label('Due Date').add_class('field_label')
                    yield DateInput(
                        mode=FieldMode.UPDATE,
                        field_id='due-date',
                        title='Due Date',
                    )
                with Horizontal():
                    yield Label('Updated').add_class('field_label')
                    yield ReadOnlyInputField(id='updated')
                with Horizontal():
                    yield Label('Created').add_class('field_label')
                    yield ReadOnlyInputField(id='created')
                with Horizontal(id='resolution-date-container') as resolution_date_container:
                    resolution_date_container.display = False
                    yield Label('Resolution Date').add_class('field_label')
                    yield ReadOnlyInputField(id='resolution-date')

        yield Label('⚠ Pending changes', id='pending-changes-notification-label')

    def _setup_jump_mode(self) -> None:
        content = self.content_container

        for input_widget in content.query(Input):
            if input_widget.can_focus and not input_widget.disabled:
                setattr(input_widget, 'jump_mode', 'focus')  # noqa: B010

        for select_widget in content.query(Select):
            if select_widget.can_focus and not select_widget.disabled:
                setattr(select_widget, 'jump_mode', 'focus')  # noqa: B010

        for tags_widget in content.query(Tags):
            if tags_widget.can_focus and not tags_widget.disabled:
                setattr(tags_widget, 'jump_mode', 'focus')  # noqa: B010

    def _update_layout_mode(self) -> None:
        try:
            screen_width = (
                self.app.console.width if hasattr(self.app, 'console') else self.app.size.width
            )
        except Exception:
            screen_width = self.size.width

        NARROW_SCREEN_THRESHOLD = 150

        try:
            form = self.content_container
            if screen_width < NARROW_SCREEN_THRESHOLD:
                form.add_class('narrow')
            else:
                form.remove_class('narrow')
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def on_resize(self) -> None:
        self._update_layout_mode()

    async def on_mount(self) -> None:
        self.content_container.display = False
        self.call_after_refresh(self._setup_jump_mode)
        self._update_layout_mode()

    def _update_pending_changes_indicator(self) -> None:
        if not self._loading_form and self.work_item:
            try:
                has_changes = self._check_for_pending_changes()
                self.has_pending_changes = has_changes

                self._update_all_field_labels_styling()
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    def _update_all_field_labels_styling(self) -> None:
        for wrapper in self.dynamic_fields_widgets_container.query(DynamicFieldWrapper):
            wrapper.update_label_styling()

        static_fields_map = {
            'status-field-container': lambda: self.work_item_status_selector,
            'priority-field-container': lambda: self.priority_selector,
            'assignee-field-container': lambda: self.assignee_selector,
            'labels-field-container': lambda: self.work_item_labels_widget,
            'components-field-container': lambda: self.work_item_components_widget,
            'affects-version-field-container': lambda: self.work_item_affects_version_widget,
            'fix-version-field-container': lambda: self.work_item_fix_version_widget,
            'story-points-field-container': lambda: self.work_item_story_points_widget,
        }

        for container_id, widget_getter in static_fields_map.items():
            try:
                container = self.query_one(f'#{container_id}')
                widget = widget_getter()

                if not widget:
                    continue

                label = container.query_one(Label)
                widget_enabled = getattr(widget, 'update_enabled', True)

                if container_id == 'status-field-container':
                    has_changed = (
                        hasattr(widget, 'value')
                        and widget.value != Select.BLANK
                        and hasattr(widget, 'selection')
                        and widget.selection is not None
                    )
                elif hasattr(widget, 'value_has_changed'):
                    has_changed = widget.value_has_changed
                elif hasattr(widget, 'original_value') and hasattr(widget, 'selection'):
                    has_changed = widget.original_value != widget.selection
                else:
                    has_changed = False

                if widget_enabled and has_changed:
                    label.add_class('pending_field_label')
                else:
                    label.remove_class('pending_field_label')
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')
                continue

    async def on_input_changed(self, event: Input.Changed) -> None:
        self._update_pending_changes_indicator()

    async def on_select_changed(self, event: Select.Changed) -> None:
        self._update_pending_changes_indicator()

    async def on_tag_auto_complete_applied(self, event: TagAutoComplete.Applied) -> None:
        self._update_pending_changes_indicator()

    async def on_tag_removed(self, event: Tag.Removed) -> None:
        self._update_pending_changes_indicator()

    def watch_has_pending_changes(self, has_changes: bool) -> None:
        self._update_notification_label_visibility(has_changes)

    def _update_notification_label_visibility(self, has_changes: bool) -> None:
        try:
            notification_label = self.pending_changes_notification_label
        except Exception:
            return

        if has_changes:
            notification_label.add_class('visible')
        else:
            notification_label.remove_class('visible')

    def action_view_worklog(self) -> None:
        if self.work_item:
            current_remaining_estimate = None
            if self.work_item.time_tracking:
                current_remaining_estimate = self.work_item.time_tracking.remaining_estimate
            self.app.push_screen(
                WorkItemWorkLogScreen(self.work_item.key, current_remaining_estimate),
                self._handle_worklog_screen_dismissal,
            )

    def action_log_work(self) -> None:
        if self.work_item:
            current_remaining_estimate = None
            if self.work_item.time_tracking:
                current_remaining_estimate = self.work_item.time_tracking.remaining_estimate
            self.app.push_screen(
                LogWorkScreen(
                    work_item_key=self.work_item.key,
                    mode='new',
                    current_remaining_estimate=current_remaining_estimate,
                ),
                self._request_adding_worklog,
            )

    def _handle_worklog_screen_dismissal(self, response: dict | None = None) -> None:
        if response and (response.get('work_logs_deleted') or response.get('work_logs_updated')):
            self.run_worker(self._refresh_work_item_fields())

    async def _update_work_item_field_values(self, updated_work_item: JiraWorkItem) -> None:
        if self.work_item:
            self.work_item.__dict__.update(updated_work_item.__dict__)

            with self.app.batch_update():
                if updated_work_item.assignee:
                    self.assignee_selector.original_value = updated_work_item.assignee.account_id
                    self.assignee_selector.value = updated_work_item.assignee.account_id
                else:
                    self.assignee_selector.original_value = None
                    self.assignee_selector.value = Select.BLANK

                if updated_work_item.priority:
                    self.priority_selector._original_value = updated_work_item.priority.id
                    self.priority_selector.value = updated_work_item.priority.id

                if updated_work_item.status:
                    self.work_item_status_selector.prompt = updated_work_item.status.name
                    self.work_item_status_selector.original_value = updated_work_item.status.id

                    self.work_item_status_selector.value = Select.BLANK

                self._setup_time_tracking(updated_work_item.time_tracking)

                if updated_work_item.updated:
                    self.work_item_last_update_date_field.value = datetime.strftime(
                        updated_work_item.updated, '%Y-%m-%d %H:%M'
                    )

                if updated_work_item.due_date:
                    self.work_item_due_date_field.set_original_value(
                        updated_work_item.display_due_date
                    )

                if hasattr(updated_work_item, 'labels') and updated_work_item.labels is not None:
                    await self.work_item_labels_widget.set_labels(updated_work_item.labels)

            self._update_pending_changes_indicator()

    async def _refresh_work_item_fields(self) -> None:
        if not self.work_item or not self.work_item.key:
            return

        work_item_key = self.work_item.key

        self.work_item = None

        application = cast('JiraApp', self.app)  # noqa: F821
        work_item_fields_response = await application.api.get_work_item(
            work_item_id_or_key=work_item_key
        )
        if work_item_fields_response.success and work_item_fields_response.result:
            updated_work_item = work_item_fields_response.result.work_items[0]
            self.work_item = updated_work_item

            if updated_work_item:
                self.post_message(WorkItemUpdated(updated_work_item))

    def _request_adding_worklog(self, data: dict | None) -> None:
        if not data:
            return

        time_spent = data.get('time_spent')
        started = data.get('started')

        if not time_spent or not started:
            self.notify(
                'Missing required fields for logging work', severity='error', title='Worklog'
            )
            return

        self.run_worker(
            self._add_worklog(
                time_spent=time_spent,
                time_remaining=data.get('time_remaining'),
                description=data.get('description'),
                started=started,
                current_remaining_estimate=data.get('current_remaining_estimate'),
            )
        )

    async def _add_worklog(
        self,
        time_spent: str,
        started: str,
        time_remaining: str | None = None,
        description: str | None = None,
        current_remaining_estimate: str | None = None,
    ) -> None:
        work_item_key = self.work_item.key if self.work_item else None
        if not work_item_key:
            return

        if not time_spent:
            self.notify(
                'You need to provide the time spent on the task to log work', title=work_item_key
            )
        elif not self.work_item or not self.work_item.key:
            return
        else:
            if not started:
                self.notify(
                    'Start date/time is required for logging work',
                    severity='error',
                    title=work_item_key,
                )
                return

            try:
                parsed_started = parser.parse(f'{started}Z')
            except (ValueError, parser.ParserError) as e:
                self.notify(
                    f'Invalid start date/time format: {e}', severity='error', title=work_item_key
                )
                return

            application = cast('JiraApp', self.app)  # noqa: F821
            response: APIControllerResponse = await application.api.add_work_item_worklog(
                work_item_key_or_id=self.work_item.key,
                started=parsed_started,
                time_spent=time_spent,
                time_remaining=time_remaining,
                comment=description,
                current_remaining_estimate=current_remaining_estimate,
            )
            if response.success:
                self.notify('Work logged successfully', title=work_item_key)

                await self._refresh_work_item_fields()
            else:
                self.notify(
                    f'Failed to log work for the item: {response.error}',
                    severity='error',
                    title=work_item_key,
                )
            return

    def _update_priority_selection(self, priorities, priority_id: str) -> None:
        for priority in priorities or []:
            if priority[1] == priority_id:
                self.priority_selector._original_value = priority_id
                self.priority_selector.value = priority_id
                return

    def _setup_priority_selector(
        self, work_item_edit_meta: dict | None, work_item_priority: WorkItemPriority
    ) -> None:
        if work_item_edit_meta:
            if not (priority_field := work_item_edit_meta.get('fields', {}).get('priority')):
                self.priority_selector.update_enabled = False
            else:
                priorities: list[tuple[str, str]] = []
                for v in priority_field.get('allowedValues', []):
                    priorities.append((v.get('name'), v.get('id')))
                self.priority_selector.set_options(priorities)
                if work_item_priority:
                    self._update_priority_selection(priorities, work_item_priority.id)
        else:
            self.priority_selector.update_enabled = False

    async def watch_clear_form(self, clear: bool = False) -> None:
        if clear:
            self.work_item_resolution_field.value = ''
            self.resolution_field_container.display = False
            self.work_item_resolution_date_field.value = ''
            self.resolution_date_container.display = False
            self.work_item_last_update_date_field.value = ''
            self.reporter_field.value = ''
            self.work_item_sprint_field.value = ''
            self.sprint_field_container.display = False
            self.work_item_status_selector.value = Select.BLANK
            self.work_item_status_selector.prompt = 'Select a status'
            self.work_item_status_selector.disabled = False
            self.assignee_selector.value = Select.BLANK
            self.assignee_selector.original_value = None
            self.priority_selector.value = Select.BLANK
            self.priority_selector.update_enabled = True
            self.work_item_due_date_field.set_original_value(None)
            await self.work_item_labels_widget.set_labels([])
            self.work_item_labels_widget.update_enabled = False
            self.labels_field_container.display = False

            self.work_item_components_widget.update_enabled = False
            self.components_field_container.display = False
            self.work_item_affects_version_widget.update_enabled = False
            self.affects_version_field_container.display = False
            self.work_item_fix_version_widget.update_enabled = False
            self.fix_version_field_container.display = False

            self.work_item_story_points_widget.value = ''
            self.work_item_story_points_widget._original_value = None
            self.work_item_story_points_widget.update_enabled = False
            self.story_points_field_container.display = False

    def watch_is_loading(self, loading: bool) -> None:
        with self.app.batch_update():
            self.content_container.display = not loading

    def _setup_time_tracking(self, time_tracking_data: TimeTracking | None) -> None:
        self.time_tracking_container.display = True

        try:
            widget = self.time_tracking_container.query_one(TimeTrackingWidget)

            if not time_tracking_data:
                widget.update_time_tracking(
                    original_estimate=None,
                    time_spent=None,
                    remaining_estimate=None,
                    original_estimate_seconds=None,
                    time_spent_seconds=None,
                    remaining_estimate_seconds=None,
                )
            else:
                widget.update_time_tracking(
                    time_tracking_data.original_estimate,
                    time_tracking_data.time_spent,
                    time_tracking_data.remaining_estimate,
                    time_tracking_data.original_estimate_seconds,
                    time_tracking_data.time_spent_seconds,
                    time_tracking_data.remaining_estimate_seconds,
                )
            return
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        self.time_tracking_container.remove_children()

        if not time_tracking_data:
            time_tracking_widget = TimeTrackingWidget(
                original_estimate=None,
                time_spent=None,
                remaining_estimate=None,
                original_estimate_seconds=None,
                time_spent_seconds=None,
                remaining_estimate_seconds=None,
            )
        else:
            time_tracking_widget = TimeTrackingWidget(
                time_tracking_data.original_estimate,
                time_tracking_data.time_spent,
                time_tracking_data.remaining_estimate,
                time_tracking_data.original_estimate_seconds,
                time_tracking_data.time_spent_seconds,
                time_tracking_data.remaining_estimate_seconds,
            )

        self.time_tracking_container.mount(time_tracking_widget)

    def _build_payload_for_update(self) -> dict:
        payload: dict[str, Any] = {}

        if not self.work_item:
            return payload

        if self.work_item_due_date_field.update_enabled:
            if self.work_item_due_date_field.value_has_changed:
                payload[self.work_item_due_date_field.jira_field_key] = (
                    self.work_item_due_date_field.get_value_for_update()
                )

        if self.priority_selector.update_enabled and self.work_item.priority:
            if work_item_priority_has_changed(
                self.work_item.priority, self.priority_selector.selection
            ):
                if self.priority_selector.selection is not None:
                    payload[self.priority_selector.jira_field_key] = (
                        self.priority_selector.selection
                    )

        if self.assignee_selector.update_enabled:
            if work_item_assignee_has_changed(
                self.work_item.assignee, self.assignee_selector.selection
            ):
                payload['assignee_account_id'] = self.assignee_selector.selection

        if self.work_item_labels_widget.update_enabled:
            if self.work_item_labels_widget.value_has_changed:
                labels = self.work_item_labels_widget.get_value_for_update()
                payload[self.work_item_labels_widget.jira_field_key] = labels

        if self.work_item_components_widget.update_enabled:
            if self.work_item_components_widget.value_has_changed:
                components = self.work_item_components_widget.get_value_for_update()
                payload[self.work_item_components_widget.jira_field_key] = components

        if self.work_item_affects_version_widget.update_enabled:
            if self.work_item_affects_version_widget.value_has_changed:
                versions = self.work_item_affects_version_widget.get_value_for_update()
                payload[self.work_item_affects_version_widget.jira_field_key] = versions

        if self.work_item_fix_version_widget.update_enabled:
            if self.work_item_fix_version_widget.value_has_changed:
                fix_versions = self.work_item_fix_version_widget.get_value_for_update()
                payload[self.work_item_fix_version_widget.jira_field_key] = fix_versions

        if self.work_item_story_points_widget.update_enabled:
            if self.work_item_story_points_widget.value_has_changed:
                story_points = self.work_item_story_points_widget.get_value_for_update()

                payload[self.work_item_story_points_widget.jira_field_key] = story_points

        if CONFIGURATION.get().enable_updating_additional_fields:
            for wrapper in self.dynamic_fields_widgets_container.children:
                if isinstance(wrapper, DynamicFieldWrapper):
                    dynamic_widget = wrapper.widget
                    if not dynamic_widget:
                        continue
                else:
                    dynamic_widget = wrapper

                if (
                    not isinstance(dynamic_widget, NumericInput)
                    and not isinstance(dynamic_widget, DateInput)
                    and not isinstance(dynamic_widget, DateTimeInput)
                    and not isinstance(dynamic_widget, SelectionWidget)
                    and not isinstance(dynamic_widget, URL)
                    and not isinstance(dynamic_widget, MultiSelect)
                    and not isinstance(dynamic_widget, TextInput)
                    and not isinstance(dynamic_widget, WorkItemLabels)
                    and not isinstance(dynamic_widget, UserPicker)
                ):
                    continue

                if isinstance(wrapper, DynamicFieldWrapper):
                    if not wrapper.value_has_changed:
                        continue
                    value_for_update = wrapper.get_value_for_update()
                    field_key = wrapper.jira_field_key
                else:
                    if not dynamic_widget.value_has_changed:
                        continue
                    value_for_update = dynamic_widget.get_value_for_update()
                    field_key = dynamic_widget.jira_field_key

                payload[field_key] = value_for_update
        return payload

    def _check_for_pending_changes(self) -> bool:
        if not self.work_item:
            return False

        payload = self._build_payload_for_update()
        has_field_changes = bool(payload)

        has_status_change = (
            self.work_item_status_selector.value != Select.BLANK
            and self.work_item_status_selector.selection is not None
        )

        return has_field_changes or has_status_change

    async def action_save_work_item(self) -> None:
        if not self.work_item:
            return

        work_item_key = self.work_item.key if self.work_item else None
        if not work_item_key:
            return

        if (
            self.priority_selector.update_enabled
            and self.work_item.priority
            and work_item_priority_has_changed(
                self.work_item.priority, self.priority_selector.selection
            )
            and self.priority_selector.selection is None
        ):
            self.notify(
                'Unsetting the priority of this work item is not possible',
                severity='warning',
                title=work_item_key,
            )
            return

        work_item_was_updated: bool = False

        payload: dict = self._build_payload_for_update()

        work_item_requires_transition = (
            self.work_item_status_selector.selection is not None
            and self.work_item_status_selector.selection != self.work_item.status.id
        )

        if not payload and not work_item_requires_transition:
            self.notify('Nothing to update.', title=work_item_key)
            return

        application = cast('JiraApp', self.app)  # noqa: F821
        if payload:
            try:
                response: APIControllerResponse = await application.api.update_work_item(
                    self.work_item, payload
                )
            except UpdateWorkItemException as e:
                self.notify(
                    f'An error occurred while trying to update the item: {e}',
                    severity='error',
                    title=work_item_key,
                )
            except ValidationError as e:
                self.notify(
                    f'Data validation error: {e}',
                    severity='error',
                    title=work_item_key,
                )
            except Exception as e:
                self.notify(
                    f'An unknown error occurred while trying to update the item: {e}',
                    severity='error',
                    title=work_item_key,
                )
            else:
                if response.success:
                    self.notify('Work item updated successfully.', title=work_item_key)
                    work_item_was_updated = True
                else:
                    error_msg = response.error if response.error else 'Unknown error'
                    self.notify(
                        'The work item was not updated.',
                        severity='error',
                        title=work_item_key,
                    )
                    self.notify(
                        error_msg,
                        severity='error',
                        title=work_item_key,
                    )

        if work_item_requires_transition:
            status_id = self.work_item_status_selector.selection
            if status_id is None:
                self.notify(
                    'Invalid status selection',
                    severity='error',
                    title=work_item_key,
                )
                return

            response = await application.api.transition_work_item_status(
                self.work_item.key, str(status_id)
            )
            if not response.success:
                self.notify(
                    f'Failed to transition the work item to a different status: {response.error}',
                    severity='error',
                    title=work_item_key,
                )
            else:
                work_item_was_updated = True
                self.notify(
                    'Successfully transitioned the work item to a different status.',
                    title=work_item_key,
                )

        if work_item_was_updated:
            self.has_pending_changes = False

            if not self.work_item or not self.work_item.key:
                return

            work_item_key = self.work_item.key
            application = cast('JiraApp', self.app)  # noqa: F821
            work_item_fields_response = await application.api.get_work_item(
                work_item_id_or_key=work_item_key
            )
            if work_item_fields_response.success and work_item_fields_response.result:
                updated_work_item = work_item_fields_response.result.work_items[0]

                await self._update_work_item_field_values(updated_work_item)

                self.post_message(WorkItemUpdated(updated_work_item))

    @staticmethod
    def _determine_editable_fields(work_item: JiraWorkItem) -> dict:
        work_item_edit_metadata: dict | None = work_item.edit_meta
        if not work_item_edit_metadata:
            return {}

        if not (fields := work_item_edit_metadata.get('fields', {})):
            return {}

        editable_fields: dict[str, bool] = {}

        if field_summary := fields.get('summary', {}):
            editable_fields[field_summary.get('key')] = 'set' in field_summary.get('operations', {})

        if field_due_date := fields.get('duedate', {}):
            editable_fields[field_due_date.get('key')] = 'set' in field_due_date.get(
                'operations', {}
            )

        if field_priority := fields.get('priority', {}):
            editable_fields[field_priority.get('key')] = 'set' in field_priority.get(
                'operations', {}
            )

        if field_parent := fields.get('parent', {}):
            if work_item.work_item_type and work_item.work_item_type.hierarchy_level == 1:
                editable_fields[field_parent.get('key')] = False
            else:
                editable_fields[field_parent.get('key')] = 'set' in field_parent.get(
                    'operations', {}
                )

        if field_assignee := fields.get('assignee', {}):
            editable_fields[field_assignee.get('key')] = 'set' in field_assignee.get(
                'operations', {}
            )

        if field_labels := fields.get('labels', {}):
            editable_fields[field_labels.get('key')] = 'set' in field_labels.get('operations', {})

        if field_components := fields.get('components', {}):
            has_set_operation = 'set' in field_components.get('operations', {})
            editable_fields[field_components.get('key')] = has_set_operation

        if field_versions := fields.get('versions', {}):
            editable_fields[field_versions.get('key')] = 'set' in field_versions.get(
                'operations', {}
            )

        if field_fix_versions := fields.get('fixVersions', {}):
            editable_fields[field_fix_versions.get('key')] = 'set' in field_fix_versions.get(
                'operations', {}
            )

        for field_id, field_meta in fields.items():
            if field_id.startswith('customfield_') and field_id not in editable_fields:
                editable_fields[field_id] = 'set' in field_meta.get('operations', {})

        return editable_fields

    @staticmethod
    def _generate_assignable_users_for_dropdown(
        users: list[JiraUser] | None = None,
        current_assignee: JiraUser | None = None,
        default_assignable_users: list[tuple[str, str]] | None = None,
    ) -> list[tuple[str, str]]:
        assignable_users: set[str] = set()
        selectable_users: list[tuple[str, str]] = []
        for user in users or []:
            if user.account_id:
                selectable_users.append((user.display_name, user.account_id))
                assignable_users.add(user.account_id)

        if not selectable_users and default_assignable_users:
            selectable_users = default_assignable_users
            for selectable_user in selectable_users:
                assignable_users.add(selectable_user[1])

        if current_assignee and current_assignee.account_id not in assignable_users:
            selectable_users.append((current_assignee.display_name, current_assignee.account_id))

        return selectable_users

    async def _retrieve_users_assignable_to_work_item(
        self,
        work_item_key: str,
        current_assignee: JiraUser | None = None,
        field_is_editable: bool | None = None,
    ) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821

        response: APIControllerResponse = (
            await application.api.search_users_assignable_to_work_item(work_item_key=work_item_key)
        )

        selectable_users: list[tuple[str, str]] = self._generate_assignable_users_for_dropdown(
            response.result,
            current_assignee,
            self.available_users,
        )

        if selectable_users:
            self.assignee_selector.set_options(selectable_users)
            if current_assignee:
                self.assignee_selector.original_value = current_assignee.account_id

                self.assignee_selector.value = current_assignee.account_id
            else:
                self.assignee_selector.original_value = None
            self.assignee_selector.update_enabled = bool(field_is_editable)
        else:
            if current_assignee:
                self.assignee_selector.set_options(
                    [(current_assignee.display_name, current_assignee.account_id)]
                )

                self.assignee_selector.original_value = current_assignee.account_id
                self.assignee_selector.value = current_assignee.account_id
                self.assignee_selector.update_enabled = bool(field_is_editable)
            else:
                self.assignee_selector.original_value = None
                self.assignee_selector.update_enabled = False

    async def _retrieve_applicable_status_codes(
        self,
        work_item_key: str,
        current_status_name: str | None = None,
        current_status_color: str | None = None,
    ) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        response: APIControllerResponse = await application.api.transitions(work_item_key)

        if not response.success or not response.result or not response.result:
            # No transitions available - disable the selector to make it read-only
            self.work_item_status_selector.set_options([])
            self.work_item_status_selector.disabled = True
            if current_status_name:
                self.work_item_status_selector.prompt = current_status_name
        else:
            transitions: list = response.result
            if not transitions:
                # Empty transitions list - disable the selector
                self.work_item_status_selector.set_options([])
                self.work_item_status_selector.disabled = True
                if current_status_name:
                    self.work_item_status_selector.prompt = current_status_name
            else:
                # Has transitions - enable and populate the dropdown selector
                allowed_status_options = []
                for transition in transitions:
                    if transition.to_state:
                        bg_color = map_jira_status_color_to_textual(
                            transition.to_state.status_category_color, for_background=True
                        )
                        text_color_type = bg_color.replace('-muted', '')

                        colored_status = f'[$text-{text_color_type} bold on ${bg_color}] {transition.to_state.name} [/]'
                        display_name = f'{transition.name} → {colored_status}'
                        allowed_status_options.append((display_name, str(transition.to_state.id)))

                allowed_status_options = sorted(allowed_status_options, key=lambda x: str(x[0]))
                self.work_item_status_selector.set_options(allowed_status_options)
                self.work_item_status_selector.disabled = False

                if current_status_name:
                    self.work_item_status_selector.prompt = current_status_name

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        if self._current_loading_worker is not None:
            self._current_loading_worker.cancel()
            self._current_loading_worker = None

        if not work_item:
            self.content_container.display = False

            self.clear_form = True

            self.has_pending_changes = False
            return

        self.is_loading = True

        self._current_loading_worker = self.run_worker(
            self._populate_work_item_fields(work_item), exclusive=True
        )

    async def _populate_work_item_fields(self, work_item: JiraWorkItem) -> None:
        work_item_key = work_item.key

        self._loading_form = True

        await self.watch_clear_form(True)

        editable_fields: dict = self._determine_editable_fields(work_item)

        if work_item.key:
            await asyncio.gather(
                self._retrieve_applicable_status_codes(
                    work_item.key,
                    work_item.status.name if work_item.status else None,
                    work_item.status.status_category_color if work_item.status else None,
                ),
                self._retrieve_users_assignable_to_work_item(
                    work_item.key,
                    work_item.assignee,
                    editable_fields.get(self.assignee_selector.jira_field_key),
                ),
            )

            if not self.work_item or self.work_item.key != work_item_key:
                return

            if work_item.status:
                self.work_item_status_selector.original_value = work_item.status.id
            else:
                self.work_item_status_selector.original_value = None

        with self.app.batch_update():
            if work_item.resolution_date:
                self.work_item_resolution_date_field.value = datetime.strftime(
                    work_item.resolution_date, '%Y-%m-%d %H:%M'
                )
                self.resolution_date_container.display = True
            else:
                self.work_item_resolution_date_field.value = ''
                self.resolution_date_container.display = False

            if work_item.resolution:
                self.work_item_resolution_field.value = work_item.resolution
                self.resolution_field_container.display = True
            else:
                self.work_item_resolution_field.value = ''
                self.resolution_field_container.display = False
            if work_item.updated:
                self.work_item_last_update_date_field.value = datetime.strftime(
                    work_item.updated, '%Y-%m-%d %H:%M'
                )
            if reporter := work_item.reporter:
                self.reporter_field.value = reporter.display_name
            if work_item.created:
                self.work_item_created_date_field.value = datetime.strftime(
                    work_item.created, '%Y-%m-%d %H:%M'
                )
            if work_item.sprint:
                self.work_item_sprint_field.value = work_item.sprint_name
                self.sprint_field_container.display = True
            else:
                self.work_item_sprint_field.value = ''
                self.sprint_field_container.display = False

            self.work_item_due_date_field.set_original_value(work_item.display_due_date)
            self.work_item_due_date_field.update_enabled = editable_fields.get(
                self.work_item_due_date_field.jira_field_key, True
            )

            if work_item.priority:
                self._setup_priority_selector(work_item.edit_meta, work_item.priority)

            self._setup_time_tracking(work_item.time_tracking)

        setup_tasks = [
            self._setup_labels_field(work_item, editable_fields),
            self._setup_components_field(work_item, editable_fields),
            self._setup_affects_version_field(work_item, editable_fields),
            self._setup_fix_version_field(work_item, editable_fields),
            self._setup_story_points_field(work_item, editable_fields),
        ]

        if CONFIGURATION.get().enable_updating_additional_fields:
            setup_tasks.append(self._add_dynamic_fields_widgets(work_item, editable_fields))

        await asyncio.gather(*setup_tasks)

        self.is_loading = False

        try:
            info_container = self.screen.query_one(WorkItemInfoContainer)
            info_container.signal_fields_widget_ready()
        except Exception as e:
            self.app.log.error(f'Failed to signal info container ready: {e}')

        if not self.work_item or self.work_item.key != work_item_key:
            return

        self._current_loading_worker = None

        with self.app.batch_update():
            self.has_pending_changes = False

            self._update_all_field_labels_styling()

        def finalize_form_load() -> None:
            self.has_pending_changes = False

            self._loading_form = False

        self.call_after_refresh(finalize_form_load)

    def _format_custom_field_value(self, field_value: Any) -> str:
        if field_value is None:
            return ''

        # Skip fields with error messages
        if isinstance(field_value, dict) and 'errorMessage' in field_value:
            return ''

        # Handle string values
        if isinstance(field_value, str):
            return field_value

        # Handle numeric values
        if isinstance(field_value, (int, float)):
            return str(field_value)

        # Handle list/array values
        if isinstance(field_value, list):
            if not field_value:
                return ''

            # Try to extract 'value' or 'name' fields from objects in the list
            if isinstance(field_value[0], dict):
                if 'value' in field_value[0]:
                    return ', '.join(
                        item.get('value', '') for item in field_value if item.get('value')
                    )
                elif 'name' in field_value[0]:
                    return ', '.join(
                        item.get('name', '') for item in field_value if item.get('name')
                    )
                elif 'displayName' in field_value[0]:
                    return ', '.join(
                        item.get('displayName', '')
                        for item in field_value
                        if item.get('displayName')
                    )

            # Otherwise, join string representations
            return ', '.join(str(item) for item in field_value)

        # Handle dict/object values
        if isinstance(field_value, dict):
            # Common patterns in Jira custom fields
            if 'value' in field_value:
                return str(field_value['value'])
            elif 'name' in field_value:
                return str(field_value['name'])
            elif 'displayName' in field_value:
                return str(field_value['displayName'])

            # For service desk request type
            if 'requestType' in field_value:
                req_type = field_value['requestType']
                if isinstance(req_type, dict) and 'name' in req_type:
                    return f'Request Type: {req_type["name"]}'

            # Try to create a readable representation
            try:
                # Skip very large or complex objects
                json_str = json.dumps(field_value)
                if len(json_str) < 200:
                    return json_str
            except (TypeError, ValueError):
                pass

            return '[Complex Object]'

        # Fallback to string conversion
        return str(field_value)

    async def _add_dynamic_fields_widgets(
        self, work_item: JiraWorkItem, editable_fields: dict
    ) -> None:
        config = CONFIGURATION.get()

        ignore_filter_ids = config.update_additional_fields_ignore_ids

        await self.dynamic_fields_widgets_container.remove_children()

        skip_fields = set()
        skip_fields.update(field.value for field in WorkItemManualUpdateFieldKeys)
        skip_fields.update(field.value for field in WorkItemUnsupportedUpdateFieldKeys)

        if ignore_filter_ids:
            skip_fields.update(ignore_filter_ids)

        edit_meta_fields = work_item.edit_meta.get('fields', {}) if work_item.edit_meta else {}

        # When editmeta is null, create read-only widgets for custom fields with values
        if not edit_meta_fields and work_item.custom_fields:
            # Fetch field metadata to get field names
            application = cast('JiraApp', self.app)  # noqa: F821
            fields_response = await application.api.get_fields()

            # Build a mapping of field_id -> field_name
            field_names_map = {}
            if fields_response.success and fields_response.result:
                for field in fields_response.result:
                    field_names_map[field.id] = field.name

            containers = []
            for field_id, field_value in work_item.custom_fields.items():
                if field_value is None or field_id in skip_fields:
                    continue

                display_value = self._format_custom_field_value(field_value)
                if not display_value:
                    continue

                # Use field name if available, otherwise fall back to field ID
                field_label = field_names_map.get(field_id, field_id)

                # Create container
                field_container = Horizontal(classes='dynamic-field-container')
                containers.append((field_container, field_label, display_value))

            if containers:
                with self.app.batch_update():
                    # Mount all containers first
                    await self.dynamic_fields_widgets_container.mount(
                        *(container for container, _, _ in containers)
                    )
                    # Then mount children to each container
                    for field_container, field_label, display_value in containers:
                        label = Label(field_label, classes='field_label')
                        readonly_field = ReadOnlyInputField()
                        readonly_field.value = display_value
                        await field_container.mount(label, readonly_field)

                    self.dynamic_fields_widgets_container.display = True
            else:
                self.dynamic_fields_widgets_container.display = False
            return

        # Normal path: editmeta is available, build editable widgets
        fields_data = []
        for field_id, field in edit_meta_fields.items():
            if not field.get('fieldId'):
                field['fieldId'] = field_id
            fields_data.append(field)

        current_values = {}
        for field_id, field in edit_meta_fields.items():
            field_key = field.get('key', '')

            if field_id in work_item.get_custom_fields():
                current_values[field_id] = work_item.get_custom_field_value(field_id)
            elif field_id in work_item.get_additional_fields():
                current_values[field_id] = work_item.get_additional_field_value(field_id)
            elif hasattr(work_item, field_key) and field_key:
                current_values[field_id] = getattr(work_item, field_key)

        dynamic_widgets = build_dynamic_widgets(
            mode=FieldMode.UPDATE,
            fields_data=fields_data,
            current_values=current_values,
            skip_fields=skip_fields,
        )

        if dynamic_widgets:
            adf_textarea_widgets = [
                w
                for w in dynamic_widgets
                if isinstance(w, DynamicFieldWrapper)
                and getattr(w, 'widget_class', None)
                and getattr(getattr(w, 'widget_class', None), '__name__', None)
                == 'ADFTextAreaWidget'
            ]
            other_widgets = [
                w
                for w in dynamic_widgets
                if not (
                    isinstance(w, DynamicFieldWrapper)
                    and getattr(w, 'widget_class', None)
                    and getattr(getattr(w, 'widget_class', None), '__name__', None)
                    == 'ADFTextAreaWidget'
                )
            ]
            sorted_widgets = other_widgets + adf_textarea_widgets

            with self.app.batch_update():
                await self.dynamic_fields_widgets_container.mount(*sorted_widgets)

                self.dynamic_fields_widgets_container.display = True

            await asyncio.sleep(0)
            await self._populate_user_picker_widgets(work_item, editable_fields)

            self._setup_jump_mode()
        else:
            self.dynamic_fields_widgets_container.display = False

    async def _populate_user_picker_widgets(
        self, work_item: JiraWorkItem, editable_fields: dict
    ) -> None:
        application = cast('JiraApp', self.app)  # noqa: F821
        user_picker_widgets = self.query(UserPicker)

        if not user_picker_widgets:
            return

        response: APIControllerResponse = (
            await application.api.search_users_assignable_to_work_item(work_item_key=work_item.key)
        )

        for user_picker in user_picker_widgets:
            max_retries = 10
            for _ in range(max_retries):
                try:
                    user_picker.query_one(SelectOverlay)
                    break
                except Exception:
                    await asyncio.sleep(0.05)
            else:
                continue

            current_user_value = user_picker.pending_value

            selectable_users: list[tuple[str, str]] = self._generate_assignable_users_for_dropdown(
                response.result,
                None,
                self.available_users,
            )

            if selectable_users:
                if current_user_value:
                    user_ids = [user[1] for user in selectable_users]
                    if current_user_value not in user_ids:
                        for user in response.result or []:
                            if user.account_id == current_user_value:
                                selectable_users.append((user.display_name, user.account_id))
                                break
                        else:
                            selectable_users.append((current_user_value, current_user_value))

                user_picker.set_options(selectable_users)
                if current_user_value:
                    user_picker.value = current_user_value
                field_editable = editable_fields.get(user_picker.jira_field_key)
                user_picker.update_enabled = (
                    bool(field_editable) if field_editable is not None else False
                )
            else:
                if current_user_value:
                    user_picker.set_options([(current_user_value, current_user_value)])
                    user_picker.value = current_user_value
                    field_editable = editable_fields.get(user_picker.jira_field_key)
                    user_picker.update_enabled = (
                        bool(field_editable) if field_editable is not None else False
                    )
                else:
                    user_picker.update_enabled = False

    async def _setup_labels_field(self, work_item: JiraWorkItem, editable_fields: dict) -> None:
        if not work_item.edit_meta:
            self.work_item_labels_widget.update_enabled = False
            self.labels_field_container.display = False
            return

        labels_field_meta = work_item.edit_meta.get('fields', {}).get('labels')
        if not labels_field_meta:
            self.work_item_labels_widget.update_enabled = False
            self.labels_field_container.display = False
            return

        current_labels = work_item.labels or []
        field_is_required = labels_field_meta.get('required', False)

        field_can_be_updated = editable_fields.get('labels', False)

        if not current_labels and not field_can_be_updated:
            self.work_item_labels_widget.update_enabled = False
            self.labels_field_container.display = False
            return

        self.work_item_labels_widget.required = field_is_required
        self.labels_field_container.display = True
        self.work_item_labels_widget.update_enabled = field_can_be_updated

        await self.work_item_labels_widget.set_labels(current_labels)

    async def _setup_components_field(self, work_item: JiraWorkItem, editable_fields: dict) -> None:
        if not work_item.edit_meta:
            self.work_item_components_widget.update_enabled = False
            self.components_field_container.display = False
            return

        components_field_meta = work_item.edit_meta.get('fields', {}).get('components')
        if not components_field_meta:
            self.work_item_components_widget.update_enabled = False
            self.components_field_container.display = False
            return

        allowed_values = components_field_meta.get('allowedValues', [])

        if allowed_values:
            options = [(v.get('name', ''), v.get('id', '')) for v in allowed_values]

            current_ids = []
            if work_item.components:
                current_ids = [comp.id for comp in work_item.components]

            field_can_be_updated = editable_fields.get('components', False)

            if not current_ids and not field_can_be_updated:
                self.work_item_components_widget.update_enabled = False
                self.components_field_container.display = False
                return

            self.components_field_container.display = True
            await self.work_item_components_widget.update_options(
                options=options,
                original_value=current_ids,
                field_supports_update=field_can_be_updated,
            )
        else:
            field_can_be_updated = editable_fields.get('components', False)

            current_ids = []
            if work_item.components:
                current_ids = [comp.id for comp in work_item.components]

            if not current_ids and not field_can_be_updated:
                self.work_item_components_widget.update_enabled = False
                self.components_field_container.display = False
                return

            self.components_field_container.display = True
            self.work_item_components_widget.update_enabled = False

            if current_ids:
                await self.work_item_components_widget.update_options(
                    options=[],
                    original_value=current_ids,
                    field_supports_update=False,
                )

    async def _setup_affects_version_field(
        self, work_item: JiraWorkItem, editable_fields: dict
    ) -> None:
        if not work_item.edit_meta:
            self.work_item_affects_version_widget.update_enabled = False
            self.affects_version_field_container.display = False
            return

        versions_field_meta = work_item.edit_meta.get('fields', {}).get('versions')
        if not versions_field_meta:
            self.work_item_affects_version_widget.update_enabled = False
            self.affects_version_field_container.display = False
            return

        allowed_values = versions_field_meta.get('allowedValues', [])

        if allowed_values:
            options = [(v.get('name', ''), v.get('id', '')) for v in allowed_values]

            current_ids = []
            if work_item.additional_fields and 'versions' in work_item.additional_fields:
                versions = work_item.additional_fields.get('versions', [])
                if versions:
                    for version in versions:
                        if isinstance(version, dict) and 'id' in version:
                            current_ids.append(version['id'])
                        elif hasattr(version, 'id'):
                            current_ids.append(version.id)  # pyright: ignore[reportAttributeAccessIssue]

            field_can_be_updated = editable_fields.get('versions', False)

            if not current_ids and not field_can_be_updated:
                self.work_item_affects_version_widget.update_enabled = False
                self.affects_version_field_container.display = False
                return

            self.affects_version_field_container.display = True
            if not self.work_item_affects_version_widget.is_mounted:
                await self.query_one(StaticFieldsWidgets).mount(
                    self.work_item_affects_version_widget
                )

            await self.work_item_affects_version_widget.update_options(
                options=options,
                original_value=current_ids,
                field_supports_update=field_can_be_updated,
            )
        else:
            field_can_be_updated = editable_fields.get('versions', False)

            current_ids = []
            if work_item.additional_fields and 'versions' in work_item.additional_fields:
                versions = work_item.additional_fields.get('versions', [])
                if versions:
                    for version in versions:
                        if isinstance(version, dict) and 'id' in version:
                            current_ids.append(version['id'])
                        elif hasattr(version, 'id'):
                            current_ids.append(version.id)  # pyright: ignore[reportAttributeAccessIssue]

            if not current_ids and not field_can_be_updated:
                self.work_item_affects_version_widget.update_enabled = False
                self.affects_version_field_container.display = False
                return

            self.affects_version_field_container.display = True
            if not self.work_item_affects_version_widget.is_mounted:
                await self.query_one(StaticFieldsWidgets).mount(
                    self.work_item_affects_version_widget
                )
            self.work_item_affects_version_widget.update_enabled = False

            if current_ids:
                await self.work_item_affects_version_widget.update_options(
                    options=[],
                    original_value=current_ids,
                    field_supports_update=False,
                )

    async def _setup_fix_version_field(
        self, work_item: JiraWorkItem, editable_fields: dict
    ) -> None:
        if not work_item.edit_meta:
            self.work_item_fix_version_widget.update_enabled = False
            self.fix_version_field_container.display = False
            return

        fix_versions_field_meta = work_item.edit_meta.get('fields', {}).get('fixVersions')
        if not fix_versions_field_meta:
            self.work_item_fix_version_widget.update_enabled = False
            self.fix_version_field_container.display = False
            return

        allowed_values = fix_versions_field_meta.get('allowedValues', [])

        if allowed_values:
            options = [(v.get('name', ''), v.get('id', '')) for v in allowed_values]

            current_ids = []
            if work_item.additional_fields and 'fixVersions' in work_item.additional_fields:
                fix_versions = work_item.additional_fields.get('fixVersions', [])
                if fix_versions:
                    for version in fix_versions:
                        if isinstance(version, dict) and 'id' in version:
                            current_ids.append(version['id'])
                        elif hasattr(version, 'id'):
                            current_ids.append(version.id)  # pyright: ignore[reportAttributeAccessIssue]

            field_can_be_updated = editable_fields.get('fixVersions', False)

            if not current_ids and not field_can_be_updated:
                self.work_item_fix_version_widget.update_enabled = False
                self.fix_version_field_container.display = False
                return

            self.fix_version_field_container.display = True
            await self.work_item_fix_version_widget.update_options(
                options=options,
                original_value=current_ids,
                field_supports_update=field_can_be_updated,
            )
        else:
            field_can_be_updated = editable_fields.get('fixVersions', False)

            current_ids = []
            if work_item.additional_fields and 'fixVersions' in work_item.additional_fields:
                fix_versions = work_item.additional_fields.get('fixVersions', [])
                if fix_versions:
                    for version in fix_versions:
                        if isinstance(version, dict) and 'id' in version:
                            current_ids.append(version['id'])
                        elif hasattr(version, 'id'):
                            current_ids.append(version.id)  # pyright: ignore[reportAttributeAccessIssue]

            if not current_ids and not field_can_be_updated:
                self.work_item_fix_version_widget.update_enabled = False
                self.fix_version_field_container.display = False
                return

            self.fix_version_field_container.display = True
            self.work_item_fix_version_widget.update_enabled = False

            if current_ids:
                await self.work_item_fix_version_widget.update_options(
                    options=[],
                    original_value=current_ids,
                    field_supports_update=False,
                )

    async def _setup_story_points_field(
        self, work_item: JiraWorkItem, editable_fields: dict | None
    ) -> None:
        if not editable_fields:
            self.work_item_story_points_widget.update_enabled = False
            self.story_points_field_container.display = False
            return

        story_points_field_id = None
        story_points_value = None

        story_points_field_meta = None

        if not work_item.edit_meta or 'fields' not in work_item.edit_meta:
            self.work_item_story_points_widget.update_enabled = False
            self.story_points_field_container.display = False
            return

        for field_id, field_meta in work_item.edit_meta.get('fields', {}).items():
            field_name = field_meta.get('name', '').lower()
            if 'story points' in field_name or 'storypoints' in field_name:
                story_points_field_id = field_id
                story_points_field_meta = field_meta

                if work_item.custom_fields and field_id in work_item.custom_fields:
                    story_points_value = work_item.custom_fields.get(field_id)
                break

        if story_points_field_id and story_points_field_meta:
            field_can_be_updated = editable_fields.get(story_points_field_id, False)

            if story_points_value is None and not field_can_be_updated:
                self.work_item_story_points_widget.update_enabled = False
                self.story_points_field_container.display = False
                return

            self.story_points_field_container.display = True

            if story_points_value is not None:
                float_value = float(story_points_value)
                str_value = str(float_value)

                self.work_item_story_points_widget._original_value = float_value

                self.work_item_story_points_widget.value = str_value

            else:
                self.work_item_story_points_widget._original_value = None

            self.work_item_story_points_widget.update_enabled = field_can_be_updated

            self.work_item_story_points_widget.jira_field_key = story_points_field_id

        else:
            self.work_item_story_points_widget.update_enabled = False
            self.story_points_field_container.display = False
