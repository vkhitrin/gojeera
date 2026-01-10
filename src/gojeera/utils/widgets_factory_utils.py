import logging
from typing import Any, Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widget import Widget
from textual.widgets import Label, Select

from gojeera.constants import LOGGER_NAME, CustomFieldType
from gojeera.utils.fields import FieldMode
from gojeera.widgets.adf_textarea import ADFTextAreaWidget
from gojeera.widgets.date_input import DateInput
from gojeera.widgets.date_time_input import DateTimeInput
from gojeera.widgets.multi_select import MultiSelect
from gojeera.widgets.numeric_input import NumericInput
from gojeera.widgets.selection import SelectionWidget
from gojeera.widgets.text_input import TextInput
from gojeera.widgets.url import URL
from gojeera.widgets.user_picker import UserPicker
from gojeera.widgets.work_item_labels import WorkItemLabels

logger = logging.getLogger(LOGGER_NAME)


class StaticFieldsWidgets(VerticalGroup):
    DEFAULT_CSS = """
    StaticFieldsWidgets {
        layout: vertical;
    }

    StaticFieldsWidgets > * {
        height: auto;
        width: 100%;
    }

    StaticFieldsWidgets > Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }
    
    StaticFieldsWidgets > Horizontal > Label {
        width: 20%;
        min-width: 15;
        max-width: 30;
        padding-right: 2;
        text-style: bold;
    }
    
    StaticFieldsWidgets > Horizontal > Label.pending_field_label {
        color: $warning;
    }
    
    StaticFieldsWidgets > Horizontal > WorkItemStatusSelectionInput,
    StaticFieldsWidgets > Horizontal > ReadOnlyInputField,
    StaticFieldsWidgets > Horizontal > SelectionWidget,
    StaticFieldsWidgets > Horizontal > UserSelectionInput,
    StaticFieldsWidgets > Horizontal > WorkItemLabels,
    StaticFieldsWidgets > Horizontal > MultiSelect,
    StaticFieldsWidgets > Horizontal > NumericInput {
        width: 1fr;
    }
    """


class DynamicFieldsWidgets(VerticalGroup):
    """Container for dynamically generated field widgets."""

    DEFAULT_CSS = """
    DynamicFieldsWidgets {
        layout: vertical;
    }

    DynamicFieldsWidgets > * {
        height: auto;
        width: 100%;
    }

    DynamicFieldsWidgets > Horizontal {
        width: 100%;
        height: auto;
    }
    """


class DynamicFieldWrapper(Horizontal):
    """
    Wrapper for dynamic field widgets that provides a horizontal layout with label.
    """

    DEFAULT_CSS = """
    DynamicFieldWrapper {
        width: 100%;
        height: auto;
        align: center middle;
    }
    
    DynamicFieldWrapper > Label {
        width: 20%;
        min-width: 15;
        max-width: 30;
        padding-right: 2;
        text-style: bold;
    }
    
    DynamicFieldWrapper > Label.pending_field_label {
        color: $warning;
    }
    
    DynamicFieldWrapper > NumericInput,
    DynamicFieldWrapper > DateInput,
    DynamicFieldWrapper > DateTimeInput,
    DynamicFieldWrapper > SelectionWidget,
    DynamicFieldWrapper > URL,
    DynamicFieldWrapper > MultiSelect,
    DynamicFieldWrapper > TextInput,
    DynamicFieldWrapper > WorkItemLabels,
    DynamicFieldWrapper > UserPicker,
    DynamicFieldWrapper > ADFTextAreaWidget {
        width: 1fr;
    }
    """

    def __init__(
        self,
        widget_factory: Callable[[], Widget],
        title: str,
        required: bool = False,
        widget_class: type[Widget] | None = None,
    ):
        super().__init__()
        self._widget_factory = widget_factory
        self._widget: Widget | None = None
        self._title = title
        self._required = required
        self._widget_class = widget_class

    def compose(self) -> ComposeResult:
        label = Label(self._title).add_class('field_label')

        yield label

        self._widget = self._widget_factory()
        yield self._widget

    @property
    def widget(self) -> Widget | None:
        return self._widget

    @property
    def widget_class(self) -> type[Widget] | None:
        return self._widget_class

    @property
    def required(self) -> bool:
        return self._required

    @property
    def jira_field_key(self) -> str:
        if self._widget:
            return getattr(self._widget, 'jira_field_key', '')
        return ''

    @property
    def value_has_changed(self) -> bool:
        if self._widget:
            return getattr(self._widget, 'value_has_changed', False)
        return False

    def update_label_styling(self) -> None:
        try:
            from textual.widgets import Label

            label = self.query_one(Label)

            widget_enabled = getattr(self._widget, 'update_enabled', True)
            has_changed = self.value_has_changed

            if widget_enabled and has_changed:
                label.add_class('pending_field_label')
            else:
                label.remove_class('pending_field_label')
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    def get_value_for_update(self):
        if self._widget:
            try:
                method = getattr(self._widget, 'get_value_for_update', None)
                if callable(method):
                    return method()
            except AttributeError:
                pass
        return None

    def get_value_for_create(self):
        if self._widget:
            try:
                method = getattr(self._widget, 'get_value_for_create', None)
                if callable(method):
                    return method()
            except AttributeError:
                pass
        return None


class FieldMetadata:
    """
    Parsed field metadata from Jira metadata.
    """

    def __init__(self, raw_metadata: dict):
        """
        Initialize from raw Jira field metadata.

        Args:
            raw_metadata: Dictionary from Jira's create or edit metadata
        """
        self.raw = raw_metadata
        self.field_id: str = raw_metadata.get('fieldId', '')
        self.name: str = raw_metadata.get('name', '')
        self.key: str = raw_metadata.get('key', '')
        self.required: bool = raw_metadata.get('required', False)
        self.schema: dict = raw_metadata.get('schema', {})
        self.custom_type: str | None = self.schema.get('custom')
        self.schema_type: str = self.schema.get('type', '')
        self.allowed_values: list[dict] = raw_metadata.get('allowedValues', [])
        self.has_default: bool = raw_metadata.get('hasDefaultValue', False)
        self.default_value: dict | None = raw_metadata.get('defaultValue')
        self.operations: list[str] = raw_metadata.get('operations', [])

    @property
    def supports_update(self) -> bool:
        return any(op in self.operations for op in ['set', 'add', 'edit', 'remove'])

    @property
    def is_custom_field(self) -> bool:
        return self.custom_type is not None

    def __repr__(self) -> str:
        return f'FieldMetadata(field_id={self.field_id!r}, name={self.name!r}, custom_type={self.custom_type!r})'


class AllowedValuesParser:
    """
    Parses Jira allowedValues into Select widget options.
    """

    @staticmethod
    def parse_options(allowed_values: list[dict]) -> list[tuple[str, str]]:
        """
        Parse allowedValues into Select-compatible options.

        Args:
            allowed_values: List of value dictionaries from Jira metadata

        Returns:
            List of (display_name, id) tuples for Select widget
        """
        options: list[tuple[str, str]] = []

        if not allowed_values:
            return options
        for value in allowed_values:
            if 'languageCode' in value and 'displayName' in value:
                display_value = value.get('displayName', '')
                value_id = value.get('languageCode', '')
            else:
                display_value = value.get('name') or value.get('value', '')
                value_id = value.get('id', '')
            if display_value and value_id:
                options.append((display_value, value_id))
        return options


class WidgetBuilder:
    """
    Factory methods for creating mode-aware widgets.
    """

    @staticmethod
    def build_user_picker(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: Any = None,
    ) -> Widget:
        def create_widget():
            if mode == FieldMode.CREATE:
                return UserPicker(
                    mode=mode,
                    field_id=metadata.field_id,
                    title=metadata.name,
                    required=metadata.required,
                )
            else:
                account_id = None
                if current_value:
                    if isinstance(current_value, dict):
                        account_id = current_value.get('accountId')
                    elif isinstance(current_value, str):
                        account_id = (
                            current_value.split(':', 1)[1]
                            if ':' in current_value
                            else current_value
                        )

                return UserPicker(
                    mode=mode,
                    field_id=metadata.field_id,
                    title=metadata.name,
                    original_value=account_id,
                    field_supports_update=metadata.supports_update,
                )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_numeric(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: float | None = None,
    ) -> Widget:
        def create_widget():
            return NumericInput(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value,
                field_supports_update=metadata.supports_update,
            )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_selection(
        mode: FieldMode,
        metadata: FieldMetadata,
        options: list[tuple[str, str]],
        initial_value: Any = Select.BLANK,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            if mode == FieldMode.CREATE:
                allow_blank = True
                init_val = initial_value
                if metadata.has_default and metadata.default_value:
                    allow_blank = False
                    init_val = metadata.default_value.get('id', Select.BLANK)

                return SelectionWidget(
                    mode=mode,
                    field_id=metadata.field_id,
                    options=options,
                    title=metadata.name,
                    required=metadata.required,
                    initial_value=init_val,
                    allow_blank=allow_blank or (init_val == Select.BLANK),
                    prompt='',
                )
            else:
                value_id = None
                if current_value:
                    if isinstance(current_value, dict):
                        value_id = current_value.get('id')
                    elif isinstance(current_value, str):
                        value_id = current_value

                return SelectionWidget(
                    mode=mode,
                    field_id=metadata.field_id,
                    options=options,
                    title=metadata.name,
                    original_value=value_id,
                    field_supports_update=metadata.supports_update,
                    allow_blank=not metadata.required,
                    prompt='',
                )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_date(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            widget = DateInput(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value if mode == FieldMode.UPDATE else None,
                field_supports_update=metadata.supports_update
                if mode == FieldMode.UPDATE
                else True,
            )

            if mode == FieldMode.UPDATE and metadata.required:
                widget.valid_empty = False

            return widget

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_datetime(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            widget = DateTimeInput(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value if mode == FieldMode.UPDATE else None,
                field_supports_update=metadata.supports_update
                if mode == FieldMode.UPDATE
                else True,
            )

            if mode == FieldMode.UPDATE and metadata.required:
                widget.valid_empty = False

            return widget

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_text(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: Any = None,
    ) -> Widget:
        def create_widget():
            if mode == FieldMode.CREATE:
                return TextInput(
                    mode=mode,
                    field_id=metadata.field_id,
                    title=metadata.name,
                    required=metadata.required,
                )
            else:
                # Ensure current_value is a string, convert or default to empty string
                if isinstance(current_value, str):
                    value = current_value
                elif current_value is None:
                    value = ''
                else:
                    # If it's not a string or None (e.g., dict, list), convert to string
                    value = str(current_value) if current_value else ''

                return TextInput(
                    mode=mode,
                    field_id=metadata.field_id,
                    title=metadata.name,
                    original_value=value,
                    field_supports_update=metadata.supports_update,
                )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_url(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            return URL(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value if mode == FieldMode.UPDATE else None,
                field_supports_update=metadata.supports_update
                if mode == FieldMode.UPDATE
                else True,
            )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_labels(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: list[str] | None = None,
    ) -> Widget:
        def create_widget():
            return WorkItemLabels(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value or [],
                supports_update=metadata.supports_update,
            )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_multicheckboxes(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: list[dict] | None = None,
    ) -> Widget:
        def create_widget():
            current_ids = []
            if mode == FieldMode.UPDATE and current_value:
                for item in current_value:
                    if isinstance(item, dict) and 'id' in item:
                        current_ids.append(str(item['id']))
                    elif hasattr(item, 'id'):
                        current_ids.append(str(item.id))

            options = AllowedValuesParser.parse_options(metadata.allowed_values or [])

            return MultiSelect(
                mode=mode,
                field_id=metadata.field_id,
                options=options,
                title=metadata.name,
                required=metadata.required,
                initial_value=current_ids if mode == FieldMode.CREATE else [],
                original_value=current_ids if mode == FieldMode.UPDATE else [],
                field_supports_update=metadata.supports_update
                if mode == FieldMode.UPDATE
                else True,
            )

        return DynamicFieldWrapper(create_widget, metadata.name, metadata.required)

    @staticmethod
    def build_adf_textarea(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: dict | str | None = None,
    ) -> Widget:
        def create_widget():
            return ADFTextAreaWidget(
                mode=mode,
                field_id=metadata.field_id,
                title=metadata.name,
                required=metadata.required,
                original_value=current_value,
                field_supports_update=False,
            )

        return DynamicFieldWrapper(
            create_widget, metadata.name, metadata.required, widget_class=ADFTextAreaWidget
        )


def map_field_to_widget(
    mode: FieldMode,
    metadata: FieldMetadata,
    current_value: Any = None,
) -> Widget | None:
    builder = WidgetBuilder()

    if metadata.is_custom_field:
        custom_type = metadata.custom_type

        if custom_type == CustomFieldType.USER_PICKER.value:
            return builder.build_user_picker(mode, metadata, current_value)

        elif custom_type == CustomFieldType.FLOAT.value:
            return builder.build_numeric(mode, metadata, current_value)

        elif custom_type == CustomFieldType.SELECT.value:
            if metadata.allowed_values:
                options = AllowedValuesParser.parse_options(metadata.allowed_values)
                return builder.build_selection(mode, metadata, options, current_value=current_value)

        elif custom_type == CustomFieldType.DATE_PICKER.value:
            return builder.build_date(mode, metadata, current_value)

        elif custom_type == CustomFieldType.DATETIME.value:
            return builder.build_datetime(mode, metadata, current_value)

        elif custom_type == CustomFieldType.TEXT_FIELD.value:
            return builder.build_text(mode, metadata, current_value)

        elif custom_type == CustomFieldType.URL.value:
            return builder.build_url(mode, metadata, current_value)

        elif custom_type == CustomFieldType.LABELS.value:
            return builder.build_labels(mode, metadata, current_value)

        elif custom_type == CustomFieldType.MULTI_CHECKBOXES.value:
            return builder.build_multicheckboxes(mode, metadata, current_value)

        elif custom_type == CustomFieldType.MULTI_SELECT.value:
            return builder.build_multicheckboxes(mode, metadata, current_value)

        elif custom_type == CustomFieldType.SD_REQUEST_LANGUAGE.value:
            if metadata.allowed_values:
                options = AllowedValuesParser.parse_options(metadata.allowed_values)
                return builder.build_selection(mode, metadata, options, current_value=current_value)

        elif custom_type == CustomFieldType.TEXTAREA.value:
            if mode == FieldMode.UPDATE:
                return builder.build_adf_textarea(mode, metadata, current_value)
            else:
                return None

        logger.warning(f'Unsupported custom field type: {custom_type} for {metadata.name}')

    else:
        schema_type = metadata.schema_type.lower()

        if schema_type == 'number':
            return builder.build_numeric(mode, metadata, current_value)

        elif schema_type == 'date':
            return builder.build_date(mode, metadata, current_value)

        elif (
            mode == FieldMode.CREATE
            and schema_type == 'array'
            and metadata.schema.get('items') == 'string'
            and metadata.field_id == 'labels'
        ):
            return builder.build_labels(mode, metadata, None)

        elif (
            schema_type == 'array'
            and metadata.allowed_values
            and (
                metadata.field_id in ('components', 'versions', 'fixVersions')
                or metadata.key in ('components', 'versions', 'fixVersions')
            )
        ):
            return builder.build_multicheckboxes(mode, metadata, current_value)

        elif metadata.allowed_values:
            options = AllowedValuesParser.parse_options(metadata.allowed_values)
            return builder.build_selection(mode, metadata, options, current_value=current_value)

        # Check if the current_value is an ADF document (dict with 'type': 'doc')
        # This handles fields like 'description' that contain ADF content
        elif (
            mode == FieldMode.UPDATE
            and isinstance(current_value, dict)
            and current_value.get('type') == 'doc'
        ):
            return builder.build_adf_textarea(mode, metadata, current_value)

    return builder.build_text(mode, metadata, current_value)


def build_dynamic_widgets(
    mode: FieldMode,
    fields_data: list[dict],
    current_values: dict[str, Any] | None = None,
    skip_fields: set[str] | None = None,
    enable_additional: bool = True,
    process_optional_fields: set[str] | None = None,
) -> list[Widget]:
    widgets: list[Widget] = []
    skip_fields = skip_fields or set()
    process_optional_fields = process_optional_fields or set()
    current_values = current_values or {}

    for field_data in fields_data:
        field_id = field_data.get('fieldId', '')
        field_key = field_data.get('key', '')
        field_name = field_data.get('name', '')
        required = field_data.get('required', False)

        field_identifiers = {field_id.lower(), field_key.lower(), field_name.lower()}
        skip_fields_lower = {f.lower() for f in skip_fields}

        if any(fid in skip_fields_lower for fid in field_identifiers if fid):
            continue

        if mode == FieldMode.CREATE and not required:
            if field_id in skip_fields_lower:
                continue

            if not enable_additional and field_id not in process_optional_fields:
                continue

        metadata = FieldMetadata(field_data)
        if not metadata.field_id:
            metadata.field_id = field_id

        current_value = None
        if mode == FieldMode.UPDATE:
            current_value = current_values.get(field_id)

        widget = map_field_to_widget(mode, metadata, current_value)

        if widget:
            if field_id and field_id.startswith('customfield'):
                widget.tooltip = f'{field_name} (Tip: to ignore use id: {field_id})'
            widgets.append(widget)
        else:
            logger.warning(f'Failed to build widget for field: {field_name} ({field_id})')

    return widgets
