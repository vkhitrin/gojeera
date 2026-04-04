import asyncio


async def wait_for_mount(pilot):
    await asyncio.sleep(0.1)


async def load_work_item_from_search(pilot, work_item_key: str = 'ENG-1'):
    await asyncio.sleep(0.1)
    await pilot.app.screen.fetch_work_items(work_item_key)
    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: pilot.app.screen.current_loaded_work_item_key == work_item_key,
        timeout=3.0,
    )
    await asyncio.sleep(0.3)


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.05):
    """Poll until a predicate becomes true or raise on timeout."""

    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        if predicate():
            return

        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError('Timed out waiting for condition')

        await asyncio.sleep(interval)
