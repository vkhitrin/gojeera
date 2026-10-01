from __future__ import annotations

from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static, TabPane

from gojeera.internal.jira.for_you import ForYouResult, ForYouSection, ForYouService
from gojeera.internal.store.config import CONFIGURATION
from gojeera.utils.jira.urls import build_external_url_for_work_item
from gojeera.widgets.layout.extended_footer import ExtendedFooter
from gojeera.widgets.layout.extended_modal_screen import ExtendedModalScreen
from gojeera.widgets.layout.extended_table import ExtendedTable
from gojeera.widgets.layout.vertical_suppress_clicks import VerticalSuppressClicks
from gojeera.widgets.navigation.extended_jumper import set_jump_mode
from gojeera.widgets.navigation.extended_tabbed_content import ExtendedTabbedContent

if TYPE_CHECKING:
    from gojeera.app import JiraApp

SECTIONS: tuple[tuple[ForYouSection, str], ...] = (
    ('due', 'Due Soon & Overdue'),
    ('updated', 'Recently Updated'),
    ('mentions', 'Mentions'),
)


class ForYouScreen(ExtendedModalScreen[str]):
    """Personal work signals, fetched only while this modal is open."""

    TITLE = 'For You'
    BINDINGS = ExtendedModalScreen.BINDINGS + [
        Binding('ctrl+r', 'refresh_feed', 'Refresh'),
        Binding('ctrl+o', 'open_work_item_in_browser', 'Browse'),
        Binding('ctrl+y', 'copy_work_item_key', 'Copy Key'),
        Binding('ctrl+u', 'copy_work_item_url', 'Copy URL'),
        Binding('[', 'previous_tab', 'Previous tab'),
        Binding(']', 'next_tab', 'Next tab'),
    ]
    DEFAULT_CSS = """
    ForYouScreen #modal_outer {
        width: 95%;
        height: 90%;
    }
    ForYouScreen ExtendedTabbedContent, ForYouScreen ContentSwitcher, ForYouScreen TabPane {
        height: 1fr;
    }
    ForYouScreen ExtendedTable {
        height: 1fr;
    }
    """

    @property
    def tabs(self) -> ExtendedTabbedContent:
        return self.query_one('#for-you-tabs', ExtendedTabbedContent)

    def compose(self) -> ComposeResult:
        yield from self.compose_modal_jumper()
        with VerticalSuppressClicks(id='modal_outer'):
            yield Static('For You', id='modal_title')
            with ExtendedTabbedContent(id='for-you-tabs'):
                for section, title in SECTIONS:
                    with TabPane(title, id=f'for-you-{section}'):
                        yield ExtendedTable(
                            id=f'{section}-table', cursor_type='row', zebra_stripes=True
                        )
        yield ExtendedFooter(show_command_palette=False)

    def on_mount(self) -> None:
        for section, _ in SECTIONS:
            table = self.query_one(f'#{section}-table', ExtendedTable)
            table.add_columns(
                'Key', 'Summary', 'Status', 'Due' if section == 'due' else 'Activity (UTC)'
            )
            if CONFIGURATION.get().jumper.enabled:
                set_jump_mode(table, 'focus')
                set_jump_mode(self.tabs.get_tab(f'for-you-{section}'), 'click')
        self.query_one('#due-table', ExtendedTable).focus()
        self.action_refresh_feed()

    def _shift_active_tab(self, direction: int) -> None:
        tabs = self.tabs
        tab_ids = [tab_id for tab_id in tabs.visible_tab_ids() if not tabs.get_tab(tab_id).disabled]
        if tabs.disabled or tabs.active not in tab_ids:
            return
        target_index = tab_ids.index(tabs.active) + direction
        if not 0 <= target_index < len(tab_ids):
            return
        active_pane = tabs.get_pane(tabs.active)
        focused = self.focused
        if focused is not None and (
            focused is active_pane or focused in active_pane.walk_children()
        ):
            tabs.activate_from_content(tab_ids[target_index])
        else:
            tabs.active = tab_ids[target_index]

    def action_previous_tab(self) -> None:
        self._shift_active_tab(-1)

    def action_next_tab(self) -> None:
        self._shift_active_tab(1)

    def action_refresh_feed(self) -> None:
        app = cast('JiraApp', self.app)
        service = ForYouService(app.api, CONFIGURATION.get().for_you)
        user = app.atlassian_context.user_info
        account_id = user.account_id if user else None
        for section, _ in SECTIONS:
            self.query_one(f'#{section}-table', ExtendedTable).clear()
            self.query_one(f'#for-you-{section}', TabPane).loading = True
            self.run_worker(
                self._load_section(service, section, account_id),
                exclusive=True,
                group=f'for-you-{section}',
            )

    async def _load_section(
        self, service: ForYouService, section: ForYouSection, account_id: str | None
    ) -> None:
        result = await service.load(section, account_id)
        table = self.query_one(f'#{section}-table', ExtendedTable)
        for entry in result.entries:
            item = entry.work_item
            activity = entry.activity_at
            detail = (
                item.display_due_date
                if section == 'due'
                else (activity.strftime('%Y-%m-%d %H:%M') if activity else '')
            )
            table.add_row(
                Text(item.key),
                Text(item.summary),
                Text(item.status_name),
                Text(detail),
                key=item.key,
            )
        self.query_one(f'#for-you-{section}', TabPane).loading = False
        self._notify_result(section, result)

    def _notify_result(self, section: ForYouSection, result: ForYouResult) -> None:
        title = f'For You — {dict(SECTIONS)[section]}'
        if result.error is not None:
            self.notify(
                f'Unable to load: {result.error} Refresh to retry.',
                title=title,
                severity='error',
            )
            return
        if result.failed_comment_items:
            self.notify(
                f'Comments unavailable for {result.failed_comment_items} item(s). Refresh to retry.',
                title=title,
                severity='warning',
            )

    def _selected_work_item_key(self) -> str | None:
        pane = self.tabs.active_pane
        if pane is None or pane.loading:
            return None
        table = pane.query_one(ExtendedTable)
        if not 0 <= table.cursor_row < table.row_count:
            return None
        key = table.ordered_rows[table.cursor_row].key.value
        return str(key) if key else None

    def action_open_work_item_in_browser(self) -> None:
        if key := self._selected_work_item_key():
            if url := build_external_url_for_work_item(key, cast('JiraApp', self.app)):
                self.app.open_url(url)

    def action_copy_work_item_key(self) -> None:
        if key := self._selected_work_item_key():
            self.app.copy_to_clipboard(key)
            self.notify('Key copied to clipboard', title=key)

    def action_copy_work_item_url(self) -> None:
        if key := self._selected_work_item_key():
            if url := build_external_url_for_work_item(key, cast('JiraApp', self.app)):
                self.app.copy_to_clipboard(url)
                self.notify('URL copied to clipboard', title=key)

    def action_load_selected_work_item(self) -> None:
        if key := self._selected_work_item_key():
            self.dismiss(key)

    @on(DataTable.RowSelected)
    def open_work_item(self, event: DataTable.RowSelected) -> None:
        event.stop()
        pane = self.tabs.active_pane
        if pane is not None and event.control is pane.query_one(ExtendedTable):
            self.action_load_selected_work_item()
