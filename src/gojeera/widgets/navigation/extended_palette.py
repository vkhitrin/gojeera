"""Command palette widget with vim-style navigation support."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.align import Align
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.command import Command, CommandInput, CommandList, CommandPalette
from textual.widgets import Input
from textual.widgets.option_list import Option

from gojeera.widgets.layout.sub_palette import is_sub_command_palette_hit

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ExtendedPalette(CommandPalette):
    """Command palette that supports vim-style navigation and sub-palette switching."""

    BINDINGS = [
        *CommandPalette.BINDINGS,
        Binding('ctrl+j', 'cursor_down', 'Next command', show=False),
        Binding('ctrl+k', "command_list('cursor_up')", 'Previous command', show=False),
    ]

    def switch_palette_context(self, *, sub_palette_id: str | None, placeholder: str) -> None:
        """Refresh this palette in-place for a different command context."""
        cast('JiraApp', self.app).active_sub_command_palette_id = sub_palette_id
        self._cancel_gather_commands()
        self._stop_no_matches_countdown()

        input_widget = self.query_one(CommandInput)
        input_widget.placeholder = placeholder
        with self.prevent(Input.Changed):
            input_widget.value = ''
        input_widget.focus()

        command_list = self.query_one(CommandList)
        command_list.clear_options()
        self._list_visible = False
        self._hit_count = 0
        self._gather_commands('')

    def _is_loaded_work_item_command(self, command: Command) -> bool:
        hit_text = command.hit.text or ''
        app = self.app
        if not hasattr(app, 'information_panel'):
            return False

        try:
            main_screen = cast('JiraApp', app)
            work_item = main_screen.information_panel.work_item
        except Exception:
            return False

        if not work_item or not work_item.key:
            return False

        return hit_text.startswith(f'{work_item.key} > ')

    def _refresh_command_list(
        self, command_list: CommandList, commands: list[Command], clear_current: bool
    ) -> None:
        del clear_current
        sub_command_palette_id = getattr(self.app, 'active_sub_command_palette_id', None)
        if sub_command_palette_id:
            commands = [
                command
                for command in commands
                if is_sub_command_palette_hit(command.hit, sub_command_palette_id)
            ]

        sorted_commands = sorted(
            commands,
            key=lambda command: (
                self._is_loaded_work_item_command(command),
                command.hit.score,
            ),
            reverse=True,
        )
        command_list.clear_options().add_options(sorted_commands)

        if sorted_commands:
            command_list.highlighted = 0
        elif sub_command_palette_id:
            command_list.add_option(
                Option(
                    Align.center(Text('No matches found', style='not bold')),
                    disabled=True,
                    id=self._NO_MATCHES,
                )
            )

        self._list_visible = bool(command_list.option_count)
        self._hit_count = len(sorted_commands)

    async def _on_key(self, event: events.Key) -> None:
        """Handle vim-style navigation even when the input consumes ctrl+k."""

        if event.key in {'backspace', 'delete'}:
            input_widget = self.query_one(CommandInput)
            if getattr(self.app, 'active_sub_command_palette_id', None) and not input_widget.value:
                event.prevent_default()
                event.stop()
                cast('JiraApp', self.app).action_show_main_command_palette()
                return

        if event.key == 'ctrl+j':
            event.prevent_default()
            event.stop()
            self._action_cursor_down()
            return

        if event.key == 'ctrl+k':
            command_list = self.query_one(CommandList)
            if (
                command_list.option_count
                and not command_list.get_option_at_index(0).id == self._NO_MATCHES
            ):
                event.prevent_default()
                event.stop()
                self._action_command_list('cursor_up')
                return

        await super()._on_key(event)
