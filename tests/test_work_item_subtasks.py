import pytest

from gojeera.app import JiraApp
from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen
from gojeera.components.work_item.work_item_subtasks import WorkItemChildWorkItemsWidget

from .test_helpers import (
    assert_main_screen,
    assert_snapshot_matches,
    focus_work_item_tab,
    wait_for_screen_to_settle,
    wait_for_worker_idle,
    wait_until,
)


async def open_subtasks_widget(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-4', right_presses=2)

    return pilot.app.screen.query_one(WorkItemChildWorkItemsWidget)


async def select_work_item_and_highlight_subtask(pilot):
    subtasks_widget = await open_subtasks_widget(pilot)
    subtasks_widget.record_list.focus()
    await pilot.pause()


async def create_subtask_and_verify(pilot):
    subtasks_widget = await open_subtasks_widget(pilot)
    await wait_for_worker_idle(pilot)
    await wait_until(lambda: not subtasks_widget.is_loading, timeout=3.0)

    initial_count = subtasks_widget.displayed_count

    subtasks_widget.focus()
    await pilot.pause()

    await pilot.press('ctrl+n')
    await wait_until(lambda: isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)

    await wait_for_worker_idle(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemScreen), f'Expected AddWorkItemScreen, got {type(screen)}'

    screen._lazy_load_work_item_types()
    await wait_until(
        lambda: screen.work_item_type_selector.prompt == 'Select a work item type',
        timeout=3.0,
    )

    assert screen._parent_work_item_key == 'ENG-4', (
        f'Expected parent work item key to be ENG-4, got {screen._parent_work_item_key}'
    )

    work_item_type_value = screen.work_item_type_selector.value

    if work_item_type_value != '10002':
        screen.work_item_type_selector.value = '10002'
        await wait_until(lambda: screen.work_item_type_selector.value == '10002', timeout=3.0)

    summary_field = screen.summary_field
    summary_field.focus()
    await pilot.pause()

    await pilot.press(*'Test new subtask')
    await wait_until(lambda: summary_field.value == 'Test new subtask', timeout=3.0)

    await pilot.press('tab')
    await pilot.pause()

    assert not screen.save_button.disabled, 'Save button should be enabled'

    screen.save_button.press()
    await wait_until(lambda: not isinstance(pilot.app.screen, AddWorkItemScreen), timeout=3.0)
    await wait_for_screen_to_settle(pilot)

    assert not isinstance(pilot.app.screen, AddWorkItemScreen), (
        f'Expected to leave AddWorkItemScreen, got {type(pilot.app.screen)}'
    )

    await wait_for_worker_idle(pilot)

    main_screen = assert_main_screen(pilot.app)

    await main_screen.retrieve_work_item_subtasks('ENG-4')
    await wait_for_worker_idle(pilot)
    subtasks_widget = main_screen.query_one(WorkItemChildWorkItemsWidget)
    await wait_until(
        lambda: subtasks_widget.displayed_count == initial_count + 1,
        timeout=3.0,
    )
    final_count = subtasks_widget.displayed_count

    assert final_count == initial_count + 1, (
        f'Expected {initial_count + 1} subtasks, got {final_count}'
    )

    assert subtasks_widget.work_items is not None, 'Expected work_items to be populated'
    new_subtask = subtasks_widget.work_items[-1]
    assert new_subtask.cleaned_summary().startswith('Test new subtask'), (
        f'Expected summary to start with "Test new subtask", got "{new_subtask.cleaned_summary()}"'
    )


HIGHLIGHT = select_work_item_and_highlight_subtask
CREATE = create_subtask_and_verify


class TestWorkItemSubtasks:
    def test_work_item_subtasks_row_highlighted(
        self, snap_compare, mock_configuration, mock_jira_api_with_search_results, mock_user_info
    ):
        assert_snapshot_matches(snap_compare, mock_configuration, mock_user_info, HIGHLIGHT)

    @pytest.mark.filterwarnings('always::UserWarning')
    def test_create_subtask(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_subtask_creation,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        assert snap_compare(app, terminal_size=(120, 40), run_before=CREATE)
