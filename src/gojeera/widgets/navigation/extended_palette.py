"""Command palette widget with vim-style navigation support."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from rich.align import Align
from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.command import Command, CommandInput, CommandList, CommandPalette
from textual.widgets import Input, Static
from textual.widgets.option_list import Option

from gojeera.widgets.layout.sub_palette import (
    get_sub_command_palette_launch,
    is_command_palette_notice,
    is_sub_command_palette_hit,
)

if TYPE_CHECKING:
    from gojeera.app import JiraApp


class ExtendedPalette(CommandPalette):
    """Command palette that supports vim-style navigation and sub-palette switching."""

    _LOADING = '--loading'
    _RESULT_LIMIT_WARNING = '--result-limit-warning'
    _last_normalized_search_value = ''

    DEFAULT_CSS = """
    ExtendedPalette #--result-limit-warning {
        overlay: screen;
        height: 1;
        padding: 0 2;
        color: $background;
        background: $warning;
        text-style: bold;
        display: none;
        opacity: 0;

        &.--prepared {
            display: block;
        }

        &.--active {
            opacity: 1;
        }
    }
    """

    BINDINGS = [
        *CommandPalette.BINDINGS,
        Binding('ctrl+j', 'cursor_down', 'Next command', show=False),
        Binding('ctrl+k', "command_list('cursor_up')", 'Previous command', show=False),
    ]

    def compose(self) -> ComposeResult:
        """Add a result-limit warning below the command list."""
        yield from super().compose()
        yield Static('', id=self._RESULT_LIMIT_WARNING)

    def _on_mount(self, _: events.Mount) -> None:
        super()._on_mount(_)
        self._prepare_result_limit_warning()

    def switch_palette_context(self, *, sub_palette_id: str | None, placeholder: str) -> None:
        """Refresh this palette in-place for a different command context."""
        cast('JiraApp', self.app).active_sub_command_palette_id = sub_palette_id
        self._cancel_gather_commands()
        self._stop_no_matches_countdown()
        self._select_context_providers(sub_palette_id)

        input_widget = self.query_one(CommandInput)
        input_widget.placeholder = placeholder
        with self.prevent(Input.Changed):
            input_widget.value = ''
        self._last_normalized_search_value = ''
        input_widget.focus()

        command_list = self.query_one(CommandList)
        command_list.clear_options()
        self._prepare_result_limit_warning()
        self._set_result_limit_warning(None)
        self._set_command_list_loading(command_list, bool(sub_palette_id))
        self._list_visible = bool(sub_palette_id)
        self._hit_count = 0
        self._gather_commands('')

    def _select_context_providers(self, sub_palette_id: str | None) -> None:
        all_providers = getattr(self, '_all_context_providers', None)
        if all_providers is None:
            all_providers = list(self._providers)
            self._all_context_providers = all_providers
        self._providers = (
            list(all_providers)
            if sub_palette_id is None
            else [
                provider
                for provider in all_providers
                if getattr(provider, 'palette_id', None) == sub_palette_id
            ]
        )

    async def _on_unmount(self) -> None:
        all_providers = getattr(self, '_all_context_providers', None)
        if all_providers is not None:
            self._providers = list(all_providers)
        await super()._on_unmount()

    @on(Input.Changed)
    def _input(self, event: Input.Changed) -> None:
        """Skip searches when whitespace leaves the effective query unchanged."""
        event.prevent_default()
        normalized_value = event.value.strip()
        if normalized_value == self._last_normalized_search_value:
            event.stop()
            return
        self._last_normalized_search_value = normalized_value
        super()._input(event)

    def _set_command_list_loading(self, command_list: CommandList, loading: bool) -> None:
        command_list.loading = loading
        command_list.set_class(loading, self._LOADING)

    def _set_result_limit_warning(self, message: str | None) -> None:
        warning = self.query_one(f'#{self._RESULT_LIMIT_WARNING}', Static)
        warning.update(message or '')
        if message is None:
            warning.remove_class('--active')
            return

        self._position_result_limit_warning()
        warning.add_class('--active')

    def _prepare_result_limit_warning(self) -> None:
        """Lay out the warning only for palettes that can display it."""
        active_palette_id = getattr(self.app, 'active_sub_command_palette_id', None)
        warning_supported = any(
            getattr(provider, 'palette_id', None) == active_palette_id
            and getattr(provider, 'shows_result_limit_warning', False)
            for provider in self._providers
        )
        warning = self.query_one(f'#{self._RESULT_LIMIT_WARNING}', Static)
        warning.set_class(warning_supported, '--prepared')
        if warning_supported:
            self._position_result_limit_warning()

    def _position_result_limit_warning(self) -> None:
        warning = self.query_one(f'#{self._RESULT_LIMIT_WARNING}', Static)
        command_list = self.query_one(CommandList)
        input_container = self.query_one('#--input')
        command_input = self.query_one(CommandInput)
        max_height = command_list.styles.max_height
        input_height = command_input.styles.height
        if max_height is None or input_height is None:
            return
        palette_container = self.query_one('#--container')
        container_width = palette_container.styles.width
        container_max_height = palette_container.styles.max_height
        result_list_bottom = (
            palette_container.styles.margin.top
            + input_container.styles.gutter.height
            + int(input_height.resolve(self.size, self.app.size))
            + int(max_height.resolve(self.size, self.app.size))
        )
        warning_layout_origin = (
            self.size.height
            if container_max_height is None
            else min(
                self.size.height,
                int(container_max_height.resolve(self.size, self.app.size)),
            )
        ) + palette_container.styles.margin.top

        warning.styles.width = container_width
        warning.styles.offset = (
            0,
            result_list_bottom - warning_layout_origin,
        )

    def on_resize(self, _: events.Resize) -> None:
        """Keep the result-limit warning aligned after terminal resizes."""
        self.call_after_refresh(self._position_result_limit_warning)

    def _start_busy_countdown(self) -> None:
        if getattr(self.app, 'active_sub_command_palette_id', None):
            self._stop_busy_countdown()
            return
        super()._start_busy_countdown()

    def _select_or_command(self, event: Any = None) -> None:
        if event is not None:
            event.stop()

        if self._list_visible or self._selected_command is None:
            return super()._select_or_command()

        launch_details = get_sub_command_palette_launch(self._selected_command)
        if launch_details is None:
            return super()._select_or_command()

        palette_id, placeholder = launch_details
        self._selected_command = None
        self.switch_palette_context(sub_palette_id=palette_id, placeholder=placeholder)

    @staticmethod
    def _is_loaded_work_item_command(command: Command, loaded_prefix: str | None) -> bool:
        if loaded_prefix is None:
            return False
        hit_text = command.hit.text or ''
        return hit_text.startswith(loaded_prefix)

    def _refresh_command_list(
        self, command_list: CommandList, commands: list[Command], clear_current: bool
    ) -> None:
        del clear_current
        self._set_command_list_loading(command_list, False)
        sub_command_palette_id = getattr(self.app, 'active_sub_command_palette_id', None)
        if sub_command_palette_id:
            commands = [
                command
                for command in commands
                if is_sub_command_palette_hit(command.hit, sub_command_palette_id)
            ]

        loaded_work_item_key = getattr(self.app, 'current_loaded_work_item_key', None)
        loaded_prefix = f'{loaded_work_item_key} > ' if loaded_work_item_key else None

        result_commands = [
            command for command in commands if not is_command_palette_notice(command.hit)
        ]
        sorted_commands = sorted(
            result_commands,
            key=lambda command: (
                self._is_loaded_work_item_command(command, loaded_prefix),
                command.hit.score,
            ),
            reverse=True,
        )
        notices = [command for command in commands if is_command_palette_notice(command.hit)]
        notice_text = notices[0].hit.text if notices else None
        command_list.clear_options().add_options(sorted_commands)
        self._set_result_limit_warning(notice_text)

        if sorted_commands:
            command_list.highlighted = 0
        elif sub_command_palette_id and not notices:
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
                and command_list.get_option_at_index(0).id != self._NO_MATCHES
            ):
                event.prevent_default()
                event.stop()
                self._action_command_list('cursor_up')
                return

        await super()._on_key(event)
