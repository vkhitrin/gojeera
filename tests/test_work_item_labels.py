from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, Mock

from gojeera.widgets.work_item.work_item_labels import (
    LABEL_SUGGESTIONS_CACHE_MAX_SIZE,
    LABEL_SUGGESTIONS_LOOKUP_DELAY_SECONDS,
    WorkItemLabels,
)


def test_label_suggestions_cache_is_case_normalized_and_bounded() -> None:
    WorkItemLabels._class_suggestions_cache.clear()

    WorkItemLabels._cache_suggestions('Backend', ['backend-api'])
    assert WorkItemLabels._get_cached_suggestions('BACKEND') == ['backend-api']

    for index in range(LABEL_SUGGESTIONS_CACHE_MAX_SIZE):
        WorkItemLabels._cache_suggestions(f'label-{index}', [f'label-{index}'])

    assert len(WorkItemLabels._class_suggestions_cache) == LABEL_SUGGESTIONS_CACHE_MAX_SIZE
    assert WorkItemLabels._get_cached_suggestions('backend') is None


def test_label_suggestions_are_debounced_and_superseded(monkeypatch) -> None:
    timer = Mock()
    schedule_lookup = Mock(return_value=timer)
    monkeypatch.setattr(
        'gojeera.widgets.work_item.work_item_labels.schedule_delayed_lookup',
        schedule_lookup,
    )
    widget = cast(
        Any,
        SimpleNamespace(
            field_id='labels',
            _last_query='',
            _suggestion_timer=None,
            _suggestion_worker=None,
        ),
    )

    WorkItemLabels.on_input_changed(
        widget,
        cast(Any, SimpleNamespace(input=SimpleNamespace(id='labels_input_tag'), value='Back')),
    )
    WorkItemLabels.on_input_changed(
        widget,
        cast(Any, SimpleNamespace(input=SimpleNamespace(id='labels_input_tag'), value='Backend')),
    )

    assert schedule_lookup.call_count == 2
    schedule_lookup.assert_called_with(
        widget,
        ANY,
        worker_attr='_suggestion_worker',
        delay=LABEL_SUGGESTIONS_LOOKUP_DELAY_SECONDS,
    )
    timer.stop.assert_called_once_with()
