import asyncio

import pytest
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp, MainScreen
from gojeera.components.new_work_item_screen import AddWorkItemScreen
from gojeera.components.work_item_subtasks import WorkItemChildWorkItemsWidget


async def select_work_item_and_highlight_subtask(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    subtasks_widget = pilot.app.screen.query_one(WorkItemChildWorkItemsWidget)
    subtasks_widget.data_table.focus()
    await asyncio.sleep(0.3)


async def create_subtask_and_verify(pilot):
    await asyncio.sleep(0.1)
    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)
    await pilot.press('enter')
    await asyncio.sleep(0.8)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.2)
    await pilot.press('right')
    await asyncio.sleep(0.5)

    subtasks_widget = pilot.app.screen.query_one(WorkItemChildWorkItemsWidget)

    await asyncio.sleep(0.5)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.3)

    initial_count = subtasks_widget.displayed_count

    subtasks_widget.focus()
    await asyncio.sleep(0.2)

    await pilot.press('ctrl+n')
    await asyncio.sleep(0.5)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.8)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    screen._lazy_load_work_item_types()
    await asyncio.sleep(0.5)

    assert screen._parent_work_item_key == 'EXAMPLE-19539', (
        f'Expected parent work item key to be EXAMPLE-19539, got {screen._parent_work_item_key}'
    )

    work_item_type_value = screen.work_item_type_selector.value

    if work_item_type_value != '10002':
        screen.work_item_type_selector.value = '10002'
        await asyncio.sleep(0.3)

    summary_field = screen.summary_field
    summary_field.focus()
    await asyncio.sleep(0.1)

    await pilot.press(*'Test new subtask')
    await asyncio.sleep(0.3)

    await pilot.press('tab')
    await asyncio.sleep(0.3)

    assert not screen.save_button.disabled, 'Save button should be enabled'

    screen.save_button.press()

    await asyncio.sleep(1.5)

    assert not isinstance(pilot.app.screen, AddWorkItemScreen), (
        f'Expected to leave AddWorkItemScreen, got {type(pilot.app.screen)}'
    )

    await asyncio.sleep(1.0)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    main_screen = pilot.app.screen
    assert isinstance(main_screen, MainScreen), (
        f'Expected to return to MainScreen, got {type(main_screen)}'
    )

    subtasks_widget = main_screen.query_one(WorkItemChildWorkItemsWidget)
    final_count = subtasks_widget.displayed_count

    assert final_count == initial_count + 1, (
        f'Expected {initial_count + 1} subtasks, got {final_count}'
    )

    assert subtasks_widget.work_items is not None, 'Expected work_items to be populated'
    new_subtask = subtasks_widget.work_items[-1]
    assert new_subtask.cleaned_summary().startswith('Test new subtask'), (
        f'Expected summary to start with "Test new subtask", got "{new_subtask.cleaned_summary()}"'
    )


class TestWorkItemSubtasks:
    def test_work_item_subtasks_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=select_work_item_and_highlight_subtask,
        )

    @pytest.mark.filterwarnings('always::UserWarning')
    def test_create_subtask_and_verify_in_table(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_subtask_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=create_subtask_and_verify)
