import asyncio

from .test_helpers import open_first_work_item_from_search, with_snapshot_assertion


async def open_loaded_work_item_and_show_jumper(pilot):
    await open_first_work_item_from_search(pilot)

    await pilot.press('ctrl+backslash')
    await asyncio.sleep(0.3)


class TestJumper:
    @with_snapshot_assertion(open_loaded_work_item_and_show_jumper, terminal_size=(120, 40))
    def test_main_screen_jumper_overlay(self): ...
