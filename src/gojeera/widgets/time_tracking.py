import logging

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, ProgressBar

logger = logging.getLogger('gojeera')


class TimeTrackingWidget(Vertical):
    """A widget to display time tracking information for a work item."""

    DEFAULT_CSS = """
    TimeTrackingWidget {
        height: auto;
        width: 100%;
    }

    TimeTrackingWidget > Label {
        width: 100%;
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

    def _build_first_row_text(self) -> str:
        parts = []
        if self._original_estimate:
            parts.append(f'Original Estimate: {self._original_estimate}')
        if self._time_spent:
            parts.append(f'Time Spent: {self._time_spent}')
        return ' | '.join(parts) if parts else ''

    def _build_second_row_text(self) -> str:
        if self._remaining_estimate:
            return f'Remaining Estimate: {self._remaining_estimate}'
        return ''

    def compose(self) -> ComposeResult:
        yield Label(self._build_first_row_text(), id='time-tracking-row1')
        yield Label(self._build_second_row_text(), id='time-tracking-row2')
        pb = ProgressBar(total=100, show_percentage=False, show_eta=False)
        pb.styles.width = '100%'
        yield pb

    def on_mount(self):
        self.progress_bar.styles.width = '100%'
        self._update_progress()

    def _update_progress(self):
        if self._original_estimate_seconds:
            self.progress_bar.progress = (
                self._time_spent_seconds * 100
            ) / self._original_estimate_seconds
        elif self._remaining_estimate_seconds and self._time_spent_seconds:
            self.progress_bar.progress = (self._time_spent_seconds * 100) / (
                self._remaining_estimate_seconds + self._time_spent_seconds
            )
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
            row1_label = self.query_one('#time-tracking-row1', Label)
            row1_label.update(self._build_first_row_text())
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        try:
            row2_label = self.query_one('#time-tracking-row2', Label)
            row2_label.update(self._build_second_row_text())
        except Exception as e:
            logger.debug(f'Exception occurred: {e}')

        self._update_progress()
