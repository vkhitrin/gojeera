from __future__ import annotations

from gojeera.commands.providers.action_command_provider import ActionCommandProvider


class CreateCommandProvider(ActionCommandProvider):
    """Expose creation actions in the command palette."""

    def _iter_commands(self):
        screen = self._get_main_screen()
        if not screen:
            return

        yield (
            'Create Work Item',
            'create_work_item',
            'Create a Jira work item from scratch',
            screen,
        )
        yield (
            'Create Work Item From Template',
            'create_work_item_from_template',
            'Create a Jira work item from a template',
            screen,
        )
