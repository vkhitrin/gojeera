from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from textual.timer import Timer
from textual.worker import Worker


def cancel_delayed_lookup(
    timer: Timer | None,
    worker: Worker | None,
) -> tuple[Timer | None, Worker | None]:
    if timer is not None:
        timer.stop()
        timer = None
    if worker is not None:
        worker.cancel()
        worker = None
    return timer, worker


def schedule_delayed_lookup(
    owner: Any,
    lookup: Callable[[], Awaitable[Any]],
    *,
    worker_attr: str = '_search_worker',
    delay: float = 0.1,
) -> Timer:
    return owner.set_timer(
        delay,
        lambda: setattr(
            owner,
            worker_attr,
            owner.run_worker(lookup(), exclusive=False),
        ),
    )
