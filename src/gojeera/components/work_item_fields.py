import asyncio
from datetime import datetime
import json
import logging
from typing import TYPE_CHECKING, Any, cast

from dateutil import parser
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalGroup, VerticalScroll
from textual.message import Message
from textual.reactive import Reactive, reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select
from textual.widgets._select import SelectOverlay
from textual_tags import Tag, TagAutoComplete

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.work_item_description import WorkItemInfoContainer
from gojeera.components.work_item_work_log_screen import WorkItemWorkLogScreen
from gojeera.components.work_log_screen import LogWorkScreen
from gojeera.config import CONFIGURATION
from gojeera.constants import (
    WorkItemManualUpdateFieldKeys,
    WorkItemUnsupportedUpdateFieldKeys,
)
from gojeera.exceptions import UpdateWorkItemException, ValidationError
from gojeera.models import JiraUser, JiraWorkItem, WorkItemPriority
from gojeera.utils.fields import (
    FieldMode,
    PendingChangesWidget,
    get_parent_relation_field_ids_from_editmeta,
    get_sprint_field_id_from_editmeta,
    is_epic_work_item_type,
    is_parent_relation_field_name,
)
from gojeera.utils.mappings import get_nested
from gojeera.utils.styling import map_jira_status_color_to_textual
from gojeera.utils.widgets_factory_utils import (
    DynamicFieldsWidgets,
    DynamicFieldWrapper,
    StaticFieldsWidgets,
    build_dynamic_widgets,
    build_field_tooltip,
)
from gojeera.utils.work_item_updates import (
    work_item_assignee_has_changed,
    work_item_priority_has_changed,
)
from gojeera.widgets.date_input import DateInput
from gojeera.widgets.date_time_input import DateTimeInput
from gojeera.widgets.extended_jumper import set_jump_mode
from gojeera.widgets.multi_select import MultiSelect
from gojeera.widgets.numeric_input import NumericInput
from gojeera.widgets.read_only_input_field import ReadOnlyInputField
from gojeera.widgets.selection import SelectionWidget
from gojeera.widgets.sprint_picker import SprintPicker
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


class FieldRowSlot(VerticalGroup):
    """Row wrapper that applies spacing above visible rows."""

    def __init__(self, *, include_top_spacer: bool = False, **kwargs: Any) -> None:
        classes = kwargs.pop('classes', '')
        combined_classes = 'field-row-slot'
        if classes:
            combined_classes = f'{combined_classes} {classes}'
        super().__init__(classes=combined_classes, **kwargs)
        self.include_top_spacer = include_top_spacer
        self.set_spacer_visible(include_top_spacer)

    def set_spacer_visible(self, visible: bool) -> None:
        self.include_top_spacer = visible
        self.set_styles(f'margin: {1 if visible else 0} 0 0 0;')


class DateMetadata(VerticalGroup):
    """Container for date/metadata field widgets."""

    DEFAULT_CSS = """
    DateMetadata {
        layout: vertical;
        margin: 0;
        margin-right: 2;
        padding: 0;
        height: auto;
    }

    DateMetadata > * {
        height: auto;
        width: 100%;
    }

    DateMetadata > .field-row-slot > Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
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

    #work-item-fields-form {
        scrollbar-size-vertical: 1;
        height: 1fr;
        padding: 0 0 1 1;
        margin-bottom: 0;
        layout: vertical;
        padding-bottom: 0;
    }

    WorkItemFields.-loading > #work-item-fields-form {
        opacity: 0;
    }

    /* Vertical layout for narrow screens */
    #work-item-fields-form.narrow > StaticFieldsWidgets > .field-row-slot > Horizontal,
    #work-item-fields-form.narrow > DynamicFieldsWidgets > .field-row-slot > Horizontal,
    #work-item-fields-form.narrow > DateMetadata > .field-row-slot > Horizontal {
        layout: vertical;
    }

    #work-item-fields-form.narrow > StaticFieldsWidgets > .field-row-slot > Horizontal > Label,
    #work-item-fields-form.narrow > DynamicFieldsWidgets > .field-row-slot > Horizontal > Label,
    #work-item-fields-form.narrow > DateMetadata > .field-row-slot > Horizontal > Label {
        width: 100%;
        padding-bottom: 0;
        padding-right: 0;
    }

    #work-item-fields-form.narrow > StaticFieldsWidgets > .field-row-slot > Horizontal > *,
    #work-item-fields-form.narrow > DynamicFieldsWidgets > .field-row-slot > Horizontal > *,
    #work-item-fields-form.narrow > DateMetadata > .field-row-slot > Horizontal > * {
        width: 100%;
    }

    #work-item-fields-form.narrow > StaticFieldsWidgets > .field-row-slot > Horizontal > .field_control,
    #work-item-fields-form.narrow > DynamicFieldsWidgets > .field-row-slot > Horizontal > .field_control,
    #work-item-fields-form.narrow > DateMetadata > .field-row-slot > Horizontal > .field_control {
        width: 100%;
        min-width: 0;
        margin-right: 0;
    }

    .dynamic-field-container {
        width: 100%;
        height: auto;
        align: center middle;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)
    clear_form: Reactive[bool] = reactive(False, always_update=True)
    is_loading: Reactive[bool] = reactive(False, always_update=True)
    has_pending_changes: Reactive[bool] = reactive(False, always_update=True)
    _loading_form: bool = False

    def __init__(self):
        super().__init__(id='work-item-fields-container')
        self.available_users: list[tuple[str, str]] | None = None
        self.can_focus = False
        self._current_loading_worker = None
        self._save_in_progress = False
        self._show_time_tracking_after_load = False
        self._field_descriptions_by_id: dict[str, str] = {}
        self._field_descriptions_loading = False
        self._assignee_refresh_worker = None
        self._status_refresh_worker = None

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
    def work_item_resolution_field(self) -> ReadOnlyInputField:
        return self.query_one('#resolution', ReadOnlyInputField)

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
    def work_item_labels_widget(self) -> WorkItemLabels:
        return self.query_one(WorkItemLabels)

    @property
    def labels_field_container(self) -> FieldRowSlot:
        return self.query_one('#labels-field-container', expect_type=FieldRowSlot)

    @property
    def status_field_container(self) -> FieldRowSlot:
        return self.query_one('#status-field-container', expect_type=FieldRowSlot)

    @property
    def priority_field_container(self) -> FieldRowSlot:
        return self.query_one('#priority-field-container', expect_type=FieldRowSlot)

    @property
    def assignee_field_container(self) -> FieldRowSlot:
        return self.query_one('#assignee-field-container', expect_type=FieldRowSlot)

    @property
    def reporter_field_container(self) -> FieldRowSlot:
        return self.query_one('#reporter-field-container', expect_type=FieldRowSlot)

    @property
    def work_item_components_widget(self) -> MultiSelect:
        return self.query_one('#components', MultiSelect)

    @property
    def components_field_container(self) -> FieldRowSlot:
        return self.query_one('#components-field-container', expect_type=FieldRowSlot)

    @property
    def work_item_affects_version_widget(self) -> MultiSelect:
        return self.query_one('#versions', MultiSelect)

    @property
    def affects_version_field_container(self) -> FieldRowSlot:
        return self.query_one('#affects-version-field-container', expect_type=FieldRowSlot)

    @property
    def work_item_fix_version_widget(self) -> MultiSelect:
        return self.query_one('#fixVersions', MultiSelect)

    @property
    def fix_version_field_container(self) -> FieldRowSlot:
        return self.query_one('#fix-version-field-container', expect_type=FieldRowSlot)

    @property
    def work_item_story_points_widget(self) -> NumericInput:
        return self.query_one('#story-points', NumericInput)

    @property
    def story_points_field_container(self) -> FieldRowSlot:
        return self.query_one('#story-points-field-container', expect_type=FieldRowSlot)

    @property
    def sprint_picker_widget(self) -> SprintPicker:
        return self.query_one('#sprint', SprintPicker)

    @property
    def sprint_field_container(self) -> FieldRowSlot:
        return self.query_one('#sprint-field-container', expect_type=FieldRowSlot)

    @property
    def work_item_resolution_date_field(self) -> ReadOnlyInputField:
        return self.query_one('#resolution-date', ReadOnlyInputField)

    @property
    def pending_changes_indicator(self) -> PendingChangesWidget:
        return self.query_one(
            '#work-item-fields-pending-changes-indicator',
            expect_type=PendingChangesWidget,
        )

    @property
    def pending_changes_button(self) -> Button:
        return self.query_one(
            '#work-item-fields-pending-changes-button',
            expect_type=Button,
        )

    @property
    def pending_changes_container(self) -> Horizontal:
        return self.query_one('#work-item-fields-pending-changes-container', expect_type=Horizontal)

    @property
    def resolution_field_container(self) -> FieldRowSlot:
        return self.query_one('#resolution-field-container', expect_type=FieldRowSlot)

    @property
    def resolution_date_container(self) -> FieldRowSlot:
        return self.query_one('#resolution-date-container', expect_type=FieldRowSlot)

    @property
    def due_date_container(self) -> FieldRowSlot:
        return self.query_one('#due-date-container', expect_type=FieldRowSlot)

    @property
    def updated_container(self) -> FieldRowSlot:
        return self.query_one('#updated-container', expect_type=FieldRowSlot)

    @property
    def created_container(self) -> FieldRowSlot:
        return self.query_one('#created-container', expect_type=FieldRowSlot)

    @property
    def time_tracking_container(self) -> Vertical:
        return self.query_one('#time-tracking-container', expect_type=Vertical)

    @property
    def date_metadata_widgets_container(self) -> DateMetadata:
        return self.query_one(DateMetadata)

    @property
    def dynamic_fields_widgets_container(self) -> DynamicFieldsWidgets:
        return self.query_one(DynamicFieldsWidgets)

    @property
    def static_fields_widgets_container(self) -> StaticFieldsWidgets:
        return self.query_one(StaticFieldsWidgets)

    @property
    def time_tracking_widget(self) -> TimeTrackingWidget:
        return self.time_tracking_container.query_one(TimeTrackingWidget)

    @staticmethod
    def _field_label(text: str) -> Label:
        normalized_text = ' '.join(text.split())
        return Label(normalized_text, classes='field_label')

    @staticmethod
    def _apply_field_control_classes(widget: Widget) -> None:
        widget.add_class('field_control')
        widget.styles.width = '1fr'

        if isinstance(widget, (Input, TextInput, NumericInput, URL, DateInput, DateTimeInput)):
            widget.add_class('field-control-input')
        elif isinstance(
            widget,
            (Select, SelectionWidget, SprintPicker, UserPicker, UserSelectionInput),
        ):
            widget.add_class('field-control-select')
        elif isinstance(widget, (MultiSelect, WorkItemLabels)):
            widget.add_class('field-control-tags')

    @staticmethod
    def _field_control(widget: Widget) -> Widget:
        WorkItemFields._apply_field_control_classes(widget)
        return widget

    @staticmethod
    def _apply_field_tooltip(
        container: FieldRowSlot,
        widget: Widget,
        field_metadata: dict[str, Any] | None,
    ) -> None:
        tooltip = build_field_tooltip(field_metadata or {})
        container.tooltip = tooltip
        label = container.query_one(Label)
        label.tooltip = tooltip
        widget.tooltip = tooltip

    @staticmethod
    def _field_metadata_with_id(
        field_id: str,
        field_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = dict(field_metadata or {})
        metadata.setdefault('fieldId', field_id)
        return metadata

    def _get_field_tooltip_metadata(
        self,
        field_id: str,
        field_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = self._field_metadata_with_id(field_id, field_metadata)
        if not metadata.get('description') and field_id:
            description = self._field_descriptions_by_id.get(field_id)
            if description:
                metadata['description'] = description
        return metadata

    async def _ensure_field_descriptions_loaded(self) -> None:
        if self._field_descriptions_by_id:
            return

        self._field_descriptions_loading = True
        application = cast('JiraApp', self.app)  # noqa: F821
        try:
            response = await application.api.get_fields()
            if not response.success or not response.result:
                return

            self._field_descriptions_by_id = {
                field.id: field.description
                for field in response.result
                if field.id and field.description
            }
        finally:
            self._field_descriptions_loading = False

    def _start_field_descriptions_loading(self) -> None:
        if self._field_descriptions_by_id or self._field_descriptions_loading:
            return
        self._field_descriptions_loading = True
        self.run_worker(self._load_field_descriptions_in_background(), exclusive=False)

    async def _load_field_descriptions_in_background(self) -> None:
        await self._ensure_field_descriptions_loaded()
        if not self.is_mounted or not self.work_item:
            return

        def apply_tooltip_refresh() -> None:
            if not self.work_item:
                return
            self._update_static_field_tooltips(self.work_item)
            self._update_dynamic_field_tooltips(self.work_item)

        self.call_after_refresh(apply_tooltip_refresh)

    def _update_static_field_tooltips(self, work_item: JiraWorkItem) -> None:
        fields = work_item.edit_meta.get('fields', {}) if work_item.edit_meta else {}

        field_bindings: list[tuple[FieldRowSlot, Widget, dict[str, Any] | None]] = [
            (
                self.status_field_container,
                self.work_item_status_selector,
                self._get_field_tooltip_metadata(
                    'status',
                    fields.get('status'),
                ),
            ),
            (
                self.priority_field_container,
                self.priority_selector,
                self._get_field_tooltip_metadata(
                    self.priority_selector.jira_field_key,
                    fields.get(self.priority_selector.jira_field_key),
                ),
            ),
            (
                self.assignee_field_container,
                self.assignee_selector,
                self._get_field_tooltip_metadata(
                    self.assignee_selector.jira_field_key,
                    fields.get(self.assignee_selector.jira_field_key),
                ),
            ),
            (
                self.labels_field_container,
                self.work_item_labels_widget,
                self._get_field_tooltip_metadata(
                    self.work_item_labels_widget.jira_field_key,
                    fields.get(self.work_item_labels_widget.jira_field_key),
                ),
            ),
            (
                self.components_field_container,
                self.work_item_components_widget,
                self._get_field_tooltip_metadata(
                    self.work_item_components_widget.jira_field_key,
                    fields.get(self.work_item_components_widget.jira_field_key),
                ),
            ),
            (
                self.affects_version_field_container,
                self.work_item_affects_version_widget,
                self._get_field_tooltip_metadata(
                    self.work_item_affects_version_widget.jira_field_key,
                    fields.get(self.work_item_affects_version_widget.jira_field_key),
                ),
            ),
            (
                self.fix_version_field_container,
                self.work_item_fix_version_widget,
                self._get_field_tooltip_metadata(
                    self.work_item_fix_version_widget.jira_field_key,
                    fields.get(self.work_item_fix_version_widget.jira_field_key),
                ),
            ),
            (
                self.story_points_field_container,
                self.work_item_story_points_widget,
                self._get_field_tooltip_metadata(
                    self.work_item_story_points_widget.jira_field_key,
                    fields.get(self.work_item_story_points_widget.jira_field_key),
                ),
            ),
            (
                self.sprint_field_container,
                self.sprint_picker_widget,
                self._get_field_tooltip_metadata(
                    self.sprint_picker_widget.jira_field_key,
                    fields.get(self.sprint_picker_widget.jira_field_key),
                ),
            ),
            (
                self.due_date_container,
                self.work_item_due_date_field,
                self._get_field_tooltip_metadata(
                    self.work_item_due_date_field.jira_field_key,
                    fields.get(self.work_item_due_date_field.jira_field_key),
                ),
            ),
        ]

        for container, widget, field_metadata in field_bindings:
            self._apply_field_tooltip(container, widget, field_metadata)

    def _update_dynamic_field_tooltips(self, work_item: JiraWorkItem) -> None:
        fields = work_item.edit_meta.get('fields', {}) if work_item.edit_meta else {}

        for wrapper in self._iter_dynamic_field_wrappers():
            widget = wrapper.widget
            field_id = wrapper.jira_field_key
            if widget is None or not field_id:
                continue

            tooltip = build_field_tooltip(
                self._get_field_tooltip_metadata(field_id, fields.get(field_id))
            )
            wrapper.tooltip = tooltip
            try:
                wrapper.query_one(Label).tooltip = tooltip
            except Exception:
                pass
            widget.tooltip = tooltip

    def compose(self) -> ComposeResult:
        with VerticalScroll(id='work-item-fields-form') as fields_form:
            fields_form.can_focus = False
            with Vertical(id='time-tracking-container') as time_tracking_container:
                time_tracking_container.display = False
                yield TimeTrackingWidget()

            with StaticFieldsWidgets():
                with FieldRowSlot(id='status-field-container'):
                    with Horizontal(id='status-field-row'):
                        yield self._field_label('Status')
                        yield self._field_control(WorkItemStatusSelectionInput([]))
                with FieldRowSlot(
                    id='resolution-field-container', include_top_spacer=True
                ) as resolution_container:
                    resolution_container.display = False
                    with Horizontal(id='resolution-field-row'):
                        yield self._field_label('Resolution')
                        yield self._field_control(ReadOnlyInputField(id='resolution'))
                with FieldRowSlot(id='priority-field-container', include_top_spacer=True):
                    with Horizontal(id='priority-field-row'):
                        yield self._field_label('Priority')
                        yield self._field_control(
                            SelectionWidget(
                                mode=FieldMode.UPDATE,
                                field_id='priority',
                                options=[],
                            )
                        )
                with FieldRowSlot(id='assignee-field-container', include_top_spacer=True):
                    with Horizontal(id='assignee-field-row'):
                        yield self._field_label('Assignee')
                        yield self._field_control(UserSelectionInput(users=[]))
                with FieldRowSlot(id='reporter-field-container', include_top_spacer=True):
                    with Horizontal(id='reporter-field-row'):
                        yield self._field_label('Reporter')
                        yield self._field_control(ReadOnlyInputField(id='reporter'))
                with FieldRowSlot(id='labels-field-container', include_top_spacer=True):
                    with Horizontal(id='labels-field-row'):
                        yield self._field_label('Labels')
                        yield self._field_control(
                            WorkItemLabels(
                                mode=FieldMode.UPDATE,
                                field_id='labels',
                                title='Labels',
                            )
                        )
                with FieldRowSlot(id='components-field-container', include_top_spacer=True):
                    with Horizontal(id='components-field-row'):
                        yield self._field_label('Components')
                        yield self._field_control(
                            MultiSelect(
                                mode=FieldMode.UPDATE,
                                field_id='components',
                                options=[],
                                title='Components',
                                required=False,
                            )
                        )
                with FieldRowSlot(id='affects-version-field-container', include_top_spacer=True):
                    with Horizontal(id='affects-version-field-row'):
                        yield self._field_label('Affects Versions')
                        yield self._field_control(
                            MultiSelect(
                                mode=FieldMode.UPDATE,
                                field_id='versions',
                                options=[],
                                title='Affects Versions',
                                required=False,
                            )
                        )
                with FieldRowSlot(id='fix-version-field-container', include_top_spacer=True):
                    with Horizontal(id='fix-version-field-row'):
                        yield self._field_label('Fix Versions')
                        yield self._field_control(
                            MultiSelect(
                                mode=FieldMode.UPDATE,
                                field_id='fixVersions',
                                options=[],
                                title='Fix Versions',
                                required=False,
                            )
                        )
                with FieldRowSlot(id='story-points-field-container', include_top_spacer=True):
                    with Horizontal(id='story-points-field-row'):
                        yield self._field_label('Story Points')
                        yield self._field_control(
                            NumericInput(
                                mode=FieldMode.UPDATE,
                                field_id='story-points',
                                title='Story Points',
                            )
                        )
                with FieldRowSlot(
                    id='sprint-field-container', include_top_spacer=True
                ) as sprint_container:
                    sprint_container.display = False
                    with Horizontal(id='sprint-field-row'):
                        yield self._field_label('Sprint')
                        yield self._field_control(
                            SprintPicker(
                                mode=FieldMode.UPDATE,
                                field_id='sprint',
                                title='Sprint',
                            )
                        )

            yield DynamicFieldsWidgets()

            with DateMetadata():
                with FieldRowSlot(id='due-date-container'):
                    with Horizontal(id='due-date-row'):
                        yield self._field_label('Due Date')
                        yield self._field_control(
                            DateInput(
                                mode=FieldMode.UPDATE,
                                field_id='due-date',
                                title='Due Date',
                            )
                        )
                with FieldRowSlot(id='updated-container', include_top_spacer=True):
                    with Horizontal(id='updated-row'):
                        yield self._field_label('Updated')
                        yield self._field_control(ReadOnlyInputField(id='updated'))
                with FieldRowSlot(id='created-container', include_top_spacer=True):
                    with Horizontal(id='created-row'):
                        yield self._field_label('Created')
                        yield self._field_control(ReadOnlyInputField(id='created'))
                with FieldRowSlot(
                    id='resolution-date-container', include_top_spacer=True
                ) as resolution_date_container:
                    resolution_date_container.display = False
                    with Horizontal(id='resolution-date-row'):
                        yield self._field_label('Resolution Date')
                        yield self._field_control(ReadOnlyInputField(id='resolution-date'))
        with Horizontal(
            id='work-item-fields-pending-changes-container'
        ) as pending_changes_container:
            pending_changes_container.display = True
            yield PendingChangesWidget(id='work-item-fields-pending-changes-indicator')

    def _setup_jump_mode(self) -> None:
        content = self.content_container

        for widget in content.walk_children(Widget):
            if hasattr(widget, 'jump_mode'):
                set_jump_mode(widget, None)

        if hasattr(self.pending_changes_button, 'jump_mode'):
            set_jump_mode(self.pending_changes_button, None)

        for widget in content.query('.field_control'):
            if not isinstance(widget, Widget):
                continue
            if not widget.can_focus:
                continue
            if widget.disabled:
                continue
            if getattr(widget, 'read_only', False):
                continue
            set_jump_mode(widget, 'focus')

        if self.pending_changes_button.can_focus and not self.pending_changes_button.disabled:
            set_jump_mode(self.pending_changes_button, 'click')

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
        except Exception:
            pass

    def on_resize(self) -> None:
        self._update_layout_mode()

    def _schedule_field_spacing_refresh(self) -> None:
        if not self.is_mounted:
            return
        self.call_after_refresh(self._refresh_field_spacing)

    def _refresh_field_spacing(self) -> None:
        previous_visible_row_exists = False
        ordered_items: list[Widget] = []
        if self.time_tracking_container.display:
            ordered_items.append(self.time_tracking_container)

        ordered_items.extend(
            slot
            for slot in [
                self.status_field_container,
                self.resolution_field_container,
                self.priority_field_container,
                self.assignee_field_container,
                self.reporter_field_container,
                self.labels_field_container,
                self.components_field_container,
                self.affects_version_field_container,
                self.fix_version_field_container,
                self.story_points_field_container,
                self.sprint_field_container,
            ]
            if slot.display
        )

        dynamic_rows = [
            child
            for child in self.dynamic_fields_widgets_container.children
            if isinstance(child, FieldRowSlot) and child.display
        ]
        if dynamic_rows:
            ordered_items.extend(dynamic_rows)

        ordered_items.extend(
            slot
            for slot in [
                self.due_date_container,
                self.updated_container,
                self.created_container,
                self.resolution_date_container,
            ]
            if slot.display
        )

        self.time_tracking_container.set_styles('margin: 0 0 0 0;')
        self.dynamic_fields_widgets_container.set_styles('margin: 0 0 0 0;')

        for child in self.dynamic_fields_widgets_container.children:
            if isinstance(child, FieldRowSlot):
                child.set_spacer_visible(False)

        for item in ordered_items:
            if isinstance(item, FieldRowSlot):
                item.set_spacer_visible(previous_visible_row_exists)
            else:
                item.set_styles(f'margin: {1 if previous_visible_row_exists else 0} 0 0 0;')
            previous_visible_row_exists = True

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
            except Exception:
                pass

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
            'sprint-field-container': lambda: self.sprint_picker_widget,
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
                        and widget.value != Select.NULL
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
            except Exception:
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
        self._update_pending_changes_footer()
        self._update_notification_label_visibility(has_changes)

    def _update_notification_label_visibility(self, has_changes: bool) -> None:
        self.refresh(layout=True)

    def _update_pending_changes_footer(self) -> None:
        self.pending_changes_indicator.has_pending_changes = self.has_pending_changes
        if self._save_in_progress:
            self.pending_changes_indicator.is_loading = True
            return

        self.pending_changes_indicator.is_loading = False

    def action_view_worklog(self) -> None:
        if self.work_item:
            self.run_worker(self._open_worklog_screen_if_logs_exist())

    async def _open_worklog_screen_if_logs_exist(self) -> None:
        if not self.work_item:
            return

        response: APIControllerResponse = await cast('JiraApp', self.app).api.get_work_item_worklog(
            self.work_item.key, limit=1
        )

        if not response.success:
            self.notify(
                f'Unable to load work logs: {response.error}',
                severity='error',
                title=self.work_item.key,
            )
            return

        if not response.result or not response.result.logs:
            self.notify(
                'Work item has no work logs',
                severity='warning',
                title=self.work_item.key,
            )
            return

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
                    started=datetime.now().strftime('%Y-%m-%d %H:%M'),
                ),
                self._request_adding_worklog,
            )

    def _handle_worklog_screen_dismissal(self, response: dict | None = None) -> None:
        if response and (response.get('work_logs_deleted') or response.get('work_logs_updated')):
            self.run_worker(self._refresh_work_item_fields())

    @staticmethod
    def _extract_field_id_list(value: Any) -> list[str]:
        if value is None:
            return []

        result: list[str] = []
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    item_id = item.get('id')
                    if item_id is not None:
                        result.append(str(item_id))
                elif hasattr(item, 'id'):
                    result.append(str(item.id))  # pyright: ignore[reportAttributeAccessIssue]
                elif isinstance(item, (str, int)):
                    result.append(str(item))
        return result

    @staticmethod
    def _extract_dynamic_current_values(work_item: JiraWorkItem) -> dict[str, Any]:
        current_values: dict[str, Any] = {}
        edit_meta_fields = work_item.edit_meta.get('fields', {}) if work_item.edit_meta else {}

        for field_id, field in edit_meta_fields.items():
            field_key = field.get('key', '')

            if field_id in work_item.get_custom_fields():
                current_values[field_id] = work_item.get_custom_field_value(field_id)
            elif field_id in work_item.get_additional_fields():
                current_values[field_id] = work_item.get_additional_field_value(field_id)
            elif hasattr(work_item, field_key) and field_key:
                current_values[field_id] = getattr(work_item, field_key)

        return current_values

    def _iter_dynamic_field_wrappers(self) -> list[DynamicFieldWrapper]:
        return list(self.dynamic_fields_widgets_container.query(DynamicFieldWrapper))

    async def _update_dynamic_widgets_values(
        self,
        updated_work_item: JiraWorkItem,
        editable_fields: dict[str, bool],
        changed_fields: set[str] | None = None,
    ) -> None:
        if not CONFIGURATION.get().enable_updating_additional_fields:
            return

        current_values = self._extract_dynamic_current_values(updated_work_item)

        for wrapper in self._iter_dynamic_field_wrappers():
            dynamic_widget = wrapper.widget
            field_key = wrapper.jira_field_key

            if not dynamic_widget or not field_key:
                continue

            if changed_fields is not None and field_key not in changed_fields:
                continue

            current_value = current_values.get(field_key)
            field_is_editable = editable_fields.get(field_key)

            if isinstance(dynamic_widget, DateInput):
                dynamic_widget.set_original_value(str(current_value) if current_value else None)
            elif isinstance(dynamic_widget, DateTimeInput):
                string_value = str(current_value) if current_value else ''
                dynamic_widget._original_value = string_value
                dynamic_widget.value = string_value
            elif isinstance(dynamic_widget, NumericInput):
                if current_value is None:
                    dynamic_widget._original_value = None
                    dynamic_widget.value = ''
                else:
                    float_value = float(current_value)
                    dynamic_widget._original_value = float_value
                    dynamic_widget.value = str(float_value)
            elif isinstance(dynamic_widget, SelectionWidget):
                selection_id = None
                if isinstance(current_value, dict):
                    selection_id = current_value.get('id')
                elif current_value is not None:
                    selection_id = str(current_value)

                dynamic_widget._original_value = selection_id
                try:
                    dynamic_widget.value = selection_id if selection_id else Select.NULL
                except Exception:
                    dynamic_widget.value = Select.NULL
            elif isinstance(dynamic_widget, URL) or isinstance(dynamic_widget, TextInput):
                string_value = str(current_value) if current_value else ''
                dynamic_widget._original_value = string_value
                dynamic_widget.value = string_value
            elif isinstance(dynamic_widget, WorkItemLabels):
                labels = [str(v) for v in current_value] if isinstance(current_value, list) else []
                await dynamic_widget.set_labels(labels)
            elif isinstance(dynamic_widget, MultiSelect):
                options = [
                    (name, value_id) for name, value_id in dynamic_widget._name_to_id.items()
                ]
                original_ids = self._extract_field_id_list(current_value)
                await dynamic_widget.update_options(
                    options=options,
                    original_value=original_ids,
                    field_supports_update=dynamic_widget.update_enabled,
                )
            elif isinstance(dynamic_widget, UserPicker):
                account_id = None
                if isinstance(current_value, dict):
                    account_id = current_value.get('accountId')
                elif current_value is not None:
                    account_id = str(current_value)

                dynamic_widget._original_value = account_id
                dynamic_widget.pending_value = account_id
                dynamic_widget.value = account_id if account_id else Select.NULL

            if field_is_editable is not None and hasattr(dynamic_widget, 'update_enabled'):
                widget_with_update_enabled = cast(Any, dynamic_widget)
                widget_with_update_enabled.update_enabled = bool(field_is_editable)

    def _field_changed(self, changed_fields: set[str] | None, *field_keys: str | None) -> bool:
        if changed_fields is None:
            return True

        normalized_keys = {field_key for field_key in field_keys if field_key}
        return bool(normalized_keys & changed_fields)

    @staticmethod
    def _normalize_changed_fields(payload: dict[str, Any], status_changed: bool) -> set[str] | None:
        changed_fields = {
            ('assignee' if field_key == 'assignee_account_id' else field_key)
            for field_key in payload
        }

        if status_changed:
            changed_fields.add('status')

        return changed_fields or None

    async def _update_work_item_field_values(
        self,
        updated_work_item: JiraWorkItem,
        changed_fields: set[str] | None = None,
    ) -> None:
        if not self.work_item:
            return

        self._loading_form = True
        try:
            self.work_item.__dict__.update(updated_work_item.__dict__)
            editable_fields = self._determine_editable_fields(updated_work_item)
            refresh_all = changed_fields is None or 'status' in changed_fields

            with self.app.batch_update():
                if refresh_all or self._field_changed(changed_fields, 'status'):
                    if updated_work_item.resolution_date:
                        self.work_item_resolution_date_field.value = datetime.strftime(
                            updated_work_item.resolution_date, '%Y-%m-%d %H:%M'
                        )
                        self.resolution_date_container.display = True
                    else:
                        self.work_item_resolution_date_field.value = ''
                        self.resolution_date_container.display = False

                    if updated_work_item.resolution:
                        self.work_item_resolution_field.value = updated_work_item.resolution
                        self.resolution_field_container.display = True
                    else:
                        self.work_item_resolution_field.value = ''
                        self.resolution_field_container.display = False

                if updated_work_item.updated:
                    self.work_item_last_update_date_field.value = datetime.strftime(
                        updated_work_item.updated, '%Y-%m-%d %H:%M'
                    )

                if refresh_all or self._field_changed(
                    changed_fields, self.assignee_selector.jira_field_key
                ):
                    if updated_work_item.assignee:
                        self.assignee_selector.original_value = (
                            updated_work_item.assignee.account_id
                        )
                        self.assignee_selector.value = updated_work_item.assignee.account_id
                    else:
                        self.assignee_selector.original_value = None
                        self.assignee_selector.value = Select.NULL

                if refresh_all or self._field_changed(
                    changed_fields, self.priority_selector.jira_field_key
                ):
                    if updated_work_item.priority:
                        self.priority_selector._original_value = updated_work_item.priority.id
                        self.priority_selector.value = updated_work_item.priority.id
                    else:
                        self.priority_selector._original_value = None
                        self.priority_selector.value = Select.NULL

                if refresh_all or self._field_changed(changed_fields, 'status'):
                    if updated_work_item.status:
                        self.work_item_status_selector.prompt = updated_work_item.status.name
                        self.work_item_status_selector.original_value = updated_work_item.status.id
                        self.work_item_status_selector.value = Select.NULL

                if refresh_all or self._field_changed(
                    changed_fields, self.work_item_due_date_field.jira_field_key
                ):
                    self.work_item_due_date_field.set_original_value(
                        updated_work_item.display_due_date
                    )
                    self.work_item_due_date_field.update_enabled = editable_fields.get(
                        self.work_item_due_date_field.jira_field_key, True
                    )

                if refresh_all or self._field_changed(changed_fields, 'timetracking', 'status'):
                    self._setup_time_tracking(updated_work_item)

            setup_tasks = []

            if refresh_all or self._field_changed(changed_fields, 'status'):
                setup_tasks.append(
                    self._retrieve_applicable_status_codes(
                        updated_work_item.key,
                        updated_work_item.status.name if updated_work_item.status else None,
                        updated_work_item.status.status_category_color
                        if updated_work_item.status
                        else None,
                    )
                )

            if refresh_all or self._field_changed(
                changed_fields, self.assignee_selector.jira_field_key, 'status'
            ):
                setup_tasks.append(
                    self._retrieve_users_assignable_to_work_item(
                        updated_work_item.key,
                        updated_work_item.assignee,
                        editable_fields.get(self.assignee_selector.jira_field_key),
                    )
                )

            if refresh_all or self._field_changed(
                changed_fields, self.work_item_labels_widget.jira_field_key
            ):
                setup_tasks.append(self._setup_labels_field(updated_work_item, editable_fields))

            if refresh_all or self._field_changed(
                changed_fields, self.work_item_components_widget.jira_field_key
            ):
                setup_tasks.append(self._setup_components_field(updated_work_item, editable_fields))

            if refresh_all or self._field_changed(
                changed_fields, self.work_item_affects_version_widget.jira_field_key
            ):
                setup_tasks.append(
                    self._setup_affects_version_field(updated_work_item, editable_fields)
                )

            if refresh_all or self._field_changed(
                changed_fields, self.work_item_fix_version_widget.jira_field_key
            ):
                setup_tasks.append(
                    self._setup_fix_version_field(updated_work_item, editable_fields)
                )

            if refresh_all or self._field_changed(
                changed_fields, self.work_item_story_points_widget.jira_field_key
            ):
                setup_tasks.append(
                    self._setup_story_points_field(updated_work_item, editable_fields)
                )

            if refresh_all or self._field_changed(
                changed_fields, self.sprint_picker_widget.jira_field_key
            ):
                setup_tasks.append(self._setup_sprint_field(updated_work_item, editable_fields))

            if CONFIGURATION.get().enable_updating_additional_fields:
                setup_tasks.append(
                    self._update_dynamic_widgets_values(
                        updated_work_item,
                        editable_fields,
                        None if refresh_all else changed_fields,
                    )
                )

            await asyncio.gather(*setup_tasks)

            if CONFIGURATION.get().enable_updating_additional_fields and refresh_all:
                self.run_worker(
                    self._populate_user_picker_widgets(updated_work_item, editable_fields),
                    exclusive=False,
                )

            self._update_static_field_tooltips(updated_work_item)
            self._update_dynamic_field_tooltips(updated_work_item)
            self._start_field_descriptions_loading()
            self.has_pending_changes = False
            self._update_all_field_labels_styling()
            self._schedule_field_spacing_refresh()
        finally:
            self._loading_form = False

    async def _refresh_work_item_fields(self) -> None:
        if not self.work_item or not self.work_item.key:
            return

        work_item_key = self.work_item.key

        application = cast('JiraApp', self.app)  # noqa: F821
        work_item_fields_response = await application.api.get_work_item(
            work_item_id_or_key=work_item_key
        )
        if work_item_fields_response.success and work_item_fields_response.result:
            updated_work_item = work_item_fields_response.result.work_items[0]

            if self.work_item and self.work_item.key == updated_work_item.key:
                await self._update_work_item_field_values(updated_work_item)
            else:
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

    def _update_priority_selection(self, priority_id: str) -> None:
        normalized_priority_id = str(priority_id)
        self.priority_selector.value = normalized_priority_id
        self.priority_selector._original_value = normalized_priority_id

    def _update_assignee_selection(self, assignee_id: str) -> None:
        self.assignee_selector.value = assignee_id
        self.assignee_selector.original_value = assignee_id

    def _setup_priority_selector(
        self, work_item_edit_meta: dict | None, work_item_priority: WorkItemPriority
    ) -> None:
        if work_item_edit_meta:
            if not (priority_field := get_nested(work_item_edit_meta, 'fields', 'priority')):
                self.priority_selector.update_enabled = False
            else:
                priorities: list[tuple[str, str]] = []
                for v in priority_field.get('allowedValues', []):
                    priorities.append((v.get('name'), v.get('id')))

                self.priority_selector.set_options(priorities)

                if work_item_priority:
                    self._update_priority_selection(work_item_priority.id)
        else:
            self.priority_selector.update_enabled = False

    async def watch_clear_form(self, clear: bool = False) -> None:
        if clear and self._loading_form:
            return
        if clear:
            self.work_item_resolution_field.value = ''
            self.resolution_field_container.display = False
            self.work_item_resolution_date_field.value = ''
            self.resolution_date_container.display = False
            self.work_item_last_update_date_field.value = ''
            self.reporter_field.value = ''
            self.work_item_status_selector.value = Select.NULL
            self.work_item_status_selector.prompt = 'Select a status'
            self.work_item_status_selector.disabled = False
            self.assignee_selector.value = Select.NULL
            self.assignee_selector.original_value = None
            self.priority_selector.value = Select.NULL
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

            self.sprint_picker_widget.sprints = None
            self.sprint_picker_widget._original_value = None
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            self._schedule_field_spacing_refresh()

    def watch_is_loading(self, loading: bool) -> None:
        with self.app.batch_update():
            self.content_container.display = loading or self.work_item is not None
            self.set_class(loading, '-loading')
            self.time_tracking_container.display = (
                not loading and self._show_time_tracking_after_load
            )

    @staticmethod
    def _format_duration(seconds: int | None) -> str | None:
        if seconds is None:
            return None
        if seconds <= 0:
            return '0m'

        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60

        parts: list[str] = []
        if hours:
            parts.append(f'{hours}h')
        if minutes:
            parts.append(f'{minutes}m')

        return ' '.join(parts) if parts else '0m'

    def _setup_time_tracking(self, work_item: JiraWorkItem | None) -> None:
        widget = self.time_tracking_widget
        time_tracking_data = work_item.time_tracking if work_item else None
        additional_fields = work_item.additional_fields or {} if work_item else {}
        aggregate_time_spent = additional_fields.get('aggregatetimespent')
        remaining_estimate_seconds = (
            time_tracking_data.remaining_estimate_seconds
            if time_tracking_data and time_tracking_data.remaining_estimate_seconds is not None
            else additional_fields.get('timeestimate')
        )
        remaining_estimate = (
            time_tracking_data.remaining_estimate
            if time_tracking_data and time_tracking_data.remaining_estimate
            else self._format_duration(remaining_estimate_seconds)
        )
        time_spent_seconds = (
            time_tracking_data.time_spent_seconds
            if time_tracking_data and time_tracking_data.time_spent_seconds is not None
            else aggregate_time_spent
        )
        time_spent = (
            time_tracking_data.time_spent
            if time_tracking_data and time_tracking_data.time_spent
            else self._format_duration(time_spent_seconds)
        )
        original_estimate_seconds = (
            time_tracking_data.original_estimate_seconds
            if time_tracking_data and time_tracking_data.original_estimate_seconds is not None
            else additional_fields.get('timeoriginalestimate')
        )
        original_estimate = (
            time_tracking_data.original_estimate
            if time_tracking_data and time_tracking_data.original_estimate
            else self._format_duration(original_estimate_seconds)
        )

        if aggregate_time_spent is None:
            self._show_time_tracking_after_load = False
            self.time_tracking_container.display = False
            widget.update_time_tracking(
                original_estimate=None,
                time_spent=None,
                remaining_estimate=None,
                original_estimate_seconds=None,
                time_spent_seconds=None,
                remaining_estimate_seconds=None,
            )
            self._schedule_field_spacing_refresh()
            return

        self._show_time_tracking_after_load = True
        self.time_tracking_container.display = not self.is_loading
        widget.update_time_tracking(
            original_estimate,
            time_spent,
            remaining_estimate,
            original_estimate_seconds,
            time_spent_seconds,
            remaining_estimate_seconds,
        )
        self._schedule_field_spacing_refresh()

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

        if self.sprint_picker_widget.update_enabled:
            if self.sprint_picker_widget.value_has_changed:
                payload[self.sprint_picker_widget.jira_field_key] = (
                    self.sprint_picker_widget.get_value_for_update()
                )

        if CONFIGURATION.get().enable_updating_additional_fields:
            for wrapper in self._iter_dynamic_field_wrappers():
                dynamic_widget = wrapper.widget
                if not dynamic_widget:
                    continue

                if not hasattr(dynamic_widget, 'value_has_changed') or not hasattr(
                    dynamic_widget, 'get_value_for_update'
                ):
                    continue

                if not wrapper.value_has_changed:
                    continue

                field_key = wrapper.jira_field_key
                if not field_key:
                    continue

                payload[field_key] = wrapper.get_value_for_update()
        return payload

    def _check_for_pending_changes(self) -> bool:
        if not self.work_item:
            return False

        payload = self._build_payload_for_update()
        has_field_changes = bool(payload)

        has_status_change = (
            self.work_item_status_selector.selection is not None
            and self.work_item_status_selector.selected_status_id != self.work_item.status.id
        )

        return has_field_changes or has_status_change

    def action_save_work_item(self) -> None:
        if self._save_in_progress:
            return

        self._save_in_progress = True
        self._update_pending_changes_footer()
        self._save_work_item()

    @on(Button.Pressed, '#work-item-fields-pending-changes-button')
    def handle_pending_changes_button_pressed(self) -> None:
        self.action_save_work_item()

    @work(exclusive=False, group='save-work-item')
    async def _save_work_item(self) -> None:
        if not self.work_item:
            self._save_in_progress = False
            return

        work_item_key = self.work_item.key if self.work_item else None
        if not work_item_key:
            self._save_in_progress = False
            return

        try:
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
                and self.work_item_status_selector.selected_status_id != self.work_item.status.id
            )

            if not payload and not work_item_requires_transition:
                return

            application = cast('JiraApp', self.app)  # noqa: F821
            work_item_updated_successfully = False
            work_item_transitioned_successfully = False
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
                        work_item_was_updated = True
                        work_item_updated_successfully = True
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
                transition_id = self.work_item_status_selector.selection
                if transition_id is None:
                    self.notify(
                        'Invalid status selection',
                        severity='error',
                        title=work_item_key,
                    )
                    return

                response = await application.api.transition_work_item_status(
                    self.work_item.key, str(transition_id)
                )
                if not response.success:
                    self.notify(
                        f'Failed to transition the work item to a different status: {response.error}',
                        severity='error',
                        title=work_item_key,
                    )
                else:
                    work_item_was_updated = True
                    work_item_transitioned_successfully = True

            if not work_item_was_updated:
                return

            self.has_pending_changes = False

            if not self.work_item or not self.work_item.key:
                return

            work_item_key = self.work_item.key
            work_item_fields_response = await application.api.get_work_item(
                work_item_id_or_key=work_item_key
            )
            if work_item_fields_response.success and work_item_fields_response.result:
                updated_work_item = work_item_fields_response.result.work_items[0]
                changed_fields = self._normalize_changed_fields(
                    payload, work_item_requires_transition
                )

                if work_item_updated_successfully and work_item_transitioned_successfully:
                    self.notify(
                        f'Work item updated successfully and transitioned to {updated_work_item.status.name}.',
                        title=work_item_key,
                    )
                elif work_item_updated_successfully:
                    self.notify('Work item updated successfully.', title=work_item_key)
                elif work_item_transitioned_successfully:
                    self.notify(
                        f'Successfully transitioned the work item to {updated_work_item.status.name}.',
                        title=work_item_key,
                    )

                await self._update_work_item_field_values(updated_work_item, changed_fields)

                self.post_message(WorkItemUpdated(updated_work_item))
            else:
                if work_item_updated_successfully and work_item_transitioned_successfully:
                    self.notify(
                        'Work item updated successfully and transitioned status successfully.',
                        title=work_item_key,
                    )
                elif work_item_updated_successfully:
                    self.notify('Work item updated successfully.', title=work_item_key)
                elif work_item_transitioned_successfully:
                    self.notify(
                        'Successfully transitioned the work item status.', title=work_item_key
                    )
        finally:
            self._save_in_progress = False
            self._update_pending_changes_footer()
            if self.has_pending_changes:
                self.pending_changes_button.disabled = False

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

        if self.work_item and self.work_item.key != work_item_key:
            return

        selectable_users: list[tuple[str, str]] = self._generate_assignable_users_for_dropdown(
            response.result,
            current_assignee,
            self.available_users,
        )

        self._apply_assignable_users_options(
            selectable_users,
            current_assignee=current_assignee,
            field_is_editable=field_is_editable,
        )

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
                        allowed_status_options.append(
                            (display_name, str(transition.id), str(transition.to_state.id))
                        )

                allowed_status_options = sorted(allowed_status_options, key=lambda x: str(x[0]))
                self.work_item_status_selector.set_transition_options(allowed_status_options)
                self.work_item_status_selector.disabled = False

                if current_status_name:
                    self.work_item_status_selector.prompt = current_status_name

    def _apply_assignable_users_options(
        self,
        selectable_users: list[tuple[str, str]],
        current_assignee: JiraUser | None = None,
        field_is_editable: bool | None = None,
    ) -> None:
        if selectable_users:
            self.assignee_selector.set_options(selectable_users)
            if current_assignee:
                self.set_timer(
                    0.01,
                    lambda: self._update_assignee_selection(current_assignee.account_id),
                )
            else:
                self.assignee_selector.original_value = None
            self.assignee_selector.update_enabled = bool(field_is_editable)
            return

        if current_assignee:
            self.assignee_selector.set_options(
                [(current_assignee.display_name, current_assignee.account_id)]
            )
            self.set_timer(
                0.01,
                lambda: self._update_assignee_selection(current_assignee.account_id),
            )
            self.assignee_selector.update_enabled = bool(field_is_editable)
        else:
            self.assignee_selector.original_value = None
            self.assignee_selector.update_enabled = False

    def _prefill_status_selector(
        self,
        current_status_name: str | None = None,
        current_status_id: str | None = None,
    ) -> None:
        self.work_item_status_selector.set_options([])
        self.work_item_status_selector.value = Select.NULL
        self.work_item_status_selector.original_value = current_status_id
        self.work_item_status_selector._transition_status_ids = {}
        self.work_item_status_selector.disabled = True
        self.work_item_status_selector.prompt = current_status_name or 'Select a status'

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        if self._current_loading_worker is not None:
            self._current_loading_worker.cancel()
            self._current_loading_worker = None
        if self._assignee_refresh_worker is not None:
            self._assignee_refresh_worker.cancel()
            self._assignee_refresh_worker = None
        if self._status_refresh_worker is not None:
            self._status_refresh_worker.cancel()
            self._status_refresh_worker = None

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

        await self.watch_clear_form(True)

        self._loading_form = True

        editable_fields: dict = self._determine_editable_fields(work_item)

        if work_item.key:
            self._prefill_status_selector(
                work_item.status.name if work_item.status else None,
                work_item.status.id if work_item.status else None,
            )
            prefilled_users = self._generate_assignable_users_for_dropdown(
                None,
                work_item.assignee,
                self.available_users,
            )
            self._apply_assignable_users_options(
                prefilled_users,
                current_assignee=work_item.assignee,
                field_is_editable=editable_fields.get(self.assignee_selector.jira_field_key),
            )

            self._status_refresh_worker = self.run_worker(
                self._retrieve_applicable_status_codes(
                    work_item.key,
                    work_item.status.name if work_item.status else None,
                    work_item.status.status_category_color if work_item.status else None,
                ),
                exclusive=False,
            )
            self._assignee_refresh_worker = self.run_worker(
                self._retrieve_users_assignable_to_work_item(
                    work_item.key,
                    work_item.assignee,
                    editable_fields.get(self.assignee_selector.jira_field_key),
                ),
                exclusive=False,
            )

            if not self.work_item or self.work_item.key != work_item_key:
                return

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

            self.work_item_due_date_field.set_original_value(work_item.display_due_date)
            self.work_item_due_date_field.update_enabled = editable_fields.get(
                self.work_item_due_date_field.jira_field_key, True
            )

            if work_item.priority:
                self._setup_priority_selector(work_item.edit_meta, work_item.priority)

            self._setup_time_tracking(work_item)

        setup_tasks = [
            self._setup_labels_field(work_item, editable_fields),
            self._setup_components_field(work_item, editable_fields),
            self._setup_affects_version_field(work_item, editable_fields),
            self._setup_fix_version_field(work_item, editable_fields),
            self._setup_story_points_field(work_item, editable_fields),
            self._setup_sprint_field(work_item, editable_fields),
        ]

        if CONFIGURATION.get().enable_updating_additional_fields:
            setup_tasks.append(self._add_dynamic_fields_widgets(work_item, editable_fields))

        await asyncio.gather(*setup_tasks)
        self._update_static_field_tooltips(work_item)
        self._update_dynamic_field_tooltips(work_item)
        self._start_field_descriptions_loading()

        self.refresh(layout=True)

        if not self.work_item or self.work_item.key != work_item_key:
            return

        self._current_loading_worker = None

        with self.app.batch_update():
            self.has_pending_changes = False

            self._update_all_field_labels_styling()

        status_name = work_item.status.name if work_item and work_item.status else None
        status_id = work_item.status.id if work_item and work_item.status else None

        def finalize_form_load() -> None:
            if status_name and status_id:
                self.work_item_status_selector.original_value = status_id
                self.work_item_status_selector.prompt = status_name

            self.has_pending_changes = False
            self._loading_form = False
            self._setup_jump_mode()
            self._refresh_field_spacing()
            self.is_loading = False

            try:
                info_container = self.screen.query_one(WorkItemInfoContainer)
                info_container.signal_fields_widget_ready()
            except Exception as e:
                self.app.log.error(f'Failed to signal info container ready: {e}')

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
        skip_fields.update(get_parent_relation_field_ids_from_editmeta(edit_meta_fields))

        sprint_field_id = get_sprint_field_id_from_editmeta(edit_meta_fields)
        if sprint_field_id:
            skip_fields.add(sprint_field_id)

        # When editmeta is null, create read-only widgets for custom fields with values
        if not edit_meta_fields and work_item.custom_fields:
            # Fetch field metadata to get field names
            application = cast('JiraApp', self.app)  # noqa: F821
            fields_response = await application.api.get_fields()

            # Build a mapping of field_id -> field_name
            field_names_map = {}
            field_descriptions_map = {}
            if fields_response.success and fields_response.result:
                for field in fields_response.result:
                    field_names_map[field.id] = field.name
                    if field.description:
                        field_descriptions_map[field.id] = field.description

            containers = []
            for field_id, field_value in work_item.custom_fields.items():
                if field_value is None or field_id in skip_fields:
                    continue

                # Use field name if available, otherwise fall back to field ID
                field_label = ' '.join(str(field_names_map.get(field_id, field_id)).split())
                if is_parent_relation_field_name(field_label):
                    continue

                display_value = self._format_custom_field_value(field_value)
                if not display_value:
                    continue

                field_tooltip = build_field_tooltip(
                    {
                        'fieldId': field_id,
                        'description': field_descriptions_map.get(field_id),
                        'schema': {'custom': ''},
                    }
                )

                # Create container
                field_container = Horizontal(classes='dynamic-field-container')
                containers.append((field_container, field_label, display_value, field_tooltip))

            if containers:
                with self.app.batch_update():
                    slots = await self._mount_field_rows_with_spacers(
                        self.dynamic_fields_widgets_container,
                        [container for container, _, _, _ in containers],
                    )
                    # Then mount children to each container
                    for slot, (_, field_label, display_value, field_tooltip) in zip(
                        slots, containers, strict=True
                    ):
                        field_container = slot.query_one(
                            '.dynamic-field-container', expect_type=Horizontal
                        )
                        label = self._field_label(field_label)
                        label.tooltip = field_tooltip
                        readonly_field = ReadOnlyInputField()
                        self._field_control(readonly_field)
                        readonly_field.value = display_value
                        readonly_field.tooltip = field_tooltip
                        await field_container.mount(label, readonly_field)

                    self.dynamic_fields_widgets_container.display = True
            else:
                self.dynamic_fields_widgets_container.display = False
            self._schedule_field_spacing_refresh()
            return

        # Normal path: editmeta is available, build editable widgets
        fields_data = []
        for field_id, field in edit_meta_fields.items():
            if not field.get('fieldId'):
                field['fieldId'] = field_id
            if not field.get('description'):
                description = self._field_descriptions_by_id.get(field_id)
                if description:
                    field = dict(field)
                    field['description'] = description
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
                await self._mount_field_rows_with_spacers(
                    self.dynamic_fields_widgets_container, sorted_widgets
                )
                self._apply_fields_panel_layout_to_dynamic_widgets()

                self.dynamic_fields_widgets_container.display = True

            await self._populate_user_picker_widgets(work_item, editable_fields)

            self._setup_jump_mode()
        else:
            self.dynamic_fields_widgets_container.display = False
        self._schedule_field_spacing_refresh()

    async def _mount_field_rows_with_spacers(
        self, container: VerticalGroup, rows: list[Widget]
    ) -> list[FieldRowSlot]:
        slots = [FieldRowSlot(include_top_spacer=index > 0) for index, _ in enumerate(rows)]
        await container.mount(*slots)
        for slot, row in zip(slots, rows, strict=True):
            await slot.mount(row)
        return slots

    def _apply_fields_panel_layout_to_dynamic_widgets(self) -> None:
        for wrapper in self.dynamic_fields_widgets_container.query(DynamicFieldWrapper):
            if wrapper.widget is None:
                continue

            self._apply_field_control_classes(wrapper.widget)

    async def _populate_user_picker_widgets(
        self, work_item: JiraWorkItem, editable_fields: dict
    ) -> None:
        # Yield once so newly mounted dynamic widgets can complete their compose cycle.
        await asyncio.sleep(0)

        application = cast('JiraApp', self.app)  # noqa: F821
        user_picker_widgets = self.dynamic_fields_widgets_container.query(UserPicker)

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

        labels_field_meta = get_nested(work_item.edit_meta, 'fields', 'labels')
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

        components_field_meta = get_nested(work_item.edit_meta, 'fields', 'components')
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

        versions_field_meta = get_nested(work_item.edit_meta, 'fields', 'versions')
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
                await self.static_fields_widgets_container.mount(
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
                await self.static_fields_widgets_container.mount(
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

        fix_versions_field_meta = get_nested(work_item.edit_meta, 'fields', 'fixVersions')
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

    async def _setup_sprint_field(
        self, work_item: JiraWorkItem, editable_fields: dict | None
    ) -> None:
        config = CONFIGURATION.get()

        if not config.enable_sprint_selection:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            return

        parent_has_locked_sprint = bool(
            work_item.parent_work_item_key
        ) and not is_epic_work_item_type(work_item.parent_work_item_type)
        is_subtask_with_non_epic_parent = bool(
            work_item.work_item_type and work_item.work_item_type.subtask
        ) and not is_epic_work_item_type(work_item.parent_work_item_type)

        if parent_has_locked_sprint or is_subtask_with_non_epic_parent:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False

            if work_item.sprint:
                self.sprint_field_container.display = True
                self.sprint_picker_widget.sprints = {
                    'sprints': [(work_item.sprint.name, work_item.sprint.id)],
                    'selection': work_item.sprint.id,
                }
                self.sprint_picker_widget._original_value = str(work_item.sprint.id)
            else:
                self.sprint_picker_widget.sprints = {'sprints': [], 'selection': None}
                self.sprint_picker_widget._original_value = None
                self.sprint_field_container.display = False
            return

        if not editable_fields:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            return

        if not work_item.edit_meta or 'fields' not in work_item.edit_meta:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            return

        sprint_field_id = get_sprint_field_id_from_editmeta(work_item.edit_meta.get('fields', {}))

        if not sprint_field_id:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            return

        field_can_be_updated = editable_fields.get(sprint_field_id, False)

        self.sprint_field_container.display = True
        self.sprint_picker_widget.jira_field_key = sprint_field_id
        self.sprint_picker_widget.update_enabled = field_can_be_updated
        self.sprint_picker_widget.disabled = not field_can_be_updated

        current_sprint_id = work_item.sprint.id if work_item.sprint else None
        if current_sprint_id is not None:
            self.sprint_picker_widget._original_value = str(current_sprint_id)
        else:
            self.sprint_picker_widget._original_value = None

        project_key = work_item.project.key if work_item.project else None

        if not project_key:
            self.sprint_picker_widget.disabled = True
            self.sprint_picker_widget.update_enabled = False
            self.sprint_field_container.display = False
            return

        self.sprint_picker_widget.start_loading()

        # Fetch sprints in background so work item renders immediately.
        self.run_worker(
            self._populate_static_sprint_picker(
                work_item_key=work_item.key,
                project_key=project_key,
                current_sprint_id=current_sprint_id,
            ),
            exclusive=False,
        )

    async def _populate_static_sprint_picker(
        self,
        work_item_key: str,
        project_key: str,
        current_sprint_id: int | None,
    ) -> None:

        try:
            application = cast('JiraApp', self.app)  # noqa: F821
            sprints_response = await application.api.get_sprints_for_project(project_key)

            if not self.work_item or self.work_item.key != work_item_key:
                return

            if not sprints_response.success or not sprints_response.result:
                logger.warning(f'Failed to fetch sprints for project {project_key}')
                self.sprint_picker_widget.update_enabled = False
                self.sprint_field_container.display = False
                return

            sprints_list = [(sprint.name, sprint.id) for sprint in sprints_response.result]
            sprints_dict = {
                'sprints': sprints_list,
                'selection': current_sprint_id,
            }
            self.sprint_picker_widget.sprints = sprints_dict

        except Exception as e:
            logger.warning(f'Failed to fetch sprints for project {project_key}: {e}')
            if self.work_item and self.work_item.key == work_item_key:
                self.sprint_picker_widget.update_enabled = False
                self.sprint_field_container.display = False
