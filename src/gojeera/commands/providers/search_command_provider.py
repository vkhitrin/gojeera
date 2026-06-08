from __future__ import annotations

import re

from textual.command import Hit, Hits

from gojeera.commands.providers.action_command_provider import ActionCommandProvider


class SearchCommandProvider(ActionCommandProvider):
    """Expose search-related commands in the command palette."""

    @staticmethod
    def _extract_requested_page(query: str) -> int | None:
        match = re.search(r'\bpage\s+(\d+)\b', query, flags=re.IGNORECASE)
        if match is None:
            return None
        return int(match.group(1))

    @staticmethod
    def _can_jump_to_page(screen, requested_page: int) -> bool:
        return (
            screen.search_results_container.search_active
            and screen.search_results_container.results_loaded
            and not screen.search_results_container.is_loading
            and 1 <= requested_page <= screen.search_results_container._total_pages
        )

    @staticmethod
    def _build_page_jump_label(requested_page: int) -> str:
        return f'Go To Search Results Page {requested_page}'

    def _build_page_jump_invoke(self, screen, requested_page: int):
        async def invoke() -> None:
            if not self._can_jump_to_page(screen, requested_page):
                return
            screen.search_results_list._request_work_items_page(requested_page)

        return invoke

    def _iter_commands(self):
        screen = self._get_main_screen()
        if not screen:
            return

        if screen.current_loaded_work_item_key:
            yield (
                'Unload Work Item',
                'unload_work_item',
                'Clear the currently loaded work item details',
                screen,
            )

        if screen.search_results_container.search_active:
            yield (
                'Clear Search',
                'clear_search',
                'Remove Search Results',
                screen,
            )
            if screen.search_results_container.results_loaded:
                yield (
                    'Go To Search Results Page…',
                    'focus_search_results_page_input',
                    'Type "page N" in the command palette to load a page',
                    screen,
                )

    async def search(self, query: str) -> Hits:
        screen = self._get_main_screen()
        if not screen:
            return

        matcher = self.matcher(query)
        for label, action, help_text, action_screen in self._iter_commands():
            score = matcher.match(label)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(label),
                    self._make_callback(action, action_screen),
                    help=help_text,
                )

        requested_page = self._extract_requested_page(query)
        if requested_page is None or not self._can_jump_to_page(screen, requested_page):
            return

        label = self._build_page_jump_label(requested_page)
        score = matcher.match(label)
        if score <= 0 and re.fullmatch(r'\s*page\s+\d+\s*', query, flags=re.IGNORECASE):
            score = 1.0
        if score <= 0:
            return

        yield Hit(
            score,
            matcher.highlight(label),
            self._build_page_jump_invoke(screen, requested_page),
            help=f'Load page {requested_page} of the current search results',
        )
