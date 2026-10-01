from __future__ import annotations

from gojeera.commands.providers.action_command_provider import ActionCommandProvider


class ForYouCommandProvider(ActionCommandProvider):
    """Offer the personal work feed in the command palette, alongside global F10."""

    def _iter_commands(self):
        if (app := self._get_main_screen()) is not None:
            yield (
                'For You',
                'show_for_you',
                'Due assignments, recent updates, and best-effort mentions',
                app,
            )
