from collections import OrderedDict
import logging
from typing import TYPE_CHECKING, cast

from textual.timer import Timer
from textual.widgets import Input
from textual.worker import Worker

from gojeera.utils.data.fields import (
    FieldMode as LabelsFieldMode,
)
from gojeera.utils.data.fields import (
    require_create_mode,
    require_update_mode,
)
from gojeera.utils.ui.delayed_lookup import cancel_delayed_lookup, schedule_delayed_lookup
from gojeera.widgets.selection.multi_select import MultiSelect

if TYPE_CHECKING:
    from gojeera.app import JiraApp

logger = logging.getLogger('gojeera')
LABEL_SUGGESTIONS_CACHE_MAX_SIZE = 128
LABEL_SUGGESTIONS_LOOKUP_DELAY_SECONDS = 0.15


class WorkItemLabels(MultiSelect):
    """
    Labels widget for Jira labels field with remote autocomplete from Jira API.
    """

    _class_suggestions_cache: OrderedDict[str, list[str]] = OrderedDict()

    @classmethod
    def _get_cached_suggestions(cls, query: str) -> list[str] | None:
        normalized_query = query.casefold()
        suggestions = cls._class_suggestions_cache.get(normalized_query)
        if suggestions is not None:
            cls._class_suggestions_cache.move_to_end(normalized_query)
        return suggestions

    @classmethod
    def _cache_suggestions(cls, query: str, suggestions: list[str]) -> None:
        normalized_query = query.casefold()
        cls._class_suggestions_cache[normalized_query] = suggestions
        cls._class_suggestions_cache.move_to_end(normalized_query)
        while len(cls._class_suggestions_cache) > LABEL_SUGGESTIONS_CACHE_MAX_SIZE:
            cls._class_suggestions_cache.popitem(last=False)

    def __init__(
        self,
        mode: LabelsFieldMode,
        field_id: str,
        title: str | None = None,
        required: bool = False,
        original_value: list[str] | None = None,
        supports_update: bool = True,
        **kwargs,
    ):
        self._last_query: str = ''
        self._suggestion_timer: Timer | None = None
        self._suggestion_worker: Worker | None = None

        options = []
        if original_value:
            options = [(label, label) for label in original_value]

        super().__init__(
            mode=mode,
            field_id=field_id,
            options=options,
            title=title,
            required=required,
            initial_value=original_value if mode == LabelsFieldMode.CREATE else None,
            original_value=original_value if mode == LabelsFieldMode.UPDATE else None,
            field_supports_update=supports_update,
            allow_new_tags=True,
            **kwargs,
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != f'{self.field_id}_input_tag':
            return

        query = event.value.strip()
        normalized_query = query.casefold()
        logger.debug(
            'labels input changed field_id=%s input_id=%s raw_value=%r query=%r',
            self.field_id,
            event.input.id,
            event.value,
            query,
        )

        if len(query) < 1:
            self._last_query = ''
            self._suggestion_timer, self._suggestion_worker = cancel_delayed_lookup(
                self._suggestion_timer,
                self._suggestion_worker,
            )
            logger.debug('labels query skipped field_id=%s reason=empty', self.field_id)
            return

        if normalized_query == self._last_query:
            logger.debug(
                'labels query skipped field_id=%s reason=duplicate query=%r', self.field_id, query
            )
            return

        self._last_query = normalized_query
        self._suggestion_timer, self._suggestion_worker = cancel_delayed_lookup(
            self._suggestion_timer,
            self._suggestion_worker,
        )
        logger.debug('labels worker scheduled field_id=%s query=%r', self.field_id, query)
        self._suggestion_timer = schedule_delayed_lookup(
            self,
            lambda: self._fetch_label_suggestions_for_query(query),
            worker_attr='_suggestion_worker',
            delay=LABEL_SUGGESTIONS_LOOKUP_DELAY_SECONDS,
        )

    def on_unmount(self) -> None:
        self._suggestion_timer, self._suggestion_worker = cancel_delayed_lookup(
            self._suggestion_timer,
            self._suggestion_worker,
        )

    def _show_remote_suggestions(self) -> None:
        try:
            self._refresh_autocomplete_visibility()
        except Exception:
            logger.exception(
                'labels suggestions dropdown failed field_id=%s',
                self.field_id,
            )

    async def _fetch_label_suggestions_for_query(self, query: str) -> None:
        normalized_query = query.casefold()
        if (cached_suggestions := self._get_cached_suggestions(query)) is not None:
            logger.debug(
                'labels suggestions cache hit field_id=%s query=%r count=%s',
                self.field_id,
                query,
                len(cached_suggestions),
            )
            self.add_tag_values(cached_suggestions)

            for suggestion in cached_suggestions:
                if suggestion not in self._name_to_id:
                    self._name_to_id[suggestion] = suggestion
                    self._id_to_name[suggestion] = suggestion
            self.call_after_refresh(self._show_remote_suggestions)
            return

        try:
            app = self.app
            if not hasattr(app, 'api'):
                logger.debug('labels suggestions skipped field_id=%s reason=no_api', self.field_id)
                return

            jira_app = cast('JiraApp', app)
            logger.debug('labels suggestions request field_id=%s query=%r', self.field_id, query)
            response = await jira_app.api.get_label_suggestions(query=query)
            logger.debug(
                'labels suggestions response field_id=%s query=%r success=%s has_result=%s',
                self.field_id,
                query,
                getattr(response, 'success', None),
                bool(getattr(response, 'result', None)),
            )

            if response.success:
                suggestions = list(response.result or [])
                if self._last_query != normalized_query:
                    return
                logger.debug(
                    'labels suggestions applied field_id=%s query=%r count=%s',
                    self.field_id,
                    query,
                    len(suggestions),
                )
                logger.debug(
                    'labels suggestions values field_id=%s query=%r suggestions=%r',
                    self.field_id,
                    query,
                    suggestions,
                )
                self._cache_suggestions(query, suggestions)
                self.add_tag_values(suggestions)

                for suggestion in suggestions:
                    if suggestion not in self._name_to_id:
                        self._name_to_id[suggestion] = suggestion
                        self._id_to_name[suggestion] = suggestion
                self.call_after_refresh(self._show_remote_suggestions)
        except Exception:
            logger.exception('labels suggestions failed field_id=%s query=%r', self.field_id, query)

    async def set_labels(self, labels: list[str]) -> None:
        options = [(label, label) for label in labels]
        await self.update_options(
            options=options,
            original_value=labels,
            field_supports_update=self._supports_update,
        )

    def get_value_for_create(self) -> list[str]:  # type: ignore[invalid-method-override]
        require_create_mode(self.mode, 'get_value_for_create()')
        selected = self.selected_tags

        return [label.strip().replace(' ', '') for label in selected if label.strip()]

    def get_value_for_update(self) -> list[str]:  # type: ignore[invalid-method-override]
        require_update_mode(self.mode, 'get_value_for_update()')
        selected = self.selected_tags

        return [label.strip().replace(' ', '') for label in selected if label.strip()]

    @property
    def value_has_changed(self) -> bool:
        require_update_mode(self.mode, 'value_has_changed')
        original_labels = self.original_value if self.original_value else []
        current_labels = self.get_value_for_update()

        if not original_labels and not current_labels:
            return False

        if bool(original_labels) != bool(current_labels):
            return True

        original_set = {label.lower() for label in original_labels}
        current_set = {label.lower() for label in current_labels}

        return original_set != current_set
