import asyncio

from gojeera.components.screens.parent_work_item_screen import ParentWorkItemScreen

from .test_helpers import (
    load_work_item_from_search,
    wait_until,
    with_snapshot_assertion,
)


async def open_parent_work_item_screen(pilot):
    await load_work_item_from_search(pilot, 'ENG-3')

    work_item = pilot.app.information_panel.work_item
    assert work_item is not None

    await pilot.app.push_screen(ParentWorkItemScreen(work_item=work_item))
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, ParentWorkItemScreen)
    assert pilot.app.screen.parent_input.has_focus
    assert pilot.app.screen.apply_button.disabled


async def select_parent_work_item_and_enable_set(pilot):
    await open_parent_work_item_screen(pilot)

    parent_input = pilot.app.screen.parent_input
    parent_input.value = 'ENG-9'
    await asyncio.sleep(0.2)
    await wait_until(lambda: not pilot.app.screen.apply_button.disabled, timeout=3.0)

    assert isinstance(pilot.app.screen, ParentWorkItemScreen)
    assert not pilot.app.screen.apply_button.disabled


class TestParentWorkItemScreen:
    @with_snapshot_assertion(open_parent_work_item_screen, terminal_size=(120, 40))
    def test_parent_work_item_screen_initial_state(self): ...

    @with_snapshot_assertion(select_parent_work_item_and_enable_set, terminal_size=(120, 40))
    def test_parent_work_item_screen_with_selected_parent(self): ...
