from textual import events
from textual.content import Content
from textual.geometry import Offset, Region, Spacing
from textual.widgets import Input
from textual_autocomplete import AutoComplete, DropdownItem, TargetState


class JQLAutoComplete(AutoComplete):
    """AutoComplete widget that suggests JQL expressions."""

    def __init__(
        self,
        target: Input,
        jql_filters: list[dict[str, str]] | None = None,
    ):
        self.jql_filters = jql_filters or []

        candidates = self._build_candidates()

        super().__init__(
            target=target,
            candidates=candidates,
        )

    def _build_candidates(self) -> list[DropdownItem]:
        items = []
        for filter_data in self.jql_filters:
            label = filter_data.get('label', '')
            expression = filter_data.get('expression', '')

            if label and expression:
                max_expression_length = 80
                if len(expression) > max_expression_length:
                    expression_display = expression[:max_expression_length] + '...'
                else:
                    expression_display = expression

                main_text = f'{label} ({expression_display})'

                source = filter_data.get('source', 'local')
                starred = filter_data.get('starred', False)

                if source == 'remote':
                    prefix_base = '☁ '
                else:
                    prefix_base = '⌂ '

                if starred:
                    prefix_text = Content.from_markup(prefix_base + '[yellow]★[/yellow] ')
                else:
                    prefix_text = prefix_base + '  '

                items.append(
                    DropdownItem(
                        main=main_text,
                        prefix=prefix_text,
                    )
                )

        return items

    def get_candidates(self, target_state: TargetState) -> list[DropdownItem]:
        return self._build_candidates()

    def get_search_string(self, target_state: TargetState) -> str:
        return target_state.text if hasattr(target_state, 'text') else str(target_state)

    def get_matches(
        self, target_state: TargetState, candidates: list[DropdownItem], search_string: str
    ) -> list[DropdownItem]:
        if not search_string or search_string.strip() == '':
            return candidates

        search_lower = search_string.lower()
        matches = []

        for candidate in candidates:
            main_text = str(candidate.main)
            if '(' in main_text:
                label = main_text.split('(')[0].strip()
            else:
                label = main_text

            if search_lower in label.lower():
                matches.append(candidate)

        return matches

    def should_show_dropdown(self, search_string: str) -> bool:
        if self.disabled:
            return False

        option_count = self.option_list.option_count

        if option_count == 0:
            return False

        if self.target:
            self.styles.width = self.target.size.width

        return True

    def apply_completion(self, value: str, state: TargetState) -> None:
        if ' (' in value:
            label = value.split(' (', 1)[0]
        else:
            label = value

        for filter_data in self.jql_filters:
            if filter_data.get('label') == label:
                expression = filter_data.get('expression', '')

                cleaned_expression = expression.replace('\n', ' ').replace('\t', ' ').strip()

                self.target.value = cleaned_expression

                self.target.cursor_position = len(cleaned_expression)
                return

        self.target.value = value
        self.target.cursor_position = len(value)

    def update_filters(self, jql_filters: list[dict[str, str]]) -> None:
        self.jql_filters = jql_filters

        new_candidates = self._build_candidates()

        self.option_list.clear_options()
        if new_candidates:
            self.option_list.add_options(new_candidates)
        else:
            return

    def _align_to_target(self) -> None:
        target_region = self.target.region
        x = target_region.x
        y = target_region.y + target_region.height

        dropdown = self.option_list
        width, height = dropdown.outer_size

        dropdown.styles.width = target_region.width

        x, y, _width, _height = Region(x, y, width, height).constrain(
            'inside',
            'none',
            Spacing.all(0),
            self.screen.scrollable_content_region,
        )
        self.absolute_offset = Offset(x, y)

    def _listen_to_messages(self, event: events.Event) -> None:
        if self.disabled:
            return

        if isinstance(event, events.Key) and self.option_list.option_count > 0:
            displayed = self.display
            highlighted = self.option_list.highlighted or 0

            if event.key == 'ctrl+j' and displayed:
                event.prevent_default()
                event.stop()
                highlighted = (highlighted + 1) % self.option_list.option_count
                self.option_list.highlighted = highlighted
                return

            elif event.key == 'ctrl+k' and displayed:
                event.prevent_default()
                event.stop()
                highlighted = (highlighted - 1) % self.option_list.option_count
                self.option_list.highlighted = highlighted
                return

        super()._listen_to_messages(event)
