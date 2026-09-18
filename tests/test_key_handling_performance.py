from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from textual.command import Command, CommandInput, CommandList, Hit
from textual.widget import Widget
from textual.widgets import Static

from gojeera.app import JiraApp
from gojeera.commands.providers.jql_filters_provider import (
    JQL_FILTERS_PALETTE_PLACEHOLDER,
    JQLFiltersProvider,
)
from gojeera.components.work_item.work_item_fields import WorkItemFields
from gojeera.widgets.layout.record_list import Record
from gojeera.widgets.navigation.extended_jumper import ExtendedJumper
from gojeera.widgets.navigation.extended_palette import ExtendedPalette
from gojeera.widgets.search.work_item_search_results_scroll import WorkItemSearchResultsScroll
from tests.test_helpers import wait_until
from tests.test_work_item_fields import priority_edit_context

pytestmark = pytest.mark.usefixtures('mock_jira_api_sync')


class DirtyValueWidget(Widget):
    def __init__(self, changed: bool) -> None:
        super().__init__()
        self.changed = changed
        self.change_checks = 0
        self.update_enabled = True

    @property
    def value_has_changed(self) -> bool:
        self.change_checks += 1
        return self.changed


async def test_search_control_state_updates_only_when_key_handling_changes_it(
    jira_app,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        search_bar = app.unified_search_bar
        set_search_mode = Mock(wraps=app.search_results_container.set_search_mode)
        app.search_results_container.set_search_mode = set_search_mode

        search_bar.mode_selector.value = 'text'
        await pilot.pause()
        set_search_mode.reset_mock()

        search_bar.unified_input.value = 'a'
        await pilot.pause()
        search_bar.unified_input.value = 'ab'
        await pilot.pause()
        search_bar.unified_input.value = 'abc'
        await pilot.pause()

        set_search_mode.assert_not_called()

        search_bar.mode_selector.value = 'jql'
        await pilot.pause()
        set_search_mode.reset_mock()

        search_bar.unified_input.value = ''
        await pilot.pause()
        search_bar.unified_input.value = 'p'
        await pilot.pause()
        search_bar.unified_input.value = 'project'
        await pilot.pause()

        assert set_search_mode.call_count == 2
        assert set_search_mode.call_args_list[0].args == ('jql', {'mode': 'jql', 'jql': ''})
        assert set_search_mode.call_args_list[1].args == ('jql', {'mode': 'jql', 'jql': 'p'})


def test_command_palette_ranking_uses_precomputed_loaded_prefix() -> None:
    loaded_command = Command(
        'Loaded work item',
        Hit(1, 'Loaded work item', lambda: None, text='ENG-1 > Open'),
    )
    other_command = Command(
        'Other work item',
        Hit(2, 'Other work item', lambda: None, text='ENG-2 > Open'),
    )

    assert ExtendedPalette._is_loaded_work_item_command(loaded_command, 'ENG-1 > ')
    assert not ExtendedPalette._is_loaded_work_item_command(other_command, 'ENG-1 > ')
    assert not ExtendedPalette._is_loaded_work_item_command(loaded_command, None)


async def test_command_palette_ignores_whitespace_only_query_changes(
    jira_app,
    monkeypatch,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        app.action_command_palette()
        await pilot.pause()
        assert isinstance(app.screen, ExtendedPalette)
        palette = app.screen
        app.action_show_jql_filters_palette()
        await pilot.pause()

        assert len(palette._providers) == 1
        assert isinstance(palette._providers[0], JQLFiltersProvider)
        assert palette.query_one(CommandInput).placeholder == JQL_FILTERS_PALETTE_PLACEHOLDER

        gather_commands = Mock()
        warning_updates = Mock()
        monkeypatch.setattr(palette, '_gather_commands', gather_commands)
        monkeypatch.setattr(palette, '_set_result_limit_warning', warning_updates)
        palette.query_one(CommandInput).value = ' '
        await pilot.pause()

        gather_commands.assert_not_called()
        warning_updates.assert_not_called()

        palette.query_one(CommandInput).value = ' open '
        await pilot.pause()

        gather_commands.assert_called_once_with('open')
        warning_updates.assert_not_called()

        app.action_show_main_command_palette()
        await pilot.pause()

        assert len(palette._providers) > 1


async def test_jql_filter_limit_warning_is_rendered_below_results(
    mock_configuration,
    mock_user_info,
) -> None:
    mock_configuration.jql_filters = [
        {
            'label': f'Filter {index}',
            'expression': f'project = ENG AND key != ENG-{index}',
        }
        for index in range(125)
    ]
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

    async with app.run_test() as pilot:
        app.action_command_palette()
        await pilot.pause()
        warning = app.screen.query_one('#--result-limit-warning', Static)

        assert not warning.display
        assert not warning.has_class('--active')

        app.action_show_jql_filters_palette()
        command_list = app.screen.query_one(CommandList)
        command_input = app.screen.query_one(CommandInput)
        assert warning.display
        assert warning.has_class('--prepared')
        await wait_until(
            lambda: command_list.option_count == 100 and warning.has_class('--active'),
            timeout=3.0,
        )

        input_y_with_warning = command_input.region.y
        assert warning.display
        assert str(warning.render()) == '100-result limit: showing 100 of 125 matches.'
        assert len(str(warning.render())) <= warning.content_region.width
        assert warning.region.y == command_list.region.bottom
        assert warning.region.x == command_list.region.x
        warning_background = warning.styles.background
        assert warning_background.r > 200
        assert warning_background.g > 100
        assert warning_background.b < 100
        assert command_list.highlighted == 0

        command_input.value = 'ENG'
        await pilot.pause()

        assert warning.display
        assert warning.has_class('--active')
        assert warning.region.x == command_list.region.x
        assert command_input.region.y == input_y_with_warning

        command_input.value = 'ENG-124'
        await wait_until(lambda: command_list.option_count == 1, timeout=3.0)
        await pilot.pause()

        assert warning.display
        assert not warning.has_class('--active')
        assert command_input.region.y == input_y_with_warning

        app.action_command_palette()
        await pilot.pause()
        app.action_show_jql_filters_palette()
        await pilot.pause()

        directly_opened_warning = app.screen.query_one('#--result-limit-warning', Static)
        directly_opened_list = app.screen.query_one(CommandList)
        await wait_until(
            lambda: (
                directly_opened_list.option_count == 100
                and directly_opened_warning.has_class('--active')
            ),
            timeout=3.0,
        )

        assert directly_opened_warning.region.width > 0
        assert directly_opened_warning.region.x == directly_opened_list.region.x
        assert directly_opened_warning.region.y == directly_opened_list.region.bottom


async def test_binding_refresh_requests_are_coalesced_and_skipped_with_hidden_footer(
    jira_app,
    mock_configuration,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        refresh_bindings = Mock()
        app.refresh_bindings = refresh_bindings

        app.request_bindings_refresh()
        app.request_bindings_refresh()
        app.request_bindings_refresh()
        await pilot.pause()

        refresh_bindings.assert_called_once_with()

        mock_configuration.show_footer = False
        app.request_bindings_refresh()
        await pilot.pause()

        refresh_bindings.assert_called_once_with()


async def test_detail_tab_keys_move_focus_with_the_active_content(
    jira_app,
    monkeypatch,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        await app._ensure_work_item_details_mounted()
        app.details_tabs_row.display = True
        app.tabs.disabled = False

        description_scroll = app.work_item_info_container.description_container
        attachments_list = app.work_item_attachments_widget.record_list
        attachments_list.set_records(
            [Record(key='attachment-1', title='Attachment', meta='', footer='')]
        )
        app.tabs.active = 'tab-description'
        await pilot.pause()

        description_scroll.focus()
        await pilot.press(']')
        await wait_until(
            lambda: app.tabs.active == 'tab-attachments' and app.focused is attachments_list,
            timeout=1.0,
        )

        await pilot.press('[')
        await wait_until(
            lambda: app.tabs.active == 'tab-description' and app.focused is description_scroll,
            timeout=1.0,
        )

        attachments_list.clear_records()
        await pilot.press(']')
        await wait_until(
            lambda: app.tabs.active == 'tab-attachments' and app.focused is app.tabs.tabs_widget,
            timeout=1.0,
        )

        attachments_list.set_records(
            [Record(key='attachment-2', title='Attachment', meta='', footer='')]
        )
        await pilot.pause()
        attachments_list.focus()
        await pilot.pause()
        monkeypatch.setattr(app, 'load_work_item', AsyncMock(return_value=True))
        await app.work_item_attachments_widget._load_work_item_and_activate_tab('ENG-2')
        await pilot.pause()
        await wait_until(
            lambda: app.tabs.active == 'tab-description' and app.focused is description_scroll,
            timeout=1.0,
        )


def test_search_result_navigation_repaints_only_changed_rows_and_ignores_boundaries() -> None:
    results = WorkItemSearchResultsScroll()
    results._rows = [
        SimpleNamespace(work_item_key='ENG-1'),
        SimpleNamespace(work_item_key='ENG-2'),
    ]
    results._selected_index = 0
    results._refresh_row_indices = Mock()
    results._scroll_to_index = Mock()

    results.action_cursor_down()

    results._refresh_row_indices.assert_called_once_with(0, 1)
    results._scroll_to_index.assert_called_once_with(1)
    assert results.current_work_item_key == 'ENG-2'

    results.action_cursor_down()

    results._refresh_row_indices.assert_called_once_with(0, 1)
    results._scroll_to_index.assert_called_once_with(1)


def test_jumper_collects_candidates_with_one_widget_tree_walk(monkeypatch) -> None:
    lower_child = SimpleNamespace(jump_mode='focus', can_focus=True, id='lower', offset=(2, 3))
    upper_child = SimpleNamespace(jump_mode='focus', can_focus=True, id='upper', offset=(4, 1))
    upper_child_duplicate = SimpleNamespace(
        jump_mode='focus', can_focus=True, id='upper-child', offset=(4, 1)
    )
    screen = SimpleNamespace(
        walk_children=Mock(return_value=[lower_child, upper_child, upper_child_duplicate]),
        get_offset=Mock(side_effect=lambda child: child.offset),
    )
    jumper = ExtendedJumper(keys=['a', 's'])
    monkeypatch.setattr(ExtendedJumper, 'screen', property(lambda _self: screen))
    monkeypatch.setattr(jumper, '_is_widget_jumpable', lambda _widget: True)

    overlays = jumper.get_overlays()

    screen.walk_children.assert_called_once_with(Widget)
    assert [(offset.x, offset.y) for offset in overlays] == [(4, 1), (2, 3)]
    assert [jump_info.key for jump_info in overlays.values()] == ['a', 's']
    assert next(iter(overlays.values())).widget is upper_child_duplicate


def test_pending_change_update_checks_only_the_changed_field() -> None:
    fields = WorkItemFields()
    changed_target = DirtyValueWidget(changed=True)
    existing_dirty_target = DirtyValueWidget(changed=True)
    fields._pending_change_target_labels = {
        changed_target: None,
        existing_dirty_target: None,
    }
    fields._dirty_pending_change_targets = {existing_dirty_target}
    fields._pending_change_sources = {changed_target}

    fields._update_pending_change_sources()

    assert changed_target in fields._dirty_pending_change_targets
    assert existing_dirty_target in fields._dirty_pending_change_targets
    assert changed_target.change_checks == 1
    assert existing_dirty_target.change_checks == 0

    changed_target.changed = False
    fields._update_pending_change_sources()

    assert changed_target not in fields._dirty_pending_change_targets
    assert existing_dirty_target in fields._dirty_pending_change_targets
    assert changed_target.change_checks == 2
    assert existing_dirty_target.change_checks == 0


def test_unknown_pending_change_source_falls_back_to_full_scan() -> None:
    fields = WorkItemFields()
    first_target = DirtyValueWidget(changed=True)
    second_target = DirtyValueWidget(changed=False)
    fields._pending_change_target_labels = {
        first_target: None,
        second_target: None,
    }
    fields._pending_change_sources = {Widget()}

    fields._update_pending_change_sources()

    assert fields._pending_change_full_scan_requested
    assert fields._dirty_pending_change_targets == {first_target}
    assert first_target.change_checks == 1
    assert second_target.change_checks == 1


async def test_incremental_field_tracking_preserves_edit_revert_and_label_state(
    mock_configuration,
    mock_jira_api_with_search_results,
    mock_user_info,
) -> None:
    del mock_jira_api_with_search_results
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

    async with app.run_test() as pilot:
        fields, priority, _status = await priority_edit_context(pilot)
        original_priority = priority.original_value
        replacement_priority = next(
            value for _label, value in priority._options if value not in {original_priority, None}
        )
        priority_label = fields._static_field_labels()['priority-field-container']

        priority.value = replacement_priority
        await wait_until(lambda: fields.has_pending_changes, timeout=3.0)

        assert priority in fields._dirty_pending_change_targets
        assert priority_label.has_class('pending_field_label')

        priority.value = original_priority
        await wait_until(lambda: not fields.has_pending_changes, timeout=3.0)

        assert priority not in fields._dirty_pending_change_targets
        assert not priority_label.has_class('pending_field_label')

        due_date = fields.work_item_due_date_field
        original_due_date = due_date.original_value
        replacement_due_date = '2030-01-01' if original_due_date != '2030-01-01' else '2031-01-01'
        due_date.update_enabled = True
        due_date.value = replacement_due_date
        await pilot.pause()
        assert due_date.value_has_changed
        assert due_date in fields._pending_change_targets()
        await wait_until(lambda: fields.has_pending_changes, timeout=3.0)

        assert due_date in fields._dirty_pending_change_targets

        due_date.value = original_due_date or ''
        await wait_until(lambda: not fields.has_pending_changes, timeout=3.0)

        assert due_date not in fields._dirty_pending_change_targets
