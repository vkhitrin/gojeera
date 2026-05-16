import logging
from typing import Any, Callable, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalGroup
from textual.widget import Widget
from textual.widgets import Label, Select

from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.data.fields import CustomFieldType, FieldMode
from gojeera.utils.data.mappings import get_nested
from gojeera.widgets.inputs.date_input import DateInput
from gojeera.widgets.inputs.date_time_input import DateTimeInput
from gojeera.widgets.inputs.numeric_input import NumericInput
from gojeera.widgets.inputs.text_input import TextInput
from gojeera.widgets.inputs.url import URL
from gojeera.widgets.markdown.adf_textarea import ADFTextAreaWidget
from gojeera.widgets.selection.multi_select import MultiSelect, extract_sprint_ids
from gojeera.widgets.selection.selection import SelectionWidget
from gojeera.widgets.selection.user_picker import UserPicker
from gojeera.widgets.work_item.work_item_labels import WorkItemLabels

logger = logging.getLogger('gojeera')


def apply_field_control_classes(widget: Widget) -> Widget:
    if not widget.has_class('field_control'):
        widget.add_class('field_control')
    if widget.styles.width != '1fr':
        widget.styles.width = '1fr'

    if isinstance(widget, (TextInput, NumericInput, URL, DateInput, DateTimeInput)):
        if not widget.has_class('field-control-input'):
            widget.add_class('field-control-input')
    elif isinstance(widget, (Select, SelectionWidget, UserPicker)):
        if not widget.has_class('field-control-select'):
            widget.add_class('field-control-select')
    elif isinstance(widget, (MultiSelect, WorkItemLabels)):
        if not widget.has_class('field-control-tags'):
            widget.add_class('field-control-tags')

    return widget


class StaticFieldsWidgets(VerticalGroup):
    DEFAULT_CSS = """
    StaticFieldsWidgets {
        layout: vertical;
        margin: 0 1 0 0;
        padding: 0;
        height: auto;
    }

    StaticFieldsWidgets > * {
        height: auto;
        width: 100%;
    }

    StaticFieldsWidgets > .field-row-slot > Horizontal {
        width: 100%;
        height: auto;
        align: center middle;
    }
    
    StaticFieldsWidgets > .field-row-slot > Horizontal > Label.pending_field_label {
        color: $warning;
    }
    """


class DynamicFieldsWidgets(VerticalGroup):
    """Container for dynamically generated field widgets."""

    DEFAULT_CSS = """
    DynamicFieldsWidgets {
        layout: stream;
        margin: 0 1 0 0;
        padding: 0;
        height: auto;
    }

    DynamicFieldsWidgets > * {
        height: auto;
        width: 100%;
    }

    DynamicFieldsWidgets > DynamicFieldWrapper,
    DynamicFieldsWidgets > .dynamic-field-container {
        width: 100%;
        height: auto;
    }

    DynamicFieldsWidgets > .dynamic-row-spaced {
        margin-top: 1;
    }

    DynamicFieldsWidgets > .field-row-slot > Horizontal {
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
    
    DynamicFieldWrapper > Label.pending_field_label {
        color: $warning;
    }
    """

    def __init__(
        self,
        widget_factory: Callable[[], Widget],
        title: str,
        required: bool = False,
        widget_class: type[Widget] | None = None,
        tooltip: str | None = None,
    ):
        super().__init__()
        self._widget_factory = widget_factory
        self._widget: Widget | None = None
        self._label: Label | None = None
        self._title = title
        self._required = required
        self._widget_class = widget_class
        self.tooltip = tooltip

    def materialize(self) -> None:
        if self._label is None:
            label = Label(self._title)
            label.add_class('field_label')
            label.tooltip = self.tooltip
            self._label = label

        if self._widget is None:
            self._widget = self._widget_factory()
            apply_field_control_classes(self._widget)
            self._widget.tooltip = self.tooltip

    def compose(self) -> ComposeResult:
        self.materialize()
        if self._label is not None:
            yield self._label
        if self._widget is not None:
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
        if self._widget is not None:
            return str(getattr(self._widget, 'jira_field_key', ''))
        return ''

    @property
    def update_enabled(self) -> bool:
        if self._widget is not None and hasattr(self._widget, 'update_enabled'):
            return bool(self._widget.update_enabled)
        return True

    @property
    def value_has_changed(self) -> bool:
        if self._widget:
            return getattr(self._widget, 'value_has_changed', False)
        return False

    def update_label_styling(self) -> None:
        try:
            from textual.widgets import Label

            label = self.query_one(Label)

            widget_enabled = self.update_enabled
            has_changed = self.value_has_changed

            if widget_enabled and has_changed:
                label.add_class('pending_field_label')
            else:
                label.remove_class('pending_field_label')
        except Exception:
            pass

    def update_metadata(
        self,
        *,
        title: str,
        required: bool,
        tooltip: str | None,
    ) -> None:
        self._title = title
        self._required = required
        self.tooltip = tooltip

        if self._label is not None:
            self._label.update(title)
            self._label.tooltip = tooltip

        if self._widget is not None:
            self._widget.tooltip = tooltip
            if hasattr(self._widget, 'label_text'):
                cast(Any, self._widget).label_text = title
            if hasattr(self._widget, 'title'):
                cast(Any, self._widget).title = title
            if hasattr(self._widget, 'required'):
                try:
                    cast(Any, self._widget).required = required
                except Exception:
                    pass

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
        self.description: str | None = raw_metadata.get('description')
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


def build_field_tooltip(field_metadata: dict[str, Any] | FieldMetadata) -> str | None:
    """Build tooltip text from Jira field metadata."""

    if isinstance(field_metadata, FieldMetadata):
        field_id = field_metadata.field_id
        description = field_metadata.description
        is_custom_field = field_metadata.is_custom_field
    else:
        field_id = str(field_metadata.get('fieldId') or field_metadata.get('id') or '')
        description = field_metadata.get('description')
        is_custom_field = field_id.startswith('customfield_') or bool(
            get_nested(field_metadata, 'schema', 'custom')
        )

    parts: list[str] = []
    if isinstance(description, str):
        normalized_description = description.strip()
        if normalized_description:
            parts.append(normalized_description)

    if is_custom_field and field_id:
        parts.append(f'({field_id})')

    return '\n\n'.join(parts) if parts else None


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
    def _build_basic_create_widget(
        widget_cls: type[TextInput] | type[UserPicker],
        mode: FieldMode,
        metadata: FieldMetadata,
    ) -> TextInput | UserPicker:
        return widget_cls(
            mode=mode,
            field_id=metadata.field_id,
            title=metadata.name,
            required=metadata.required,
        )

    @staticmethod
    def _build_mode_widget(
        mode: FieldMode,
        *,
        create_factory: Callable[[], Widget],
        update_factory: Callable[[], Widget],
    ) -> Widget:
        if mode == FieldMode.CREATE:
            return create_factory()
        return update_factory()

    @staticmethod
    def _field_kwargs(
        metadata: FieldMetadata,
        *,
        mode: FieldMode,
        required: bool | None = None,
        original_value: Any = None,
    ) -> dict[str, Any]:
        return {
            'mode': mode,
            'field_id': metadata.field_id,
            'title': metadata.name,
            'required': metadata.required if required is None else required,
            'original_value': original_value,
            'field_supports_update': metadata.supports_update if mode == FieldMode.UPDATE else True,
        }

    @staticmethod
    def _normalize_update_string_value(current_value: Any) -> str:
        if isinstance(current_value, str):
            return current_value
        if current_value is None:
            return ''
        return str(current_value) if current_value else ''

    @staticmethod
    def _extract_update_identifier(current_value: Any, *, key: str = 'id') -> str | None:
        if not current_value:
            return None
        if isinstance(current_value, dict):
            return current_value.get(key)
        if isinstance(current_value, str):
            return current_value
        return None

    @staticmethod
    def _extract_user_account_id(current_value: Any) -> str | None:
        if not current_value:
            return None
        if isinstance(current_value, dict):
            return current_value.get('accountId')
        if isinstance(current_value, str):
            return current_value.split(':', 1)[1] if ':' in current_value else current_value
        return None

    @staticmethod
    def _selection_allows_blank(metadata: FieldMetadata, initial_value: Any) -> bool:
        if metadata.field_id == 'priority' or metadata.schema_type.lower() == 'priority':
            return False
        return initial_value == Select.NULL or not metadata.required

    @staticmethod
    def _multi_select_for_mode(
        mode: FieldMode,
        metadata: FieldMetadata,
        *,
        options: list[tuple[str, str]],
        initial_value: list[str] | None = None,
        original_value: list[str] | None = None,
    ) -> MultiSelect:
        return MultiSelect(
            mode=mode,
            field_id=metadata.field_id,
            options=options,
            title=metadata.name,
            required=metadata.required,
            initial_value=initial_value if mode == FieldMode.CREATE else [],
            original_value=original_value if mode == FieldMode.UPDATE else [],
            field_supports_update=metadata.supports_update if mode == FieldMode.UPDATE else True,
        )

    @staticmethod
    def _wrap_dynamic_field(
        widget_factory: Callable[[], Widget],
        metadata: FieldMetadata,
        *,
        widget_class: type[Widget] | None = None,
    ) -> Widget:
        return DynamicFieldWrapper(
            widget_factory,
            metadata.name,
            metadata.required,
            widget_class=widget_class,
            tooltip=build_field_tooltip(metadata),
        )

    @staticmethod
    def _build_temporal_input(
        widget_cls: type[DateInput] | type[DateTimeInput],
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            widget = widget_cls(
                **WidgetBuilder._field_kwargs(
                    metadata,
                    mode=mode,
                    original_value=current_value if mode == FieldMode.UPDATE else None,
                )
            )

            if mode == FieldMode.UPDATE and metadata.required:
                widget.valid_empty = False

            return widget

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_user_picker(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: Any = None,
    ) -> Widget:
        def create_widget():
            return WidgetBuilder._build_mode_widget(
                mode,
                create_factory=lambda: WidgetBuilder._build_basic_create_widget(
                    UserPicker, mode, metadata
                ),
                update_factory=lambda: UserPicker(
                    **WidgetBuilder._field_kwargs(
                        metadata,
                        mode=mode,
                        original_value=WidgetBuilder._extract_user_account_id(current_value),
                    )
                ),
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_numeric(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: float | None = None,
    ) -> Widget:
        def create_widget():
            return NumericInput(
                **WidgetBuilder._field_kwargs(metadata, mode=mode, original_value=current_value)
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_selection(
        mode: FieldMode,
        metadata: FieldMetadata,
        options: list[tuple[str, str]],
        initial_value: Any = Select.NULL,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            allow_blank = True
            init_val = initial_value
            if metadata.has_default and metadata.default_value:
                allow_blank = False
                init_val = metadata.default_value.get('id', Select.NULL)

            return WidgetBuilder._build_mode_widget(
                mode,
                create_factory=lambda: SelectionWidget(
                    mode=mode,
                    field_id=metadata.field_id,
                    options=options,
                    title=metadata.name,
                    required=metadata.required,
                    initial_value=init_val,
                    allow_blank=allow_blank
                    and WidgetBuilder._selection_allows_blank(metadata, init_val),
                    prompt='',
                ),
                update_factory=lambda: SelectionWidget(
                    mode=mode,
                    field_id=metadata.field_id,
                    options=options,
                    title=metadata.name,
                    original_value=WidgetBuilder._extract_update_identifier(current_value),
                    field_supports_update=metadata.supports_update,
                    allow_blank=not metadata.required,
                    prompt='',
                ),
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_date(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        return WidgetBuilder._build_temporal_input(
            DateInput,
            mode,
            metadata,
            current_value,
        )

    @staticmethod
    def build_datetime(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        return WidgetBuilder._build_temporal_input(
            DateTimeInput,
            mode,
            metadata,
            current_value,
        )

    @staticmethod
    def build_text(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: Any = None,
    ) -> Widget:
        def create_widget():
            return WidgetBuilder._build_mode_widget(
                mode,
                create_factory=lambda: WidgetBuilder._build_basic_create_widget(
                    TextInput, mode, metadata
                ),
                update_factory=lambda: TextInput(
                    **WidgetBuilder._field_kwargs(
                        metadata,
                        mode=mode,
                        original_value=WidgetBuilder._normalize_update_string_value(current_value),
                    )
                ),
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_url(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: str | None = None,
    ) -> Widget:
        def create_widget():
            return URL(
                **WidgetBuilder._field_kwargs(
                    metadata,
                    mode=mode,
                    original_value=current_value if mode == FieldMode.UPDATE else None,
                )
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

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

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

    @staticmethod
    def build_multicheckboxes(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: list[Any] | None = None,
    ) -> Widget:
        def create_widget():
            current_ids = []
            if mode == FieldMode.UPDATE and current_value:
                for item in current_value:
                    if isinstance(item, dict) and 'id' in item:
                        current_ids.append(str(item['id']))

            options = AllowedValuesParser.parse_options(metadata.allowed_values or [])

            return WidgetBuilder._multi_select_for_mode(
                mode,
                metadata,
                options=options,
                initial_value=current_ids,
                original_value=current_ids,
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)

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

        return WidgetBuilder._wrap_dynamic_field(
            create_widget,
            metadata,
            widget_class=ADFTextAreaWidget,
        )

    @staticmethod
    def build_sprint_selection(
        mode: FieldMode,
        metadata: FieldMetadata,
        current_value: list[str] | None = None,
    ) -> Widget:
        """Build sprint selection widget with lazy loading.

        Args:
            mode: CREATE or UPDATE
            metadata: Field metadata from Jira
            current_value: Current sprint ID (int) for UPDATE mode

        Returns:
            DynamicFieldWrapper containing MultiSelect
        """

        def create_widget():
            return WidgetBuilder._multi_select_for_mode(
                mode,
                metadata,
                options=[],
                initial_value=current_value,
                original_value=current_value,
            )

        return WidgetBuilder._wrap_dynamic_field(create_widget, metadata)


def _field_data_summary(field_data: dict[str, Any]) -> tuple[str, str, str, bool]:
    return (
        field_data.get('fieldId', ''),
        field_data.get('key', ''),
        field_data.get('name', ''),
        field_data.get('required', False),
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

        elif custom_type == CustomFieldType.GH_EPIC_LINK.value:
            return builder.build_text(mode, metadata, current_value)

        elif custom_type == CustomFieldType.GH_SPRINT.value:
            # Check if sprint selection feature is enabled
            config = CONFIGURATION.get()
            if config.enable_sprint_selection:
                sprint_ids = extract_sprint_ids(current_value)

                return builder.build_sprint_selection(mode, metadata, sprint_ids or None)
            else:
                # Fallback to text input if feature disabled
                return builder.build_text(mode, metadata, current_value)

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

    skip_fields_lower = {f.lower() for f in skip_fields}

    for field_data in fields_data:
        field_id, field_key, field_name, required = _field_data_summary(field_data)

        field_identifiers = {
            str(field_id).lower(),
            str(field_key).lower(),
            str(field_name).lower(),
        }
        if any(fid in skip_fields_lower for fid in field_identifiers if fid):
            continue

        if mode == FieldMode.CREATE and not required:
            if str(field_id).lower() in skip_fields_lower:
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
            widget.tooltip = build_field_tooltip(metadata)
            widgets.append(widget)
        else:
            logger.warning(f'Failed to build widget for field: {field_name} ({field_id})')

    return widgets
