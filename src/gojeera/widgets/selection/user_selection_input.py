from textual.reactive import Reactive, reactive

from gojeera.utils.data.fields import optional_selection_value_has_changed
from gojeera.widgets.selection.vim_select import VimSelect


class UserSelectionInput(VimSelect):
    DEFAULT_CSS = """
    UserSelectionInput {
        width: 100%;
    }
    """

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
    def value_has_changed(self) -> bool:
        return optional_selection_value_has_changed(
            original_value=self.original_value,
            current_value=self.selection,
        )

    def watch_users(self, users: dict | None = None) -> None:
        if users and (items := users.get('users', []) or []):
            options = [(item.display_name, item.account_id) for item in items]
            self.replace_options(options, selection=users.get('selection'))
