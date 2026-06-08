import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from textual.widgets import Select

from gojeera.app import JiraApp
from gojeera.components.work_item.work_item_fields import (
    FLAGGED_GLYPH,
    UNFLAGGED_GLYPH,
    WorkItemFields,
)
from gojeera.internal.jira.work_item_permissions import VIEW_WATCHERS_PERMISSIONS
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.jira.factories import WorkItemFactory
from gojeera.widgets.button_with_metadata import ButtonWithMetadata

from .test_helpers import (
    choose_select_option,
    load_work_item_from_search,
    wait_until,
    with_snapshot_assertion,
    with_snapshot_assertion_fixture,
)

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


def _create_eng3_work_item():
    return WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )


def _patched_watching_widget(monkeypatch, *, is_watching: bool):
    work_item = _create_eng3_work_item()
    work_item.is_watching = is_watching
    work_item.watch_count = 2
    fields_widget = WorkItemFields()
    button = ButtonWithMetadata(icon='◉')

    monkeypatch.setattr(WorkItemFields, 'work_item', property(lambda _self: work_item))
    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(WorkItemFields, 'watchers_button', property(lambda _self: button))
    monkeypatch.setattr(fields_widget, 'notify', Mock())
    return work_item, fields_widget, button


def test_work_item_is_flagged_reads_custom_field_value() -> None:
    work_item = _create_eng3_work_item()
    work_item.custom_fields = work_item.custom_fields or {}
    work_item.custom_fields['customfield_10114'] = [{'value': 'Impediment'}]

    assert WorkItemFields._work_item_is_flagged(work_item, 'customfield_10114')


def test_current_work_item_flagged_state_prefers_remote_state() -> None:
    fields_widget = WorkItemFields()
    fields_widget._flagged_state = True

    assert fields_widget._current_work_item_flagged_state() is True


def test_current_work_item_flagged_state_reads_work_item_flagged(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.flagged = True
    fields_widget = WorkItemFields()
    fields_widget._flagged_state = None
    monkeypatch.setattr(WorkItemFields, 'work_item', property(lambda _self: work_item))

    assert WorkItemFields._current_work_item_flagged_state(fields_widget) is True


def test_watch_work_item_before_mount_does_not_query_children() -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    fields_widget = WorkItemFields()

    fields_widget.watch_work_item(work_item)


def test_sync_flag_button_uses_remote_state_without_field_key(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    fields_widget = WorkItemFields()
    fields_widget._flagged_state = True

    button = type(
        'FakeButton',
        (),
        {
            'label': '',
            'disabled': True,
            'tooltip': None,
            'refresh': lambda self, *, layout=False: setattr(self, 'refresh_layout', layout),
        },
    )()
    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(WorkItemFields, 'flag_button', property(lambda _self: button))

    fields_widget._sync_flag_button(work_item)

    assert button.label == '⚑'
    assert button.disabled is False


def test_flag_button_refresh_is_skipped_when_flagged_state_is_known(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.flagged = False
    fields_widget = WorkItemFields()
    run_worker = Mock()
    monkeypatch.setattr(fields_widget, 'run_worker', run_worker)

    fields_widget._start_flag_button_state_refresh_if_needed(work_item)

    run_worker.assert_not_called()


def test_flag_button_refresh_runs_when_flagged_state_is_unknown(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.flagged = None
    fields_widget = WorkItemFields()

    def fake_run_worker(coro, *, exclusive):
        coro.close()
        return SimpleNamespace(is_finished=False, exclusive=exclusive)

    run_worker = Mock(side_effect=fake_run_worker)
    monkeypatch.setattr(fields_widget, 'run_worker', run_worker)

    fields_widget._start_flag_button_state_refresh_if_needed(work_item)

    run_worker.assert_called_once()
    assert run_worker.call_args.kwargs == {'exclusive': False}


def test_sync_watchers_action_displays_positive_watch_count(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.watch_count = 2
    fields_widget = WorkItemFields()

    button = ButtonWithMetadata(icon='◉')
    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(WorkItemFields, 'watchers_button', property(lambda _self: button))

    fields_widget._sync_watchers_action(work_item)

    assert button.label == '◉ 2'
    assert button.metadata == '2'
    assert button.disabled is False


def test_sync_watchers_action_displays_multi_digit_count_as_metadata(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.watch_count = 12
    fields_widget = WorkItemFields()

    button = ButtonWithMetadata(icon='◉')
    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(WorkItemFields, 'watchers_button', property(lambda _self: button))

    fields_widget._sync_watchers_action(work_item)

    assert button.label == '◉ 12'
    assert button.metadata == '12'


def test_watchers_action_refreshes_layout_when_metadata_changes(monkeypatch) -> None:
    button = ButtonWithMetadata(icon='◉')
    refresh = Mock()
    monkeypatch.setattr(button, 'refresh', refresh)

    button.metadata = '4'

    assert button.label == '◉ 4'
    refresh.assert_any_call(layout=True)


def test_sync_watchers_action_hides_zero_watch_count(monkeypatch) -> None:
    work_item = WorkItemFactory.create_work_item(
        json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    )
    work_item.watch_count = 0
    fields_widget = WorkItemFields()

    button = ButtonWithMetadata(icon='◉', metadata='2')
    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(WorkItemFields, 'watchers_button', property(lambda _self: button))

    fields_widget._sync_watchers_action(work_item)

    assert button.label == '◉'
    assert button.metadata == ''
    assert button.disabled is False


async def test_can_view_watchers_returns_false_when_permission_is_missing(monkeypatch) -> None:
    fields_widget = WorkItemFields()
    api = SimpleNamespace(
        validate_work_item_permissions=AsyncMock(
            return_value=APIControllerResponse(
                success=False,
                error='Missing required permission(s) to view watchers: VIEW_VOTERS_AND_WATCHERS',
            )
        )
    )
    monkeypatch.setattr(WorkItemFields, 'app', property(lambda _self: SimpleNamespace(api=api)))

    assert not await fields_widget._can_view_watchers('ENG-3')
    api.validate_work_item_permissions.assert_awaited_once_with(
        'ENG-3',
        list(VIEW_WATCHERS_PERMISSIONS),
        action_name='view watchers',
    )


def test_start_view_watchers_permission_load_schedules_background_worker(monkeypatch) -> None:
    fields_widget = WorkItemFields()
    scheduled = {}

    def fake_run_worker(coro, *, exclusive, group):
        coro.close()
        scheduled['exclusive'] = exclusive
        scheduled['group'] = group
        return SimpleNamespace(is_finished=False)

    monkeypatch.setattr(WorkItemFields, 'is_mounted', property(lambda _self: True))
    monkeypatch.setattr(fields_widget, 'run_worker', fake_run_worker)

    fields_widget._start_view_watchers_permission_load('ENG-3')

    assert scheduled == {
        'exclusive': False,
        'group': 'view-watchers-permission-load',
    }
    assert (
        fields_widget._permission_cache._workers[('ENG-3', VIEW_WATCHERS_PERMISSIONS)].is_finished
        is False
    )


async def test_can_view_watchers_uses_cached_permission_without_request(monkeypatch) -> None:
    fields_widget = WorkItemFields()
    fields_widget._permission_cache._cache[('ENG-3', VIEW_WATCHERS_PERMISSIONS)] = (
        APIControllerResponse(
            success=False,
            error='Missing required permission(s) to view watchers: VIEW_VOTERS_AND_WATCHERS',
        )
    )
    api = SimpleNamespace(validate_work_item_permissions=AsyncMock())
    monkeypatch.setattr(WorkItemFields, 'app', property(lambda _self: SimpleNamespace(api=api)))

    assert not await fields_widget._can_view_watchers('ENG-3')
    api.validate_work_item_permissions.assert_not_awaited()


async def test_toggle_current_user_watching_starts_watching_without_watchers_menu(
    monkeypatch,
) -> None:
    work_item, fields_widget, button = _patched_watching_widget(monkeypatch, is_watching=False)
    monkeypatch.setattr(
        fields_widget,
        '_start_watching_work_item',
        AsyncMock(return_value=APIControllerResponse()),
    )
    stop_watching = AsyncMock()
    monkeypatch.setattr(fields_widget, '_stop_watching_work_item', stop_watching)

    await fields_widget._toggle_current_user_watching()

    assert work_item.is_watching is True
    assert work_item.watch_count == 3
    assert button.label == '◉ 3'
    fields_widget._start_watching_work_item.assert_awaited_once()
    stop_watching.assert_not_awaited()


async def test_toggle_current_user_watching_stops_watching_without_watchers_menu(
    monkeypatch,
) -> None:
    work_item, fields_widget, button = _patched_watching_widget(monkeypatch, is_watching=True)
    start_watching = AsyncMock()
    monkeypatch.setattr(fields_widget, '_start_watching_work_item', start_watching)
    monkeypatch.setattr(
        fields_widget,
        '_stop_watching_work_item',
        AsyncMock(return_value=APIControllerResponse()),
    )

    await fields_widget._toggle_current_user_watching()

    assert work_item.is_watching is False
    assert work_item.watch_count == 1
    assert button.label == '◉ 1'
    start_watching.assert_not_awaited()
    fields_widget._stop_watching_work_item.assert_awaited_once()


async def open_work_item_and_view_fields(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    await pilot.app.workers.wait_for_complete()

    fields_widget = await loaded_fields_widget_with_priority(pilot)
    await asyncio.sleep(0.3)

    status_selector = fields_widget.work_item_status_selector
    status_selector.focus()
    await asyncio.sleep(0.3)


async def open_flagged_work_item_and_view_fields(pilot):
    await load_work_item_from_search(pilot, 'ENG-5')

    await pilot.app.workers.wait_for_complete()

    fields_widget = await loaded_fields_widget_with_priority(pilot)
    await wait_until(lambda: fields_widget.flag_button.label == FLAGGED_GLYPH, timeout=3.0)
    fields_widget.work_item_status_selector.focus()
    await asyncio.sleep(0.3)


async def unflag_work_item_and_view_fields(pilot):
    await load_work_item_from_search(pilot, 'ENG-5')

    await pilot.app.workers.wait_for_complete()

    fields_widget = await loaded_fields_widget_with_priority(pilot)
    await wait_until(lambda: fields_widget.flag_button.label == FLAGGED_GLYPH, timeout=3.0)
    await fields_widget.toggle_work_item_flag()
    await wait_until(lambda: fields_widget.flag_button.label == UNFLAGGED_GLYPH, timeout=3.0)
    fields_widget.work_item_status_selector.focus()
    await asyncio.sleep(0.3)


async def add_work_item_watcher_and_view_fields(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    await pilot.app.workers.wait_for_complete()

    fields_widget = await loaded_fields_widget_with_priority(pilot)
    await wait_until(lambda: fields_widget.watchers_button.label == '◉ 1', timeout=3.0)
    await fields_widget._toggle_current_user_watching()
    await wait_until(lambda: fields_widget.watchers_button.label == '◉ 2', timeout=3.0)
    fields_widget.work_item_status_selector.focus()
    await asyncio.sleep(0.3)


async def loaded_fields_widget_with_priority(pilot):
    fields_widget = pilot.app.screen.query_one(WorkItemFields)
    await wait_until(
        lambda: (
            bool(fields_widget.priority_selector.value)
            and fields_widget.priority_selector.selection is not None
        ),
        timeout=3.0,
    )
    return fields_widget


async def priority_edit_context(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = await loaded_fields_widget_with_priority(pilot)
    priority_selector = fields_widget.priority_selector
    await asyncio.sleep(0.2)

    priority_selector.focus()
    await asyncio.sleep(0.2)
    return fields_widget, priority_selector, fields_widget.work_item_status_selector


async def modify_priority_field(pilot):
    _fields_widget, _priority_selector, status_selector = await priority_edit_context(pilot)
    await choose_select_option(pilot)

    status_selector.focus()
    await asyncio.sleep(0.2)


async def modify_assignee_field(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    assignee_selector = fields_widget.assignee_selector

    await asyncio.sleep(0.5)

    if assignee_selector._options and len(assignee_selector._options) > 1:
        current_value = assignee_selector.value

        for _label, value in assignee_selector._options:
            if value != current_value and value != Select.NULL:
                assignee_selector.value = value
                break
        await asyncio.sleep(0.3)

    assignee_selector.focus()
    await asyncio.sleep(0.3)


async def modify_due_date_field(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    content = fields_widget.content_container
    content.focus()
    await asyncio.sleep(0.2)

    await pilot.press('pagedown')
    await asyncio.sleep(0.3)

    due_date_field = fields_widget.work_item_due_date_field
    due_date_field.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+a')
    await asyncio.sleep(0.1)
    due_date_field.value = '2026-12-31'
    await asyncio.sleep(0.5)


async def save_priority_field_and_verify_applied(pilot):
    fields_widget, priority_selector, status_selector = await priority_edit_context(pilot)
    priority_selector.value = '2'
    await asyncio.sleep(0.3)

    await wait_until(lambda: fields_widget.has_pending_changes, timeout=3.0)
    fields_widget.action_save_work_item()

    await wait_until(lambda: not fields_widget._save_in_progress, timeout=3.0)
    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: priority_selector.original_value == '2' and priority_selector.value == '2',
        timeout=3.0,
    )
    await asyncio.sleep(0.3)

    status_selector.focus()
    await asyncio.sleep(0.2)


async def discard_priority_field_change_and_verify_restored(
    pilot, *, assert_local_only: bool = False
):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)
    priority_selector = fields_widget.priority_selector

    await wait_until(
        lambda: bool(priority_selector.value) and priority_selector.selection is not None,
        timeout=3.0,
    )
    await asyncio.sleep(0.2)

    original_value = priority_selector.original_value
    replacement_value = next(
        value
        for _label, value in priority_selector._options
        if value not in {original_value, Select.NULL}
    )

    priority_selector.value = replacement_value
    await wait_until(lambda: fields_widget.has_pending_changes, timeout=3.0)
    await wait_until(
        lambda: (
            fields_widget.discard_changes_button.display
            and fields_widget.pending_changes_button.display
        ),
        timeout=3.0,
    )

    if assert_local_only:

        async def fail_status_refresh(*_args, **_kwargs):
            raise AssertionError('Discard should not refresh applicable statuses')

        async def fail_assignable_users_refresh(*_args, **_kwargs):
            raise AssertionError('Discard should not refresh assignable users')

        fields_widget._retrieve_applicable_status_codes = fail_status_refresh
        fields_widget._retrieve_users_assignable_to_work_item = fail_assignable_users_refresh

    await pilot.press('ctrl+z')

    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: (
            not fields_widget.has_pending_changes
            and priority_selector.original_value == original_value
            and priority_selector.value == original_value
        ),
        timeout=3.0,
    )


class TestWorkItemFields:
    @with_snapshot_assertion(open_work_item_and_view_fields, terminal_size=(120, 60))
    def test_work_item_fields_initial_state(self):
        pass

    @with_snapshot_assertion(open_flagged_work_item_and_view_fields, terminal_size=(120, 60))
    def test_work_item_is_flagged(self):
        pass

    @with_snapshot_assertion_fixture(
        unflag_work_item_and_view_fields,
        fixture_name='mock_jira_api_with_unflagged_work_item_update',
        terminal_size=(120, 60),
    )
    def test_work_item_is_unflagged(self):
        pass

    @with_snapshot_assertion_fixture(
        add_work_item_watcher_and_view_fields,
        fixture_name='mock_jira_api_with_added_work_item_watcher',
        terminal_size=(120, 60),
    )
    def test_work_item_adds_watcher(self):
        pass

    @with_snapshot_assertion(modify_priority_field, terminal_size=(120, 50))
    def test_work_item_fields_with_pending_priority_change(self):
        pass

    @with_snapshot_assertion(modify_assignee_field, terminal_size=(120, 50))
    def test_work_item_fields_with_pending_assignee_change(self):
        pass

    @with_snapshot_assertion(modify_due_date_field, terminal_size=(120, 50))
    def test_work_item_fields_with_pending_due_date_change(self):
        pass

    @with_snapshot_assertion_fixture(
        save_priority_field_and_verify_applied,
        fixture_name='mock_jira_api_with_saved_work_item_field_update',
        terminal_size=(120, 50),
    )
    def test_work_item_fields_with_saved_priority_change_applied(self):
        pass

    @pytest.mark.asyncio
    async def test_work_item_fields_discard_pending_priority_change(
        self,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        async with app.run_test() as pilot:
            await discard_priority_field_change_and_verify_restored(
                pilot,
                assert_local_only=True,
            )
