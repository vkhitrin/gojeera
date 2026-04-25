from rich.cells import cell_len
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Button


def button_label_text(label: object) -> str:
    if isinstance(label, str):
        return label
    if hasattr(label, 'plain') and isinstance(label.plain, str):
        return label.plain
    return str(label)


def button_label_width(label: object) -> int:
    try:
        return max(cell_len(line) for line in button_label_text(label).splitlines())
    except ValueError:
        return 0


class ExtendedButton(Button):
    """Button widget with a loading state."""

    LOADING_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']

    is_loading: reactive[bool] = reactive(False)

    def __init__(
        self,
        *args,
        include_label_width_padding: bool = True,
        **kwargs,
    ):
        self.include_label_width_padding = include_label_width_padding
        super().__init__(*args, **kwargs)
        if not self.include_label_width_padding:
            self.styles.set_rule('line_pad', 0)
        self._loading_frame_index = 0
        self._loading_timer: Timer | None = None
        self._disabled_before_loading = False
        self._stored_label = self.label
        self._updating_loading_label = False

    def get_content_width(self, container, viewport) -> int:
        if self.include_label_width_padding:
            return super().get_content_width(container, viewport)

        return button_label_width(self.label)

    def watch_label(self, label) -> None:
        if not self._updating_loading_label and not self.is_loading:
            self._stored_label = label

    def watch_is_loading(self, is_loading: bool) -> None:
        if is_loading:
            self._disabled_before_loading = self.disabled
            self.disabled = True
            self._loading_frame_index = 0
            self._start_loading_animation()
            return

        self._stop_loading_animation()
        self.disabled = self._disabled_before_loading

    def _start_loading_animation(self) -> None:
        self._update_loading_label()
        if self._loading_timer is None:
            self._loading_timer = self.set_interval(0.08, self._update_loading_label)

    def _stop_loading_animation(self) -> None:
        if self._loading_timer is not None:
            self._loading_timer.stop()
            self._loading_timer = None

        self._updating_loading_label = True
        try:
            self.label = self._stored_label
        finally:
            self._updating_loading_label = False

    def _update_loading_label(self) -> None:
        frame = self.LOADING_FRAMES[self._loading_frame_index]
        self._loading_frame_index = (self._loading_frame_index + 1) % len(self.LOADING_FRAMES)

        self._updating_loading_label = True
        try:
            self.label = f'{frame} Saving...'
        finally:
            self._updating_loading_label = False
