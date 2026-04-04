"""This module provides functions for dealing with Jira fields."""

from enum import Enum
from typing import Any

from gojeera.constants import CustomFieldType
from gojeera.utils.mappings import get_nested


class FieldMode(Enum):
    """Enum to distinguish between field creation and update contexts."""

    CREATE = 'create'
    UPDATE = 'update'


class BaseField:
    def setup_base_field(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        compact: bool = True,
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
