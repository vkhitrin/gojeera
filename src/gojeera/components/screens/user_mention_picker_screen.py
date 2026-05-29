from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Select, Static

from gojeera.internal.models.jira import JiraUser
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.modal_buttons import (
    build_modal_cancel_button,
    build_modal_confirm_button,
)
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.selection.vim_select import VimSelect


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
        ('ctrl+c', 'dismiss_screen', 'Close'),
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
        yield from self.compose_modal_jumper()

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
                yield build_modal_confirm_button(
                    Button,
                    button_id='user-mention-button-insert',
                    label='Insert',
                    disabled=True,
                )
                yield build_modal_cancel_button(Button, button_id='user-mention-button-quit')

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
        self.activate_modal_actions(self.user_select, jump_mode='focus')
        self.activate_modal_actions(
            self.insert_button,
            self.query_one('#user-mention-button-quit', Button),
            focus=False,
        )

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
