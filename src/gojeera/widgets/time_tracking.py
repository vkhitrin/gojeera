import logging

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ProgressBar

logger = logging.getLogger('gojeera')


class TimeTrackingWidget(Vertical):
    """A widget to display time tracking information for a work item."""

    DEFAULT_CSS = """
    TimeTrackingWidget {
        height: auto;
        width: 100%;
        margin: 0;
        padding: 0;
    }

    TimeTrackingWidget > Label {
        width: 100%;
    }

    #time-tracking-stats {
        width: 100%;
        height: auto;
    }

    #time-tracking-logged {
        width: 1fr;
        color: $text;
    }

    #time-tracking-remaining {
        width: auto;
        color: $text-muted;
    }

    TimeTrackingWidget > ProgressBar {
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0;
    }

    TimeTrackingWidget > ProgressBar > Bar {
        width: 100%;
    }

    #time-tracking-meta {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        original_estimate: str | None = None,
        time_spent: str | None = None,
        remaining_estimate: str | None = None,
        original_estimate_seconds: int | None = None,
        time_spent_seconds: int | None = None,
        remaining_estimate_seconds: int | None = None,
    ):
        super().__init__()
        self._original_estimate = original_estimate or ''
        self._time_spent = time_spent or ''
        self._remaining_estimate = remaining_estimate or ''
        self._original_estimate_seconds = original_estimate_seconds
        self._time_spent_seconds = time_spent_seconds or 0
        self._remaining_estimate_seconds = remaining_estimate_seconds

        self.id = 'time-tracking-widget'

    @property
    def progress_bar(self) -> ProgressBar:
        return self.query_one(ProgressBar)

    @property
    def logged_label(self) -> Label:
        return self.query_one('#time-tracking-logged', Label)

    @property
    def remaining_label(self) -> Label:
        return self.query_one('#time-tracking-remaining', Label)

    @property
    def meta_label(self) -> Label:
        return self.query_one('#time-tracking-meta', Label)

    def _update_labels(self) -> None:
        self.logged_label.update(self._build_first_row_text())
        self.remaining_label.update(self._build_remaining_text())
        meta_text = self._build_second_row_text()
        self.meta_label.update(meta_text)
        self.meta_label.display = bool(meta_text)

    def _derive_logged_text(self) -> str:
        if self._time_spent:
            return self._time_spent.removesuffix(' logged')
        if self._time_spent_seconds > 0:
            return self._format_duration(self._time_spent_seconds)
        if (
            self._original_estimate_seconds is not None
            and self._remaining_estimate_seconds is not None
            and self._original_estimate_seconds > self._remaining_estimate_seconds
        ):
            logged_seconds = self._original_estimate_seconds - self._remaining_estimate_seconds
            return self._format_duration(logged_seconds)
        return ''

    @staticmethod
    def _format_duration(seconds: int) -> str:
        if seconds <= 0:
            return '0m'

        hours, remainder = divmod(seconds, 3600)
        minutes = remainder // 60
        days, hours = divmod(hours, 8)

        parts: list[str] = []
        if days:
            parts.append(f'{days}d')
        if hours:
            parts.append(f'{hours}h')
        if minutes:
            parts.append(f'{minutes}m')
        return ' '.join(parts) if parts else '0m'

    def _build_first_row_text(self) -> str:
        logged_text = self._derive_logged_text()
        return f'{logged_text} logged' if logged_text else '0m logged'

    def _build_remaining_text(self) -> str:
        logged_text = self._derive_logged_text()
        has_remaining = bool(self._remaining_estimate) and self._remaining_estimate != '0m'
        if has_remaining:
            return f'{self._remaining_estimate} remaining'
        if self._original_estimate and self._original_estimate != '0m':
            return f'{self._original_estimate} remaining'
        if logged_text:
            return '0m remaining'
        return ''

    def _build_second_row_text(self) -> str:
        if self._original_estimate and self._original_estimate != '0m':
            return f'Original estimate {self._original_estimate}'
        return ''

    def compose(self) -> ComposeResult:
        pb = ProgressBar(total=100, show_percentage=False, show_eta=False)
        pb.styles.width = '100%'
        with Horizontal(id='time-tracking-stats'):
            yield Label(self._build_first_row_text(), id='time-tracking-logged')
            yield Label(self._build_remaining_text(), id='time-tracking-remaining')
        yield pb
        yield Label(self._build_second_row_text(), id='time-tracking-meta')

    def on_mount(self):
        try:
            self._update_labels()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        self.progress_bar.styles.width = '100%'
        self._update_progress()

    def _update_progress(self):
        if self._remaining_estimate_seconds is not None and self._time_spent_seconds:
            self.progress_bar.progress = (self._time_spent_seconds * 100) / (
                self._remaining_estimate_seconds + self._time_spent_seconds
            )
        elif self._original_estimate_seconds:
            self.progress_bar.progress = (
                self._time_spent_seconds * 100
            ) / self._original_estimate_seconds
        elif self._time_spent_seconds:
            self.progress_bar.progress = 100
        else:
            self.progress_bar.progress = 0

    def update_time_tracking(
        self,
        original_estimate: str | None = None,
        time_spent: str | None = None,
        remaining_estimate: str | None = None,
        original_estimate_seconds: int | None = None,
        time_spent_seconds: int | None = None,
        remaining_estimate_seconds: int | None = None,
    ):
        self._original_estimate = original_estimate or ''
        self._time_spent = time_spent or ''
        self._remaining_estimate = remaining_estimate or ''
        self._original_estimate_seconds = original_estimate_seconds
        self._time_spent_seconds = time_spent_seconds or 0
        self._remaining_estimate_seconds = remaining_estimate_seconds

        try:
            self._update_labels()
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        self._update_progress()
