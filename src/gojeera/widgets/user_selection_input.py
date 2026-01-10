from typing import cast

from textual.reactive import Reactive, reactive
from textual.widgets import Select

from gojeera.widgets.vim_select import VimSelect


class UserSelectionInput(VimSelect):
    WIDGET_ID = 'jira-users-selector'
    users: Reactive[dict | None] = reactive(None, always_update=True)

    def __init__(self, users: list):
        super().__init__(
            options=users,
            prompt='Unassigned',
            name='users',
            id=self.WIDGET_ID,
            type_to_search=True,
            compact=True,
            classes='jira-selector',
        )

        self.jira_field_key = 'assignee'
        self._update_enabled = True

        self.original_value: str | None = None

    @property
    def help_anchor(self) -> str:
        return '#search-by-assignee'

    @property
    def update_enabled(self) -> bool:
        return self._update_enabled

    @update_enabled.setter
    def update_enabled(self, value: bool) -> None:
        self._update_enabled = value
        self.disabled = not value

    @property
    def selection(self) -> str | None:
        if self.value == Select.BLANK:
            return None

        return cast(str | None, self.value) if self.value else None

    @property
    def value_has_changed(self) -> bool:
        if not self.original_value:
            return bool(self.selection)

        if not self.selection:
            return True

        return self.original_value != self.selection

    def watch_users(self, users: dict | None = None) -> None:
        self.clear()
        if users and (items := users.get('users', []) or []):
            options = [(item.display_name, item.account_id) for item in items]
            self.set_options(options)
            if selection := users.get('selection'):
                for option in options:
                    if option[1] == selection:
                        self.value = option[1]
                        break
