import asyncio


async def wait_for_mount(pilot):
    await asyncio.sleep(0.1)


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.05):
    """Poll until a predicate becomes true or raise on timeout."""

    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        if predicate():
            return

        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError('Timed out waiting for condition')

        await asyncio.sleep(interval)
