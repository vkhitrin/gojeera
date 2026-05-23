import logging

from textual.reactive import Reactive, reactive

from gojeera.utils.data.fields import (
    BaseField,
    BaseUpdateField,
    FieldMode,
    configure_select_field_for_mode,
    normalized_selection_value,
    optional_selection_value_has_changed,
    require_update_mode,
    selection_update_payload,
)
from gojeera.widgets.selection.user_selection_input import (
    UNASSIGNED_OPTION,
    UNASSIGNED_VALUE,
    UnassignedUserSelect,
)

logger = logging.getLogger(__name__)


class UserPicker(UnassignedUserSelect, BaseField, BaseUpdateField):
    """
    User picker widget.
    """

    DEFAULT_CSS = """
    UserPicker {
        width: 100%;
    }
    """

    users: Reactive[dict | None] = reactive(None, always_update=True)

    update_enabled: Reactive[bool] = reactive(True)
    pending_value: str | None = None
    pending_display_name: str | None = None

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: str | None = None,
        original_display_name: str | None = None,
        field_supports_update: bool = True,
    ):
        super().__init__(
            options=[UNASSIGNED_OPTION],
            prompt=original_display_name or 'Unassigned',
            id=field_id,
            type_to_search=True,
            compact=True,
            allow_blank=False,
            value=UNASSIGNED_VALUE,
        )

        def sync_update_state() -> None:
            self.pending_value = original_value
            self.pending_display_name = original_display_name
            self.update_enabled = field_supports_update

        configure_select_field_for_mode(
            self,
            mode=mode,
            field_id=field_id,
            title=title,
            required=required,
            field_supports_update=field_supports_update,
            original_value=original_value,
            on_update=sync_update_state if mode == FieldMode.UPDATE else None,
        )

    def watch_update_enabled(self, enabled: bool) -> None:
        self.disabled = not enabled

    def set_pending_user(self, account_id: str | None, display_name: str | None = None) -> None:
        self.pending_value = account_id
        self.pending_display_name = display_name

    def watch_users(self, users: dict | None = None) -> None:
        if self.mode != FieldMode.CREATE:
            return

        if users and (items := users.get('users', []) or []):
            options = [(item.display_name, item.account_id) for item in items]
            self.replace_options(options, selection=users.get('selection'))

    def get_value_for_update(self) -> dict | None:
        require_update_mode(self.mode, 'get_value_for_update()')
        return selection_update_payload(self.value, 'accountId')

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        return optional_selection_value_has_changed(
            original_value=self.original_value,
            current_value=normalized_selection_value(self.value),
        )
