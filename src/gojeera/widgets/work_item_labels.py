import logging

from textual.widgets import Input

from gojeera.utils.fields import FieldMode
from gojeera.widgets.multi_select import MultiSelect

logger = logging.getLogger('gojeera')


class WorkItemLabels(MultiSelect):
    """
    Labels widget for Jira labels field with remote autocomplete from Jira API.
    """

    _class_suggestions_cache: dict[str, list[str]] = {}

    def __init__(
        self,
        mode: FieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: list[str] | None = None,
        supports_update: bool = True,
        **kwargs,
    ):
        self._last_query: str = ''

        options = []
        if original_value:
            options = [(label, label) for label in original_value]

        super().__init__(
            mode=mode,
            field_id=field_id,
            options=options,
            title=title,
            required=required,
            initial_value=original_value if mode == FieldMode.CREATE else None,
            original_value=original_value if mode == FieldMode.UPDATE else None,
            field_supports_update=supports_update,
            **kwargs,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f'{self.field_id}_input_tag':
            return

        query = event.value.strip()

        if len(query) < 1:
            return

        if query == self._last_query:
            return

        self._last_query = query

        self.run_worker(
            self._fetch_label_suggestions_for_query(query),
            exclusive=True,
            name=f'fetch_labels_{query}',
        )

    async def _fetch_label_suggestions_for_query(self, query: str) -> None:
        if query in WorkItemLabels._class_suggestions_cache:
            cached_suggestions = WorkItemLabels._class_suggestions_cache[query]
            self.add_tag_values(cached_suggestions)

            for suggestion in cached_suggestions:
                if suggestion not in self._name_to_id:
                    self._name_to_id[suggestion] = suggestion
                    self._id_to_name[suggestion] = suggestion
            return

        try:
            app = self.app
            if not hasattr(app, 'api'):
                return

            response = await app.api.get_label_suggestions(query=query)  # type: ignore[union-attr]

            if response.success and response.result:
                suggestions = response.result
                WorkItemLabels._class_suggestions_cache[query] = suggestions
                self.add_tag_values(suggestions)

                for suggestion in suggestions:
                    if suggestion not in self._name_to_id:
                        self._name_to_id[suggestion] = suggestion
                        self._id_to_name[suggestion] = suggestion
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

    async def set_labels(self, labels: list[str]) -> None:
        options = [(label, label) for label in labels]
        await self.update_options(
            options=options,
            original_value=labels,
            field_supports_update=self._supports_update,
        )

    def get_value_for_create(self) -> list[str]:  # type: ignore[invalid-method-override]
        if self.mode != FieldMode.CREATE:
            raise ValueError('get_value_for_create() only valid in CREATE mode')

        selected = self.selected_tags

        return [label.strip().replace(' ', '') for label in selected if label.strip()]

    def get_value_for_update(self) -> list[str]:  # type: ignore[invalid-method-override]
        if self.mode != FieldMode.UPDATE:
            raise ValueError('get_value_for_update() only valid in UPDATE mode')

        selected = self.selected_tags

        return [label.strip().replace(' ', '') for label in selected if label.strip()]

    @property
    def value_has_changed(self) -> bool:
        if self.mode != FieldMode.UPDATE:
            raise ValueError('value_has_changed only valid in UPDATE mode')

        original_labels = self.original_value if self.original_value else []
        current_labels = self.get_value_for_update()

        if current_labels is None:
            current_labels = []

        if not original_labels and not current_labels:
            return False

        if bool(original_labels) != bool(current_labels):
            return True

        original_set = {label.lower() for label in original_labels}
        current_set = {label.lower() for label in current_labels}

        return original_set != current_set
