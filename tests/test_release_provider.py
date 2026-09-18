import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest

from gojeera.commands.providers.release_provider import ReleaseCommandProvider
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraProject


@pytest.mark.asyncio
async def test_release_provider_yields_projects_as_checks_complete():
    release_second_project = asyncio.Event()
    first_project = JiraProject(id='1', key='ENG', name='Engineering')
    second_project = JiraProject(id='2', key='OPS', name='Operations')

    class FakeAPI:
        async def search_projects_with_releases(self, on_page=None):
            assert on_page is not None
            on_page([first_project])
            await release_second_project.wait()
            on_page([first_project, second_project])
            return APIControllerResponse(result=[first_project, second_project])

    app = SimpleNamespace(api=FakeAPI(), notify=lambda *args, **kwargs: None)
    screen = SimpleNamespace(app=app)
    provider = ReleaseCommandProvider(cast(Any, screen))
    projects = provider._iter_projects_with_releases()

    first_result = await anext(projects)

    assert first_result is first_project
    assert not provider._projects_with_releases_task.done()

    release_second_project.set()
    second_result = await anext(projects)

    assert second_result is second_project
    with pytest.raises(StopAsyncIteration):
        await anext(projects)
