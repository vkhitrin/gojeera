from gojeera.widgets.selection.vim_select import VimSelect

CURRENT_STATUS_VALUE = ''


class WorkItemStatusSelectionInput(VimSelect):
    DEFAULT_CSS = """
    WorkItemStatusSelectionInput {
        width: 100%;
    }
    """

    WIDGET_ID = 'jira-work-item-status-selector'

    def __init__(self, statuses: list, *, prompt: str = ''):
        super().__init__(
            options=statuses,
            prompt=prompt,
            name='work_item_status',
            id=self.WIDGET_ID,
            type_to_search=True,
            compact=True,
            classes='jira-selector',
            allow_blank=False,
            value=CURRENT_STATUS_VALUE,
        )
        self.original_value: str | None = None
        self._transition_status_ids: dict[str, str] = {}

    @property
    def selected_status_id(self) -> str | None:
        if transition_id := self.selection:
            return self._transition_status_ids.get(transition_id, transition_id)
        return None

    def set_status_options(
        self,
        *,
        current_status_name: str,
        transitions: list[tuple[str, str, str]] | None = None,
    ) -> None:
        self._transition_status_ids = {
            transition_id: status_id for _label, transition_id, status_id in transitions or []
        }
        self.set_options(
            [
                (current_status_name, CURRENT_STATUS_VALUE),
                *[(label, transition_id) for label, transition_id, _status_id in transitions or []],
            ]
        )
        self.value = CURRENT_STATUS_VALUE
