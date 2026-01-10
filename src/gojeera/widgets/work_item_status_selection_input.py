from textual.reactive import Reactive, reactive

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
        self.original_value: str | None = None

    async def watch_statuses(self, statuses: list[tuple[str, str]] | None = None) -> None:
        self.clear()
        await self.recompose()
        self.set_options(statuses or [])
