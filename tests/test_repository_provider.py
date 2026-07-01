from types import SimpleNamespace
from typing import Any, cast

import pytest

from gojeera.commands.providers.repository_provider import RepositoryCommandProvider
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraProject


@pytest.mark.asyncio
async def test_repository_provider_loads_software_projects_without_feature_scan():
    calls = []

    class FakeAPI:
        async def search_projects(self, **kwargs):
            calls.append(('search_projects', kwargs))
            return APIControllerResponse(
                result=[
                    JiraProject(id='2', key='WEB', name='Web', project_type_key='software'),
                    JiraProject(id='1', key='ENG', name='Engineering', project_type_key='software'),
                ]
            )

    app = SimpleNamespace(api=FakeAPI(), notify=lambda *args, **kwargs: None)
    screen = SimpleNamespace(app=app)
    provider = RepositoryCommandProvider(cast(Any, screen))

    projects = await provider._load_projects()

    assert calls == [('search_projects', {'project_type_key': 'software'})]
    assert [project.key for project in projects] == ['ENG', 'WEB']
