from __future__ import annotations

from gojeera.commands.providers.action_command_provider import ActionCommandProvider
from gojeera.components.work_item.work_item_fields import WorkItemFields
from gojeera.utils.data.fields import supports_parent_work_item


class WorkItemCommandProvider(ActionCommandProvider):
    """Expose loaded work-item actions in the command palette."""

    def _get_loaded_work_item_key(self) -> str | None:
        screen = self._get_main_screen()
        if not screen or not screen.is_work_item_ready:
            return None
        work_item = screen.information_panel.work_item
        if not work_item:
            return None
        return work_item.key

    def _iter_commands(self):
        screen = self._get_main_screen()
        work_item_key = self._get_loaded_work_item_key()
        if not screen or not work_item_key:
            return

        work_item = screen.information_panel.work_item
        if work_item is None:
            return

        flag_action_label = (
            'Remove Flag' if WorkItemFields._work_item_is_flagged(work_item) else 'Add Flag'
        )
        watch_action_label = 'Stop Watching' if work_item.is_watching else 'Start Watching'
        commands: list[tuple[str, str, str]] = [
            (
                f'{work_item_key} > Open In Browser',
                'open_loaded_work_item_in_browser',
                'Open work item in Jira in your browser',
            ),
            (
                f'{work_item_key} > Copy Key',
                'copy_loaded_work_item_key',
                'Copy work item key to the clipboard',
            ),
            (
                f'{work_item_key} > Copy URL',
                'copy_loaded_work_item_url',
                'Copy work item URL to the clipboard',
            ),
            (
                f'{work_item_key} > Copy As Template',
                'copy_loaded_work_item_as_template',
                'Copy work item template YAML to the clipboard',
            ),
            (
                f'{work_item_key} > Clone Work Item',
                'clone_loaded_work_item',
                'Clone work item',
            ),
            (
                f'{work_item_key} > Reload Work Item',
                'reload_loaded_work_item',
                'Reload the active work item from Jira',
            ),
            (
                f'{work_item_key} > {watch_action_label}',
                'watch_loaded_work_item',
                '',
            ),
            (
                f'{work_item_key} > {flag_action_label}',
                'flag_work_item',
                '',
            ),
            (
                f'{work_item_key} > Edit Information',
                'edit_work_item_info',
                'Edit the summary and description',
            ),
            (
                f'{work_item_key} > New Attachment',
                'add_attachment',
                'Attach a file to work item',
            ),
            (
                f'{work_item_key} > New Related Item',
                'new_related_work_item',
                'Create a new relationship from work item',
            ),
            (
                f'{work_item_key} > New Web Link',
                'new_web_link',
                'Add a web link to work item',
            ),
            (
                f'{work_item_key} > View Worklog',
                'view_worklog',
                'Open the worklog list for the loaded work item',
            ),
            (
                f'{work_item_key} > Log Work',
                'log_work',
                'Log work against the loaded work item',
            ),
        ]

        if supports_parent_work_item(work_item):
            commands.append(
                (
                    f'{work_item_key} > Set Parent Work Item',
                    'set_parent_work_item',
                    'Set or clear the parent work item',
                )
            )

        if not (work_item.work_item_type and work_item.work_item_type.subtask):
            commands.insert(
                6,
                (
                    f'{work_item_key} > Create Subtask',
                    'create_work_item_subtask',
                    'Create a subtask under work item',
                ),
            )

        if screen.work_item_comments_widget.can_add_comment:
            commands.append(
                (
                    f'{work_item_key} > New Comment',
                    'new_comment',
                    'Add a comment to work item',
                )
            )

        if work_item.parent_key.strip():
            commands.append(
                (
                    f'{work_item_key} > Go To Parent',
                    'go_to_parent_work_item',
                    'Load the parent work item',
                )
            )

        for label, action, help_text in commands:
            yield label, action, help_text, screen
