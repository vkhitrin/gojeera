"""Command palette widget with vim-style navigation support."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import events
from textual.binding import Binding
from textual.command import Command, CommandList, CommandPalette

if TYPE_CHECKING:
    from gojeera.app import MainScreen


class ExtendedPalette(CommandPalette):
    """Command palette that supports vim-style ctrl+j/k navigation."""

    BINDINGS = [
        *CommandPalette.BINDINGS,
        Binding('ctrl+j', 'cursor_down', 'Next command', show=False),
        Binding('ctrl+k', "command_list('cursor_up')", 'Previous command', show=False),
    ]

    def _is_loaded_work_item_command(self, command: Command) -> bool:
        hit_text = command.hit.text or ''
        calling_screen = self._calling_screen
        if calling_screen is None or not hasattr(calling_screen, 'information_panel'):
            return False

        try:
            main_screen = cast('MainScreen', calling_screen)
            work_item = main_screen.information_panel.work_item
        except Exception:
            return False

        if not work_item or not work_item.key:
            return False

        return hit_text.startswith(f'{work_item.key} > ')

    def _refresh_command_list(
        self, command_list: CommandList, commands: list[Command], clear_current: bool
    ) -> None:
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

        self._list_visible = bool(command_list.option_count)
        self._hit_count = command_list.option_count

    async def _on_key(self, event: events.Key) -> None:
        """Handle vim-style navigation even when the input consumes ctrl+k."""

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
