from collections.abc import Callable
from enum import Enum
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Button

from gojeera.utils.data.mappings import get_nested


class FieldMode(Enum):
    """Enum to distinguish between field creation and update contexts."""

    CREATE = 'create'
    UPDATE = 'update'


class CustomFieldType(Enum):
    """Known Jira custom field types that map to specific widgets."""

    USER_PICKER = 'com.atlassian.jira.plugin.system.customfieldtypes:userpicker'
    FLOAT = 'com.atlassian.jira.plugin.system.customfieldtypes:float'
    SELECT = 'com.atlassian.jira.plugin.system.customfieldtypes:select'
    DATE_PICKER = 'com.atlassian.jira.plugin.system.customfieldtypes:datepicker'
    DATETIME = 'com.atlassian.jira.plugin.system.customfieldtypes:datetime'
    TEXT_FIELD = 'com.atlassian.jira.plugin.system.customfieldtypes:textfield'
    TEXTAREA = 'com.atlassian.jira.plugin.system.customfieldtypes:textarea'
    LABELS = 'com.atlassian.jira.plugin.system.customfieldtypes:labels'
    URL = 'com.atlassian.jira.plugin.system.customfieldtypes:url'
    MULTI_CHECKBOXES = 'com.atlassian.jira.plugin.system.customfieldtypes:multicheckboxes'
    MULTI_SELECT = 'com.atlassian.jira.plugin.system.customfieldtypes:multiselect'
    SD_REQUEST_LANGUAGE = (
        'com.atlassian.servicedesk.servicedesk-lingo-integration-plugin:sd-request-language'
    )
    GH_EPIC_LINK = 'com.pyxis.greenhopper.jira:gh-epic-link'
    GH_SPRINT = 'com.pyxis.greenhopper.jira:gh-sprint'


class BaseField:
    def setup_base_field(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
    ) -> None:
        self.mode = mode
        self.field_id = field_id
        self.label_text = title or field_id
        self._required = required

        if required:
            add_class = getattr(self, 'add_class', None)
            if callable(add_class):
                add_class('required')

    @property
    def required(self) -> bool:
        return getattr(self, '_required', False)

    @required.setter
    def required(self, value: bool) -> None:
        self._required = value
        add_class = getattr(self, 'add_class', None)
        remove_class = getattr(self, 'remove_class', None)
        if value:
            if callable(add_class):
                add_class('required')
        elif callable(remove_class):
            remove_class('required')

    def mark_required(self) -> None:
        self.required = True


class BaseUpdateField:
    def setup_update_field(
        self,
        jira_field_key: str,
        original_value: Any = None,
        field_supports_update: bool = True,
    ) -> None:
        self.jira_field_key = jira_field_key
        self._original_value = original_value
        self._field_supports_update = field_supports_update

        if hasattr(self, 'disabled'):
            self.disabled = not field_supports_update

    @property
    def original_value(self) -> Any:
        return self._original_value

    @property
    def update_enabled(self) -> bool:
        return getattr(self, '_field_supports_update', True)

    @update_enabled.setter
    def update_enabled(self, value: bool) -> None:
        self._field_supports_update = value
        if hasattr(self, 'disabled'):
            self.disabled = not value

    @property
    def value_has_changed(self) -> bool:
        raise NotImplementedError('Subclasses must implement value_has_changed')


_UNSET = object()


def update_value_or_unset(value: Any) -> Any:
    return value if value else _UNSET


def require_update_mode(mode: FieldMode, operation: str) -> None:
    if mode != FieldMode.UPDATE:
        raise ValueError(f'{operation} only valid in UPDATE mode')


def require_create_mode(mode: FieldMode, operation: str) -> None:
    if mode != FieldMode.CREATE:
        raise ValueError(f'{operation} only valid in CREATE mode')


def normalized_selection_value(value: Any) -> str | None:
    from textual.widgets import Select

    if value is Select.NULL or not value:
        return None

    value_str = str(value).strip()
    if value_str and value_str != 'Select.NULL':
        return value_str
    return None


def selection_update_payload(value: Any, value_key: str) -> dict[str, str] | None:
    value_str = normalized_selection_value(value)
    if not value_str:
        return None

    return {value_key: value_str}


def optional_selection_value_has_changed(
    *,
    original_value: str | None,
    current_value: str | None,
) -> bool:
    if not original_value:
        return bool(current_value)

    if not current_value:
        return True

    return original_value != current_value


def configure_field_for_mode(
    widget: Any,
    *,
    mode: FieldMode,
    field_id: str,
    title: str | None = None,
    required: bool = False,
    original_value: Any = None,
    field_supports_update: bool = True,
    create_classes: list[str] | None = None,
    update_value: Any = _UNSET,
    on_update: Callable[[], None] | None = None,
) -> None:
    widget.setup_base_field(
        mode=mode,
        field_id=field_id,
        title=title,
        required=required,
    )

    if mode == FieldMode.UPDATE:
        widget.setup_update_field(
            jira_field_key=field_id,
            original_value=original_value,
            field_supports_update=field_supports_update,
        )
        if update_value is not _UNSET:
            widget.value = update_value
        if on_update is not None:
            on_update()
        return

    for class_name in create_classes or []:
        widget.add_class(class_name)


def configure_compact_field_for_mode(
    widget: Any,
    **kwargs: Any,
) -> None:
    kwargs.pop('compact', None)
    configure_field_for_mode(widget, **kwargs)


def configure_select_field_for_mode(
    widget: Any,
    **kwargs: Any,
) -> None:
    configure_compact_field_for_mode(
        widget,
        create_classes=['surface-input-select'],
        **kwargs,
    )


class ValidationUtils:
    """Shared validation utilities for field widgets."""

    @staticmethod
    def is_empty_or_whitespace(value: str | None) -> bool:
        if value is None:
            return True
        if value == '':
            return True
        if value.strip() == '':
            return True
        return False

    @staticmethod
    def values_differ(original: Any, current: Any, ignore_whitespace: bool = True) -> bool:
        if ignore_whitespace and isinstance(original, str) and isinstance(current, str):
            return original.strip() != current.strip()
        return original != current


class PendingChangesWidget(Horizontal, can_focus=False):
    """Transparent footer widget that exposes a full-width pending-changes button."""

    PENDING_LABEL = 'Apply Changes'

    DEFAULT_CSS = """
    PendingChangesWidget {
        width: 100%;
        height: 1;
        background: transparent;
        margin: 0;
        padding: 0;
        align: center middle;
    }

    PendingChangesWidget > Button {
        width: 1fr;
        height: 1;
        background: transparent;
    }
    """

    has_pending_changes = reactive(False)
    is_loading = reactive(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.can_focus = False
        self.display = True

    def compose(self) -> ComposeResult:
        button = Button(
            self.PENDING_LABEL,
            id='work-item-fields-pending-changes-button',
        )
        button.display = False
        yield button

    @property
    def button(self) -> Button:
        return self.query_one(Button)

    def watch_has_pending_changes(self, has_pending_changes: bool) -> None:
        self.button.display = has_pending_changes or self.is_loading

    def watch_is_loading(self, is_loading: bool) -> None:
        self.button.display = self.has_pending_changes or is_loading
        self.button.disabled = is_loading
        self.button.label = self.PENDING_LABEL
        self.loading = is_loading


def get_custom_fields_values(fields_values: dict, edit_metadata_fields: dict) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field_id, field_data in edit_metadata_fields.items():
        schema = field_data.get('schema', {})
        if schema.get('customId') or schema.get('custom'):
            values[field_id] = fields_values.get(field_id)

    for field_id, field_value in fields_values.items():
        if not field_id.lower().startswith('customfield_'):
            continue
        if field_id not in values:
            values[field_id] = field_value
    return values


def get_additional_fields_values(
    fields_values: dict[str, Any], ignored_fields: list[str]
) -> dict[str, Any]:
    additional_fields: dict[str, Any] = {}
    for field_id, field_value in fields_values.items():
        if field_id in ignored_fields:
            continue
        if field_id.lower().startswith('customfield_'):
            continue
        additional_fields[field_id] = field_value
    return additional_fields


def get_sprint_field_id_from_fields_data(fields_data: list[dict[str, Any]]) -> str | None:
    for field in fields_data:
        field_id = field.get('fieldId')
        schema_custom = get_nested(field, 'schema', 'custom')
        if field_id and schema_custom == CustomFieldType.GH_SPRINT.value:
            return field_id
    return None


def get_sprint_field_id_from_editmeta(edit_metadata_fields: dict[str, Any]) -> str | None:
    for field_id, field_meta in edit_metadata_fields.items():
        schema_custom = get_nested(field_meta, 'schema', 'custom')
        if schema_custom == CustomFieldType.GH_SPRINT.value:
            return field_id
    return None


def is_parent_relation_field_name(field_name: str | None) -> bool:
    normalized_field_name = (field_name or '').strip().casefold()
    return normalized_field_name in {'epic', 'epic link', 'epic name', 'parent link'}


def _is_parent_relation_field(
    field_id: str | None,
    field_name: str | None,
    field_key: str | None,
    schema_custom: str | None,
) -> bool:
    normalized_field_id = (field_id or '').strip().casefold()
    normalized_field_key = (field_key or '').strip().casefold()

    if normalized_field_id == 'parent' or normalized_field_key == 'parent':
        return True

    if schema_custom == CustomFieldType.GH_EPIC_LINK.value:
        return True

    return is_parent_relation_field_name(field_name)


def get_parent_relation_field_ids_from_fields_data(fields_data: list[dict[str, Any]]) -> set[str]:
    field_ids: set[str] = set()
    for field in fields_data:
        field_id = field.get('fieldId')
        field_name = field.get('name')
        field_key = field.get('key')
        schema_custom = get_nested(field, 'schema', 'custom')
        if _is_parent_relation_field(field_id, field_name, field_key, schema_custom) and field_id:
            field_ids.add(field_id)
    return field_ids


def get_parent_relation_field_ids_from_editmeta(edit_metadata_fields: dict[str, Any]) -> set[str]:
    field_ids: set[str] = set()
    for field_id, field_meta in edit_metadata_fields.items():
        field_name = field_meta.get('name')
        field_key = field_meta.get('key')
        schema_custom = get_nested(field_meta, 'schema', 'custom')
        if _is_parent_relation_field(field_id, field_name, field_key, schema_custom):
            field_ids.add(field_id)
    return field_ids


def is_epic_work_item_type(work_item_type_name: str | None) -> bool:
    """Return whether the Jira work item type represents an epic."""

    return (work_item_type_name or '').strip().casefold() == 'epic'


def supports_parent_work_item(work_item: Any) -> bool:
    """Return whether the work item supports editing its parent relationship."""

    if work_item is None:
        return False

    work_item_type = getattr(work_item, 'work_item_type', None)
    if work_item_type and getattr(work_item_type, 'hierarchy_level', None) == 1:
        return False

    fields = work_item.get_edit_metadata() if hasattr(work_item, 'get_edit_metadata') else None
    if not fields:
        return False

    parent_field = fields.get('parent', {})
    if not parent_field:
        return False

    return 'set' in parent_field.get('operations', {})
