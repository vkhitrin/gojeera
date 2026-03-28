from __future__ import annotations

from textual.command import DiscoveryHit, Hit, Hits, Provider


class WorkItemCommandProvider(Provider):
    """Expose loaded work-item actions in the command palette."""

    def _get_main_screen(self):
        from gojeera.app import MainScreen

        if isinstance(self.screen, MainScreen):
            return self.screen
        return None

    def _get_loaded_work_item_key(self) -> str | None:
        screen = self._get_main_screen()
        if not screen:
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
        assert work_item is not None

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
                f'{work_item_key} > Clone Work Item',
                'clone_loaded_work_item',
                'Clone work item',
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
                f'{work_item_key} > New Comment',
                'new_comment',
                'Add a comment to work item',
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

        if not (work_item.work_item_type and work_item.work_item_type.subtask):
            commands.insert(
                6,
                (
                    f'{work_item_key} > New Subtask',
                    'new_work_item_subtask',
                    'Create a subtask under work item',
                ),
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

    async def discover(self) -> Hits:
        for label, action, help_text, screen in self._iter_commands():
            yield DiscoveryHit(
                label,
                self._make_callback(action, screen),
                help=help_text,
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for label, action, help_text, screen in self._iter_commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    self._make_callback(action, screen),
                    help=help_text,
                )

    def _make_callback(self, action: str, screen):
        async def run_command() -> None:
            await self.app.run_action(action, screen)

        return run_command
