from __future__ import annotations

import logging

from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.screen import Screen

from gojeera.components.comment_screen import CommentScreen
from gojeera.components.edit_work_item_info_screen import EditWorkItemInfoScreen
from gojeera.components.new_work_item_screen import AddWorkItemScreen
from gojeera.components.work_log_screen import LogWorkScreen
from gojeera.constants import LOGGER_NAME

logger = logging.getLogger(LOGGER_NAME)


class PanelCommandProvider(Provider):
    """Command provider for inserting ADF panel markers in description/comment fields."""

    async def discover(self) -> Hits:
        """Provide discovery hit for Insert Panel command.

        This command is only shown when a screen with description/comment field is active.
        """

        screen_stack = self.app.screen_stack
        if len(screen_stack) >= 2:
            target_screen = screen_stack[-2]
        else:
            target_screen = self.screen

        if self._is_panel_screen(target_screen) and self._has_description_widget(target_screen):

            async def insert_panel_on_screen() -> None:
                await self._insert_panel_on_screen(target_screen)

            yield DiscoveryHit(
                'Insert Panel',
                insert_panel_on_screen,
                help='Insert an ADF panel ([!NOTE], [!WARNING], etc.)',
            )
        else:
            pass

    async def search(self, query: str) -> Hits:
        screen_stack = self.app.screen_stack
        if len(screen_stack) >= 2:
            target_screen = screen_stack[-2]
        else:
            target_screen = self.screen

        if not (
            self._is_panel_screen(target_screen) and self._has_description_widget(target_screen)
        ):
            return

        matcher = self.matcher(query)
        command_text = 'Insert Panel'
        score = matcher.match(command_text)

        if score > 0:

            async def insert_panel_on_screen() -> None:
                await self._insert_panel_on_screen(target_screen)

            yield Hit(
                score,
                matcher.highlight(command_text),
                insert_panel_on_screen,
                help='Insert an ADF Panel ([!NOTE], [!WARNING], etc.)',
            )

    def _is_panel_screen(self, screen: Screen) -> bool:
        return isinstance(
            screen,
            (
                CommentScreen,
                AddWorkItemScreen,
                EditWorkItemInfoScreen,
                LogWorkScreen,
            ),
        )

    def _has_description_widget(self, screen: Screen) -> bool:
        try:
            from textual.widgets import TextArea

            from gojeera.widgets.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea

            description_widgets = list(screen.query(ExtendedADFMarkdownTextArea))
            if not description_widgets:
                return False

            for desc_widget in description_widgets:
                try:
                    textarea = desc_widget.query_one(TextArea)

                    if textarea.has_focus:
                        return True
                except Exception as e:
                    logger.debug(f'Failed to query textarea in description widget: {e}')
                    continue

            return False
        except Exception:
            return False

    async def _insert_panel_on_screen(self, target_screen: Screen) -> None:
        action_method = getattr(target_screen, 'action_insert_alert', None)
        if action_method and callable(action_method):
            target_screen.run_worker(action_method(), exclusive=False)
        else:
            pass
