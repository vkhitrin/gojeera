"""This module provides functions for dealing with Jira fields."""

from enum import Enum
from typing import Any


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
            if hasattr(self, 'add_class'):
                self.add_class('required')  # type: ignore[call-non-callable]

    @property
    def required(self) -> bool:
        return getattr(self, '_required', False)

    @required.setter
    def required(self, value: bool) -> None:
        self._required = value
        if hasattr(self, 'add_class') and hasattr(self, 'remove_class'):
            if value:
                self.add_class('required')  # type: ignore[call-non-callable]
            else:
                self.remove_class('required')  # type: ignore[call-non-callable]

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
