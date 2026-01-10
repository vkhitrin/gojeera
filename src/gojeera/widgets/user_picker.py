import logging

from textual.reactive import Reactive, reactive

from gojeera.utils.fields import BaseField, BaseUpdateField, FieldMode
from gojeera.widgets.vim_select import VimSelect

logger = logging.getLogger(__name__)


class UserPicker(VimSelect, BaseField, BaseUpdateField):
    """
    User picker widget.
    """

    users: Reactive[dict | None] = reactive(None, always_update=True)

    update_enabled: Reactive[bool] = reactive(True)

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
            prompt='Unassigned',
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

            self.update_enabled = field_supports_update

    def watch_update_enabled(self, enabled: bool) -> None:
        self.disabled = not enabled

    def watch_users(self, users: dict | None = None) -> None:
        if self.mode != FieldMode.CREATE:
            return

        self.clear()
        if users and (items := users.get('users', []) or []):
            options = [(item.display_name, item.account_id) for item in items]
            self.set_options(options)
            if selection := users.get('selection'):
                for option in options:
                    if option[1] == selection:
                        self.value = option[1]
                        break

    def get_value_for_update(self) -> dict | None:
        from textual.widgets import Select

        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        if self.value is Select.BLANK or not self.value:
            return None

        value_str = str(self.value).strip()
        if value_str and value_str != 'Select.BLANK':
            return {'accountId': value_str}
        return None

    @property
    def value_has_changed(self) -> bool:
        from textual.widgets import Select

        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

        current_value = None
        if self.value is not Select.BLANK and self.value:
            value_str = str(self.value).strip()

            if value_str and value_str != 'Select.BLANK':
                current_value = value_str

        original_value = self.original_value

        if not original_value:
            return bool(current_value)

        if not current_value:
            return True

        return original_value != current_value
