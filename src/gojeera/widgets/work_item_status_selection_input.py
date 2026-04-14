from typing import cast

from textual.reactive import Reactive, reactive
from textual.widgets import Select

from gojeera.widgets.vim_select import VimSelect


class WorkItemStatusSelectionInput(VimSelect):
    WIDGET_ID = 'jira-work-item-status-selector'

    statuses: Reactive[list[tuple[str, str]] | None] = reactive(None, always_update=True)

    def __init__(self, statuses: list):
        super().__init__(
            options=statuses,
            prompt='Select a status',
            name='work_item_status',
            id=self.WIDGET_ID,
            type_to_search=True,
            compact=True,
            classes='jira-selector',
        )
        self.styles.width = '100%'
        self.original_value: str | None = None
        self._transition_status_ids: dict[str, str] = {}

    @property
    def selection(self) -> str | None:
        if self.value == Select.NULL:
            return None

        return cast(str | None, self.value) if self.value else None

    @property
    def selected_status_id(self) -> str | None:
        if transition_id := self.selection:
            return self._transition_status_ids.get(transition_id)
        return None

    def set_transition_options(self, statuses: list[tuple[str, str, str]]) -> None:
        self._transition_status_ids = {
            transition_id: status_id for _label, transition_id, status_id in statuses
        }
        self.set_options([(label, transition_id) for label, transition_id, _status_id in statuses])

    async def watch_statuses(self, statuses: list[tuple[str, str]] | None = None) -> None:
        self.clear()
        await self.recompose()
        self.set_options(statuses or [])
