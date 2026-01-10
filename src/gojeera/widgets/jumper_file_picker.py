import logging
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Input
from textual_fspicker import FileOpen

from gojeera.config import CONFIGURATION
from gojeera.widgets.extended_jumper import ExtendedJumper

logger = logging.getLogger('gojeera')


class ExtendedFileOpen(FileOpen):
    """FileOpen dialog with jumper support."""

    BINDINGS = [
        Binding('full_stop', 'hidden', show=False),
        Binding('escape', 'dismiss(None)', 'Cancel'),
        Binding('ctrl+backslash', 'show_overlay', 'Jump'),
    ]

    def __init__(
        self,
        location: str | Path = '.',
        title: str = 'Open',
        *,
        open_button: str = '',
        cancel_button: str = '',
        filters=None,
        must_exist: bool = True,
        default_file: str | Path | None = None,
        double_click_directories: bool = True,
        suggest_completions: bool = True,
    ) -> None:
        super().__init__(
            location=location,
            title=title,
            open_button=open_button,
            cancel_button=cancel_button,
            filters=filters,
            must_exist=must_exist,
            default_file=default_file,
            double_click_directories=double_click_directories,
            suggest_completions=suggest_completions,
        )

    def compose(self) -> ComposeResult:
        try:
            jumper_enabled = CONFIGURATION.get().jumper.enabled
            jumper_keys = CONFIGURATION.get().jumper.keys
        except (LookupError, AttributeError):
            jumper_enabled = False
            jumper_keys = []

        if jumper_enabled:
            yield ExtendedJumper(keys=jumper_keys)

        yield from super().compose()

    def on_mount(self) -> None:
        super().on_mount()

        try:
            jumper_enabled = CONFIGURATION.get().jumper.enabled
        except (LookupError, AttributeError):
            return

        if jumper_enabled:
            try:
                file_input = self.query_one(Input)
                file_input.jump_mode = 'focus'  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

            try:
                select_button = self.query_one('#select', Button)
                select_button.jump_mode = 'click'  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

            try:
                cancel_button = self.query_one('#cancel', Button)
                cancel_button.jump_mode = 'click'  # type: ignore[attr-defined]
            except Exception as e:
                logger.debug(f'Exception occurred: {e}')

    async def action_show_overlay(self) -> None:
        try:
            jumper_enabled = CONFIGURATION.get().jumper.enabled
        except (LookupError, AttributeError):
            return

        if not jumper_enabled:
            return

        try:
            jumper = self.query_one(ExtendedJumper)
            overlays = jumper.get_overlays()
            if overlays:
                jumper.show()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')
