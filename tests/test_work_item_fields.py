import asyncio

from textual.widgets import Select

from gojeera.app import JiraApp
from gojeera.components.work_item_fields import WorkItemFields


async def open_work_item_and_view_fields(pilot):

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.3)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    status_selector = fields_widget.work_item_status_selector
    status_selector.focus()
    await asyncio.sleep(0.3)


async def modify_priority_field(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    priority_selector = fields_widget.priority_selector

    await asyncio.sleep(0.5)

    if priority_selector._options and len(priority_selector._options) > 1:
        priority_selector.value = '10001'
        await asyncio.sleep(0.3)

    priority_selector.focus()
    await asyncio.sleep(0.3)


async def modify_assignee_field(pilot):
    await open_work_item_and_view_fields(pilot)

    fields_widget = pilot.app.screen.query_one(WorkItemFields)

    assignee_selector = fields_widget.assignee_selector

    await asyncio.sleep(0.5)

    if assignee_selector._options and len(assignee_selector._options) > 1:
        current_value = assignee_selector.value

        for _label, value in assignee_selector._options:
            if value != current_value and value != Select.BLANK:
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


class TestWorkItemFields:
    def test_work_item_fields_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=open_work_item_and_view_fields)

    def test_work_item_fields_with_pending_priority_change(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=modify_priority_field)

    def test_work_item_fields_with_pending_assignee_change(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=modify_assignee_field)

    def test_work_item_fields_with_pending_due_date_change(
        self,
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_search_with_results,
        mock_jira_api_with_search_results,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=modify_due_date_field)
