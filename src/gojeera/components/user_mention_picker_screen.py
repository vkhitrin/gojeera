from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Select, Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraUser
from gojeera.widgets.extended_jumper import ExtendedJumper
from gojeera.widgets.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.vim_select import VimSelect


class UserMentionSelector(VimSelect):
    """Custom VimSelect for user mention selection."""

    def __init__(self, items: list[tuple[str, tuple[str, str]]]):
        super().__init__(
            options=items,
            prompt='Select user...',
            name='user_mention_select',
            type_to_search=True,
            compact=True,
        )
        self.valid_empty = False


class UserMentionPickerScreen(ModalScreen[tuple[str, str] | None]):
    """Modal screen for selecting a user to mention.

    Args:
        base_url: The Jira instance base URL for generating mention links
        users: Optional list of users to display initially
    """

    BINDINGS = [
        ('escape', 'app.pop_screen', 'Close'),
        ('ctrl+c', 'app.pop_screen', 'Close'),
        ('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(
        self,
        base_url: str,
        users: list[JiraUser] | None = None,
    ):
        super().__init__()
        self.base_url = base_url
        self._all_users = users or []
        self._modal_title = 'Insert User Mention'

    @property
    def user_select(self) -> UserMentionSelector:
        return self.query_one(UserMentionSelector)

    @property
    def insert_button(self) -> Button:
        return self.query_one('#user-mention-button-insert', Button)

    def compose(self) -> ComposeResult:
        if CONFIGURATION.get().jumper.enabled:
            yield ExtendedJumper(keys=CONFIGURATION.get().jumper.keys)

        with VerticalSuppressClicks(id='modal_outer'):
            yield Static(self._modal_title, id='modal_title')
            with VerticalScroll(id='user-mention-form'):
                with Vertical():
                    yield Label('User').add_class('field_label')

                    options = [
                        (self._format_user_display(user), (user.account_id, user.display_name))
                        for user in self._all_users
                    ]
                    yield UserMentionSelector(options)

            with Horizontal(id='modal_footer'):
                yield Button(
                    'Insert',
                    variant='success',
                    id='user-mention-button-insert',
                    disabled=True,
                    compact=True,
                )
                yield Button('Cancel', variant='error', id='user-mention-button-quit', compact=True)

        yield Footer(show_command_palette=False)

    def _format_user_display(self, user: JiraUser) -> str:
        """Format user for display in select dropdown.

        Args:
            user: JiraUser object

        Returns:
            Formatted display string
        """
        if user.email:
            return f'{user.display_name} ({user.email})'
        return user.display_name

    def on_mount(self) -> None:
        if CONFIGURATION.get().jumper.enabled:
            self.user_select.jump_mode = 'focus'  # type: ignore[attr-defined]
            self.insert_button.jump_mode = 'click'  # type: ignore[attr-defined]
            self.query_one('#user-mention-button-quit', Button).jump_mode = 'click'  # type: ignore[attr-defined]

    async def action_show_overlay(self) -> None:
        if not CONFIGURATION.get().jumper.enabled:
            return
        jumper = self.query_one(ExtendedJumper)
        jumper.show()

    @on(Select.Changed, 'UserMentionSelector')
    def handle_user_selected(self) -> None:
        if self.user_select.selection:
            self.insert_button.disabled = False
        else:
            self.insert_button.disabled = True

    @on(Button.Pressed, '#user-mention-button-insert')
    def handle_insert(self) -> None:
        selected_value = self.user_select.value
        if selected_value and isinstance(selected_value, tuple):
            result: tuple[str, str] = selected_value  # type: ignore[invalid-assignment]
            self.dismiss(result)
        else:
            self.dismiss(None)

    @on(Button.Pressed, '#user-mention-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self) -> None:
        self.dismiss(None)
