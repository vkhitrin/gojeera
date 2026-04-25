from __future__ import annotations

import inspect
import logging
from typing import ClassVar

from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.screen import Screen
from textual.widgets import TextArea

from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.screens.edit_work_item_info_screen import EditWorkItemInfoScreen
from gojeera.components.screens.new_work_item_screen import AddWorkItemScreen
from gojeera.components.screens.work_log_screen import LogWorkScreen
from gojeera.widgets.markdown.extended_adf_markdown_textarea import ExtendedADFMarkdownTextArea

logger = logging.getLogger('gojeera')


class EditorCommandProvider(Provider):
    command_text: ClassVar[str]
    command_help: ClassVar[str]
    action_name: ClassVar[str]

    def _target_screen(self) -> Screen:
        screen_stack = self.app.screen_stack
        if len(screen_stack) >= 2:
            return screen_stack[-2]
        return self.screen

    def _supports_editor_command(self, screen: Screen) -> bool:
        return isinstance(
            screen,
            (
                CommentScreen,
                AddWorkItemScreen,
                EditWorkItemInfoScreen,
                LogWorkScreen,
            ),
        )

    def _has_focused_description_widget(self, screen: Screen) -> bool:
        try:
            description_widgets = list(screen.query(ExtendedADFMarkdownTextArea))
            if not description_widgets:
                return False

            for desc_widget in description_widgets:
                try:
                    textarea = desc_widget.query_one(TextArea)
                    if textarea.has_focus:
                        return True
                except Exception:
                    continue

            return False
        except Exception:
            return False

    def _eligible_target_screen(self) -> Screen | None:
        target_screen = self._target_screen()
        if not (
            self._supports_editor_command(target_screen)
            and self._has_focused_description_widget(target_screen)
        ):
            return None
        return target_screen

    def _build_invoke(self, target_screen: Screen):
        async def invoke() -> None:
            await self._invoke_on_screen(target_screen)

        return invoke

    async def discover(self) -> Hits:
        target_screen = self._eligible_target_screen()
        if target_screen is None:
            return

        yield DiscoveryHit(
            self.command_text,
            self._build_invoke(target_screen),
            help=self.command_help,
        )

    async def search(self, query: str) -> Hits:
        target_screen = self._eligible_target_screen()
        if target_screen is None:
            return

        matcher = self.matcher(query)
        score = matcher.match(self.command_text)
        if score <= 0:
            return

        yield Hit(
            score,
            matcher.highlight(self.command_text),
            self._build_invoke(target_screen),
            help=self.command_help,
        )

    async def _invoke_on_screen(self, target_screen: Screen) -> None:
        action_method = getattr(target_screen, self.action_name, None)
        if action_method and callable(action_method):
            result = action_method()
            if inspect.isawaitable(result):
                target_screen.run_worker(result, exclusive=False)
