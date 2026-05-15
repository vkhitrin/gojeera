import asyncio

import pytest
from textual.widgets import Select

from gojeera.app import JiraApp
from gojeera.components.work_item.work_item_fields import WorkItemFields

from .test_helpers import (
    choose_select_option,
    load_work_item_from_search,
    wait_until,
    with_snapshot_assertion,
    with_snapshot_assertion_fixture,
)


async def open_work_item_and_view_fields(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    await pilot.app.workers.wait_for_complete()

    fields_widget = pilot.app.screen.query_one(WorkItemFields)
    await wait_until(
        lambda: (
            bool(fields_widget.priority_selector.value)
            and fields_widget.priority_selector.selection is not None
        ),
        timeout=3.0,
    )
    await asyncio.sleep(0.3)

    status_selector = fields_widget.work_item_status_selector
    status_selector.focus()
    await asyncio.sleep(0.3)


async def modify_priority_field(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    priority_selector = fields_widget.priority_selector
    status_selector = fields_widget.work_item_status_selector

    await wait_until(
        lambda: bool(priority_selector.value) and priority_selector.selection is not None,
        timeout=3.0,
    )
    await asyncio.sleep(0.2)

    priority_selector.focus()
    await asyncio.sleep(0.2)
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
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    priority_selector = fields_widget.priority_selector
    status_selector = fields_widget.work_item_status_selector

    await wait_until(
        lambda: bool(priority_selector.value) and priority_selector.selection is not None,
        timeout=3.0,
    )
    await asyncio.sleep(0.2)

    priority_selector.focus()
    await asyncio.sleep(0.2)
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
