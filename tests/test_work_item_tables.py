from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable

from gojeera.components.screens.repository_pull_requests_screen import RepositoryPullRequestsScreen
from gojeera.components.work_item.work_item_attachments import WorkItemAttachmentsWidget
from gojeera.components.work_item.work_item_development import WorkItemDevelopmentWidget
from gojeera.components.work_item.work_item_history import WorkItemHistoryWidget
from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.components.work_item.work_item_subtasks import WorkItemChildWorkItemsWidget
from gojeera.components.work_item.work_item_web_links import WorkItemRemoteLinksWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import (
    Attachment,
    JiraProjectRepository,
    JiraRepositoryPullRequest,
    WorkItemRemoteLink,
    WorkItemStatus,
    WorkItemType,
)
from gojeera.internal.models.work_items import (
    JiraWorkItem,
    PaginatedWorkItemHistory,
    RelatedJiraWorkItem,
    WorkItemHistoryChange,
    WorkItemHistoryEntry,
)
from gojeera.widgets.layout.extended_table import ExtendedTable, TableRecord


@pytest.mark.parametrize(
    'widget_type',
    [
        WorkItemAttachmentsWidget,
        WorkItemChildWorkItemsWidget,
        RelatedWorkItemsWidget,
        WorkItemRemoteLinksWidget,
        WorkItemDevelopmentWidget,
        WorkItemHistoryWidget,
    ],
)
async def test_issue_tabs_contain_tables(widget_type) -> None:
    widget = widget_type()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        table = widget.table
        assert isinstance(table, ExtendedTable)
        assert [column.label.plain for column in table.columns.values()] == list(widget.COLUMNS)
        assert table.cursor_type == 'row'
        assert not table.can_focus
        table.set_records([TableRecord('1', tuple('Cell' for _ in widget.COLUMNS))])
        table.focus()
        await pilot.pause()
        assert table.has_focus


async def test_attachments_table_selection_and_deletion(monkeypatch) -> None:
    widget = WorkItemAttachmentsWidget()
    widget.work_item_key = 'ENG-1'
    delete_attachment = AsyncMock(return_value=APIControllerResponse(success=True))

    class TestApp(App):
        api = SimpleNamespace(delete_attachment=delete_attachment)

        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        first = Attachment(id='1', filename='first.txt', mime_type='text/plain', size=2048)
        second = replace(first, id='2', filename='[second].txt')
        widget.attachments = [first, second]
        await pilot.pause()
        assert widget.displayed_count == widget.table.row_count == 2
        assert [cell.plain for cell in widget.table.get_row('2')] == [
            '[second].txt',
            '2.00',
            'text/plain',
            '',
            '',
        ]
        assert not widget.focus_attachment_by_filename('missing.txt')
        assert widget.focus_attachment_by_filename('[second].txt')
        await pilot.pause()
        assert widget.selected_attachment is second
        assert widget.table.has_focus
        open_attachment = AsyncMock()
        monkeypatch.setattr(widget, 'action_open_attachment', open_attachment)
        await pilot.press('enter')
        await pilot.pause()
        open_attachment.assert_awaited_once()
        await widget.handle_delete_choice(True)
        delete_attachment.assert_awaited_once_with('2')
        assert widget.attachments == [first]
        assert widget.table.row_count == widget.displayed_count == 1
        widget.attachments = None
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 0
        assert not widget.table.can_focus


async def test_repository_table_uses_enter_to_navigate(monkeypatch) -> None:
    screen = RepositoryPullRequestsScreen('ENG', JiraProjectRepository(id='1', name='Repository'))
    bindings = [
        binding if isinstance(binding, Binding) else Binding(*binding)
        for binding in screen.BINDINGS
    ]
    assert all(binding.key != 'ctrl+g' for binding in bindings)
    assert any(
        binding.key == 'enter' and binding.action == 'go_to_work_item' for binding in bindings
    )
    navigate = AsyncMock()
    monkeypatch.setattr(screen, 'action_go_to_work_item', navigate)
    event = Mock()
    await screen.on_pull_request_selected(event)
    navigate.assert_awaited_once()
    event.stop.assert_called_once()


async def test_table_mouse_clicks_select_without_activation() -> None:
    table = ExtendedTable(id='table', columns=('Summary',), cursor_type='row')
    activated_rows = []
    selected_headers = []

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield table

        def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
            activated_rows.append(event.row_key.value)

        def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
            selected_headers.append(event.label.plain)

    first, second = object(), object()
    async with TestApp().run_test() as pilot:
        table.set_records(
            [
                TableRecord('1', ('First',), first),
                TableRecord('2', ('Second',), second),
            ]
        )
        await pilot.pause()
        await pilot.click(table, offset=(2, 1))
        await pilot.click(table, offset=(2, 1))
        assert table.selected_payload is first
        await pilot.click(table, offset=(2, 2))
        await pilot.click(table, offset=(2, 2))
        assert table.selected_payload is second
        assert table.has_focus
        assert activated_rows == []
        await pilot.click(table, offset=(2, 0))
        assert selected_headers == ['Summary']
        await pilot.press('enter')
        await pilot.pause()
        assert activated_rows == ['2']


async def test_table_records_use_auto_height_and_vim_navigation() -> None:
    table = ExtendedTable(id='table', columns=('Summary',), cursor_type='row')

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield table

    async with TestApp().run_test(size=(40, 12)) as pilot:
        table.set_records(
            [
                TableRecord('1', ('First line\nSecond line\nThird line',)),
                TableRecord('2', ('Long text ' * 20,)),
            ]
        )
        await pilot.pause()
        assert table.get_row_height(table.ordered_rows[0].key) == 3
        table.focus()
        await pilot.press('j')
        assert table.cursor_row == 1
        await pilot.press('k')
        assert table.cursor_row == 0
        await pilot.press('G')
        assert table.cursor_row == 1
        await pilot.press('g')
        assert table.cursor_row == 0
        await pilot.press('l')
        await pilot.pause()
        assert table.scroll_x > 0
        await pilot.press('h')
        await pilot.pause()
        assert table.scroll_x == 0


async def test_table_preserves_selection_and_clears_payload() -> None:
    table = ExtendedTable(id='table', columns=('Summary',), cursor_type='row', disable_empty=True)

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield table

    first, second = object(), object()
    async with TestApp().run_test() as pilot:
        table.set_records(
            [
                TableRecord('1', ('[literal markup]',), first),
                TableRecord('2', ('Second',), second),
            ]
        )
        table.select_index(1, focus=True)
        assert table.selected_payload is second
        table.set_records(
            [
                TableRecord('2', ('Updated',), second),
                TableRecord('1', ('First',), first),
            ]
        )
        await pilot.pause()
        assert table.selected_payload is second
        assert table.get_row('2')[0].plain == 'Updated'
        table.clear_records()
        assert table.row_count == 0
        assert table.selected_payload is None
        assert len(table.columns) == 1


async def test_web_link_table_filters_missing_urls_and_opens_selected_link(monkeypatch) -> None:
    widget = WorkItemRemoteLinksWidget()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        link = WorkItemRemoteLink(
            id='1',
            global_id='',
            relationship='Docs',
            title='[Guide]',
            summary='',
            url='https://example.com',
            status_resolved=True,
        )
        widget.remote_links = [link, replace(link, id='2', url=None)]
        await pilot.pause()
        assert widget.displayed_count == widget.table.row_count == 1
        assert [cell.plain for cell in widget.table.get_row('1')] == [
            'Docs',
            '[Guide]',
            'Resolved',
            'https://example.com',
        ]
        open_url = Mock()
        monkeypatch.setattr(pilot.app, 'open_url', open_url)
        widget.table.focus()
        await pilot.press('enter')
        await pilot.pause()
        open_url.assert_called_once_with(link.url)


async def test_development_table_opens_selected_pull_request(monkeypatch) -> None:
    widget = WorkItemDevelopmentWidget()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        pull_request = JiraRepositoryPullRequest(
            id='1',
            title='Fix bug',
            work_item_key='ENG-1',
            work_item_id='1',
            url='https://example.com/pr/1',
        )
        widget.pull_requests = [pull_request]
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 1
        assert widget.table.selected_payload is pull_request
        open_url = Mock()
        monkeypatch.setattr(pilot.app, 'open_url', open_url)
        widget.table.focus()
        await pilot.press('enter')
        await pilot.pause()
        open_url.assert_called_once_with(pull_request.url)


@pytest.mark.parametrize('widget_type', [WorkItemChildWorkItemsWidget, RelatedWorkItemsWidget])
async def test_work_item_table_navigation(widget_type, monkeypatch) -> None:
    widget = widget_type()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        model_type = (
            JiraWorkItem if widget_type is WorkItemChildWorkItemsWidget else RelatedJiraWorkItem
        )
        work_item = model_type(
            id='1',
            key='ENG-1',
            summary='Summary',
            status=WorkItemStatus(id='1', name='Open'),
            work_item_type=WorkItemType(id='1', name='Task'),
        )
        widget.work_items = [work_item]
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 1
        assert widget.table.selected_payload is work_item
        load_work_item = Mock()
        monkeypatch.setattr(widget, 'load_work_item', load_work_item)
        widget.table.focus()
        assert all(binding.key != 'ctrl+g' for binding in widget.BINDINGS)
        await pilot.press('ctrl+g')
        await pilot.pause()
        load_work_item.assert_not_called()
        await pilot.press('enter')
        await pilot.pause()
        assert load_work_item.call_count == 1
        assert load_work_item.call_args.args == ('ENG-1',)
        widget.work_items = None
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 0


async def test_history_loads_next_page_when_table_scrolls_near_end() -> None:
    widget = WorkItemHistoryWidget()
    entries = [WorkItemHistoryEntry(id=str(index)) for index in range(101)]
    get_history = AsyncMock(
        side_effect=[
            APIControllerResponse(
                result=PaginatedWorkItemHistory(
                    entries=entries[:100], max_results=100, start_at=0, is_last=False
                )
            ),
            APIControllerResponse(
                result=PaginatedWorkItemHistory(
                    entries=entries[100:], max_results=100, start_at=100, is_last=True
                )
            ),
        ]
    )

    loaded_counts = []

    class TestApp(App):
        api = SimpleNamespace(get_work_item_history=get_history)

        def mark_detail_tab_count_loaded(self, tab_id: str, count: int) -> None:
            loaded_counts.append((tab_id, count))

        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test(size=(80, 24)) as pilot:
        widget.work_item_key = 'ENG-1'
        widget.load_if_needed()
        await pilot.pause()
        assert widget.table.row_count == 100
        assert get_history.await_count == 1
        widget.table.focus()
        widget.table.move_cursor(row=99)
        await pilot.pause()
        assert get_history.await_count == 2
        assert widget.table.row_count == widget.displayed_count == 101
        assert loaded_counts == [('tab-history', 101)]


async def test_history_table_displays_every_change() -> None:
    widget = WorkItemHistoryWidget()

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield widget

    async with TestApp().run_test() as pilot:
        changes = [
            WorkItemHistoryChange(field=f'Field {index}', to_value='new') for index in range(6)
        ]
        entry = WorkItemHistoryEntry(id='1', changes=changes)
        widget.history = [entry]
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 1
        assert widget.table.get_row('1')[2].plain == '; '.join(
            change.sentence() for change in changes
        )
        widget.history = None
        await pilot.pause()
        assert widget.table.row_count == widget.displayed_count == 0
