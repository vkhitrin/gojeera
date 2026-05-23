from __future__ import annotations

from rich.text import Text
from textual import events
from textual.content import Content
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem, TargetState

from gojeera.internal.models.jira import JiraFilterDict
from gojeera.widgets.selection.dropdown_positioning import constrain_dropdown_offset

HISTORY_PREFIX = '⏱   '


class SearchAutoComplete(AutoComplete):
    """Unified autocomplete dropdown for search history and JQL filters."""

    def __init__(
        self,
        target: Input,
        *,
        history_queries: list[str] | None = None,
        jql_filters: list[JiraFilterDict] | None = None,
        show_on_empty_input: bool = True,
        hide_exact_single_match: bool = False,
    ):
        self.history_queries = history_queries or []
        self.jql_filters = jql_filters or []
        self._filter_expressions = self._build_filter_expression_set(self.jql_filters)
        self._candidates: list[DropdownItem] = []
        self.show_on_empty_input = show_on_empty_input
        self.hide_exact_single_match = hide_exact_single_match
        self._rebuild_cached_candidates()
        super().__init__(target=target, candidates=self._candidates)

    def _build_candidates(self) -> list[DropdownItem]:
        items = [DropdownItem(main=query, prefix=HISTORY_PREFIX) for query in self.history_queries]

        sorted_filters = sorted(
            self.jql_filters,
            key=lambda filter_data: not bool(filter_data.get('starred', False)),
        )
        for filter_data in sorted_filters:
            if item := self._build_filter_candidate(filter_data):
                items.append(item)

        return items

    @staticmethod
    def _build_filter_candidate(filter_data: JiraFilterDict) -> DropdownItem | None:
        label = filter_data.get('label', '')
        expression = filter_data.get('expression', '')
        if not label or not expression:
            return None

        max_expression_length = 80
        expression_display = (
            expression[:max_expression_length] + '...'
            if len(expression) > max_expression_length
            else expression
        )
        main_text = f'{label} ({expression_display})'

        prefix_base = '☁ ' if filter_data.get('source', 'local') == 'remote' else '⌂ '
        if filter_data.get('starred', False):
            prefix_text = Content.from_markup(prefix_base + '[yellow]★[/yellow] ')
        else:
            prefix_text = prefix_base + '  '

        return DropdownItem(main=main_text, prefix=prefix_text)

    def get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
        del target_state
        return self._candidates

    def get_search_string(self, target_state: TargetState) -> str:
        return target_state.text if hasattr(target_state, 'text') else str(target_state)

    def get_matches(
        self, target_state: TargetState, candidates: list[DropdownItem], search_string: str
    ) -> list[DropdownItem]:
        del target_state
        normalized_search = search_string.strip().lower()
        if not normalized_search:
            return candidates if self.show_on_empty_input else []

        matches = []
        for candidate in candidates:
            label = candidate.value.split(' (', 1)[0]
            if normalized_search in label.lower():
                matches.append(candidate)
        return matches

    def should_show_dropdown(self, search_string: str) -> bool:
        if self.disabled or self.option_list.option_count == 0:
            return False

        if not self.show_on_empty_input and not search_string.strip():
            return False

        if self.hide_exact_single_match and self.option_list.option_count == 1:
            first_option = self.option_list.get_option_at_index(0).prompt
            first_option_text = (
                first_option.plain if isinstance(first_option, Text) else str(first_option)
            )
            if first_option_text == search_string:
                return False

        if self.target:
            self.styles.width = self.target.size.width

        return True

    def apply_completion(self, value: str, state: TargetState) -> None:
        del state
        if value in self.history_queries:
            self.target.value = value
            self.target.cursor_position = len(value)
            return

        label = value.split(' (', 1)[0] if ' (' in value else value
        for filter_data in self.jql_filters:
            if filter_data.get('label') == label:
                expression = filter_data.get('expression', '')
                cleaned_expression = expression.replace('\n', ' ').replace('\t', ' ').strip()
                self.target.value = cleaned_expression
                self.target.cursor_position = len(cleaned_expression)
                return

        self.target.value = value
        self.target.cursor_position = len(value)

    def update_history_queries(self, history_queries: list[str]) -> None:
        self.history_queries = history_queries
        self._rebuild_cached_candidates()
        self._refresh_options()

    def update_queries(self, queries: list[str]) -> None:
        self.update_history_queries(queries)

    def update_filters(self, jql_filters: list[JiraFilterDict]) -> None:
        self.jql_filters = jql_filters
        self._filter_expressions = self._build_filter_expression_set(jql_filters)
        self._rebuild_cached_candidates()
        self._refresh_options()

    def has_filter_expression(self, expression: str) -> bool:
        return self._normalize_expression(expression) in self._filter_expressions

    @classmethod
    def _build_filter_expression_set(cls, jql_filters: list[JiraFilterDict]) -> set[str]:
        return {
            normalized_expression
            for filter_data in jql_filters
            if (
                normalized_expression := cls._normalize_expression(
                    str(filter_data.get('expression', ''))
                )
            )
        }

    @staticmethod
    def _normalize_expression(expression: str) -> str:
        return ' '.join(expression.split())

    def _rebuild_cached_candidates(self) -> None:
        self._candidates = self._build_candidates()
        self.candidates = self._candidates

    def _refresh_options(self) -> None:
        self.option_list.clear_options()
        if self._candidates:
            self.option_list.add_options(self._candidates)
            if self.target.has_focus and self.display:
                self._handle_target_update()

    def _align_to_target(self) -> None:
        target_region = self.target.region
        x = target_region.x
        y = target_region.y + target_region.height

        dropdown = self.option_list
        width, height = dropdown.outer_size
        dropdown.styles.width = target_region.width

        self.absolute_offset = constrain_dropdown_offset(
            x=x,
            y=y,
            width=width,
            height=height,
            container_region=self.screen.scrollable_content_region,
        )

    def _show_all_candidates(self) -> None:
        self.option_list.clear_options()
        if self._candidates:
            self.option_list.add_options(self._candidates)
        self._align_to_target()
        self.action_show()
        self.option_list.highlighted = 0

    def _listen_to_messages(self, event: events.Event) -> None:
        if self.disabled:
            return

        if isinstance(event, events.Key):
            if event.key == 'down' and self.target.has_focus:
                event.prevent_default()
                event.stop()
                if self.display and self.option_list.option_count > 0:
                    highlighted = self.option_list.highlighted or 0
                    self.option_list.highlighted = (highlighted + 1) % self.option_list.option_count
                else:
                    self._show_all_candidates()
                return

            if self.option_list.option_count > 0:
                displayed = self.display
                highlighted = self.option_list.highlighted or 0

                if event.key == 'ctrl+j' and displayed:
                    event.prevent_default()
                    event.stop()
                    self.option_list.highlighted = (highlighted + 1) % self.option_list.option_count
                    return

                if event.key == 'ctrl+k' and displayed:
                    event.prevent_default()
                    event.stop()
                    self.option_list.highlighted = (highlighted - 1) % self.option_list.option_count
                    return

        super()._listen_to_messages(event)
