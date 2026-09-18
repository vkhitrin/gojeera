from collections.abc import Callable
from typing import Any, TypeVar, cast

from textual.timer import Timer
from textual.widget import Widget
from textual.worker import Worker

T = TypeVar('T')


def worker_is_running(worker: Worker[Any] | None) -> bool:
    """Return whether a Textual worker is still active."""
    return worker is not None and not worker.is_finished


def should_start_keyed_load(
    requested_key: str | None,
    loaded_key: str | None,
    worker: Worker[Any] | None,
) -> bool:
    """Return whether a keyed lazy load is both needed and idle."""
    return bool(requested_key and loaded_key != requested_key and not worker_is_running(worker))


def cancel_worker(worker: Worker[Any] | None) -> None:
    """Cancel an active Textual worker, if present."""
    if worker is not None and worker_is_running(worker):
        worker.cancel()


def request_bindings_refresh(widget: Widget) -> None:
    """Refresh bindings through the optimized application hook when available."""
    request_refresh = getattr(widget.app, 'request_bindings_refresh', None)
    if callable(request_refresh):
        request_refresh()
    else:
        widget.screen.refresh_bindings()


def replace_timer(
    widget: Widget,
    timer: Timer | None,
    delay: float,
    callback: Callable[[], T],
) -> Timer:
    """Stop an existing timer and schedule its replacement."""
    if timer is not None:
        timer.stop()
    return widget.set_timer(delay, callback)


class DebouncedFilterMixin:
    """Schedule one replaceable filter-render callback."""

    FILTER_RENDER_DELAY_SECONDS: float
    _filter_render_timer: Timer | None

    def _schedule_filter_callback(self, callback: Callable[[], Any]) -> None:
        widget = cast(Widget, self)
        self._filter_render_timer = replace_timer(
            widget,
            self._filter_render_timer,
            self.FILTER_RENDER_DELAY_SECONDS,
            callback,
        )
