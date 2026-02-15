from __future__ import annotations

from typing import Any, Callable

from textual.widgets import Static
from textual.widgets._select import SelectCurrent

from gojeera.widgets.vim_select import VimSelect


class LazySelect(VimSelect):
    """Select widget that supports lazy loading."""

    SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    def __init__(
        self,
        lazy_load_callback: Callable[[], Any] | None = None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._lazy_load_callback = lazy_load_callback
        self._has_loaded = False
        self._original_prompt = kwargs.get('prompt', 'Select')
        self._is_loading = False
        self._spinner_index = 0
        self._spinner_timer = None

    def watch_expanded(self, expanded: bool) -> None:
        if not expanded:
            return

        if not self._has_loaded and self._lazy_load_callback:
            self._has_loaded = True

            self._is_loading = True
            self._start_spinner()

            self._lazy_load_callback()

    def _start_spinner(self) -> None:
        self._spinner_index = 0
        self._update_spinner()

        self._spinner_timer = self.set_interval(0.08, self._update_spinner)

    def _update_spinner(self) -> None:
        if not self._is_loading:
            return
        spinner = self.SPINNER_FRAMES[self._spinner_index]
        new_prompt = f'{self._original_prompt} {spinner}'
        self._spinner_index = (self._spinner_index + 1) % len(self.SPINNER_FRAMES)
        self.prompt = new_prompt
        try:
            select_current = self.query_one(SelectCurrent)
            select_current.placeholder = new_prompt
            select_current.query_one('#label', Static).update(new_prompt)
        except Exception:
            pass

    def _stop_spinner(self) -> None:
        if self._is_loading:
            self._is_loading = False
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self.prompt = self._original_prompt
            try:
                select_current = self.query_one(SelectCurrent)
                select_current.placeholder = self._original_prompt
                if self.value == self.BLANK:
                    select_current.query_one('#label', Static).update(self._original_prompt)
            except Exception:
                pass

    def set_options(self, options) -> None:
        super().set_options(options)
        self._stop_spinner()
