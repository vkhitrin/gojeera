from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static

from gojeera.config import CONFIGURATION
from gojeera.models import JiraUser
from gojeera.utils.focus import focus_first_available
from gojeera.widgets.extended_footer import ExtendedFooter
from gojeera.widgets.extended_jumper import ExtendedJumper, set_jump_mode
from gojeera.widgets.extended_modal_screen import ExtendedModalScreen
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


class UserMentionPickerScreen(ExtendedModalScreen[tuple[str, str] | None]):
    """Modal screen for selecting a user to mention.

    Args:
        base_url: The Jira instance base URL for generating mention links
        users: Optional list of users to display initially
    """

    BINDINGS = ExtendedModalScreen.BINDINGS + [
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
            with VerticalScroll(id='user-mention-form', classes='modal-form modal-form--fields'):
                with Vertical():
                    user_label = Label('User')
                    user_label.add_class('field_label')
                    yield user_label

                    options = [
                        (self._format_user_display(user), (user.account_id, user.display_name))
                        for user in self._all_users
                    ]
                    yield UserMentionSelector(options)

            with Horizontal(id='modal_footer', classes='modal-footer-spaced'):
                yield Button(
                    'Insert',
                    variant='success',
                    id='user-mention-button-insert',
                    classes='modal-action-button modal-action-button--confirm',
                    disabled=True,
                    compact=True,
                )
                yield Button(
                    'Cancel',
                    variant='error',
                    id='user-mention-button-quit',
                    classes='modal-action-button modal-action-button--danger',
                    compact=True,
                )

        yield ExtendedFooter(show_command_palette=False)

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
            set_jump_mode(self.user_select, 'focus')
            set_jump_mode(self.insert_button, 'click')
            set_jump_mode(self.query_one('#user-mention-button-quit', Button), 'click')
        self.call_after_refresh(lambda: focus_first_available(self.user_select))

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
        if (
            selected_value
            and isinstance(selected_value, tuple)
            and len(selected_value) == 2
            and all(isinstance(value, str) for value in selected_value)
        ):
            account_id = str(selected_value[0])
            display_name = str(selected_value[1])
            self.dismiss((account_id, display_name))
        else:
            self.dismiss()

    @on(Button.Pressed, '#user-mention-button-quit')
    def handle_cancel(self) -> None:
        self.dismiss()
