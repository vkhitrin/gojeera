from textual.reactive import Reactive, reactive
from textual.widgets import Select

from gojeera.utils.fields import BaseField, BaseUpdateField, FieldMode
from gojeera.widgets.lazy_select import LazySelect


class SprintPicker(LazySelect, BaseField, BaseUpdateField):
    """Sprint picker widget with lazy loading and spinner support."""

    sprints: Reactive[dict | None] = reactive(None, always_update=True)

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: str | None = None,
        field_supports_update: bool = True,
    ):
        super().__init__(
            options=[],
            prompt='No sprint',
            id=field_id,
            type_to_search=True,
            compact=True,
            allow_blank=True,
        )

        self.setup_base_field(
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            compact=True,
        )

        if mode == FieldMode.UPDATE:
            self.setup_update_field(
                jira_field_key=field_id,
                original_value=original_value,
                field_supports_update=field_supports_update,
            )
            self.add_class('work_item_details_input_field')

            self.pending_value = original_value

        self._start_loading_on_mount = False

    def on_mount(self) -> None:
        if self._start_loading_on_mount:
            self._start_spinner()

    def start_loading(self) -> None:
        """Start the spinner. Safe to call before or after mount."""
        self._is_loading = True
        if self.is_mounted:
            self._start_spinner()
        else:
            self._start_loading_on_mount = True

    def watch_sprints(self, sprints: dict | None = None) -> None:
        if sprints is None:
            return
        self.clear()
        if items := sprints.get('sprints', []) or []:
            options = [(name, str(sprint_id)) for name, sprint_id in items]
            self._stop_spinner()
            self.set_options(options)
            if selection := sprints.get('selection'):
                for option in options:
                    if option[1] == str(selection):
                        self.value = option[1]
                        break
        else:
            self._stop_spinner()

    def get_value_for_update(self) -> int | None:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        if self.value is Select.NULL or not self.value:
            return None

        value_str = str(self.value).strip()
        if value_str and value_str != 'Select.NULL':
            return int(value_str)
        return None

    def get_value_for_create(self) -> int | None:
        if self.mode != FieldMode.CREATE:
            raise ValueError('get_value_for_create() only valid in CREATE mode')

        if self.value is Select.NULL or not self.value:
            return None

        value_str = str(self.value).strip()
        if value_str and value_str != 'Select.NULL':
            return int(value_str)
        return None

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

        if self._is_loading:
            return False

        current_value = None
        if self.value is not Select.NULL and self.value:
            value_str = str(self.value).strip()

            if value_str and value_str != 'Select.NULL':
                current_value = value_str

        original_value = self.original_value

        if not original_value:
            return bool(current_value)

        if not current_value:
            return True

        return original_value != current_value
