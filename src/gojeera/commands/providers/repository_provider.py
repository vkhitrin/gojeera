from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast

from gojeera.commands.providers import project_provider
from gojeera.internal.models.jira import JiraProject

REPOSITORIES_PALETTE_ID = 'project-repositories'
REPOSITORIES_ACTION_LABEL = 'View Repositories'
REPOSITORIES_ACTION_HELP = 'Browse repositories associated with a Jira project'
REPOSITORIES_PALETTE_PLACEHOLDER = 'Search projects for repositories...'


class RepositoryCommandProvider(project_provider.ProjectSubPaletteProvider):
    """Expose project repository lookup in the command palette."""

    palette_id = REPOSITORIES_PALETTE_ID
    palette_placeholder = REPOSITORIES_PALETTE_PLACEHOLDER
    action_label = REPOSITORIES_ACTION_LABEL
    action_help = REPOSITORIES_ACTION_HELP
    action_name = 'show_repositories_palette'

    def _build_project_callback(self, project: JiraProject):
        async def open_project_repositories() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_view_project_repositories(project.key)

        return open_project_repositories

    async def _load_projects(self) -> list[JiraProject]:
        from gojeera.app import JiraApp

        app = cast('JiraApp', self.app)
        response = await app.api.search_projects(project_type_key='software')
        if not response.success:
            app.notify(
                response.error or 'Failed to load projects',
                severity='error',
            )
            return []
        return sorted(
            cast(list[JiraProject], response.result or []),
            key=lambda project: project.key.casefold(),
        )

    async def _get_projects(self) -> list[JiraProject]:
        cached_projects = getattr(self, '_repository_projects', None)
        if cached_projects is not None:
            return cast(list[JiraProject], cached_projects)

        load_task = getattr(self, '_repository_projects_task', None)
        if load_task is None or load_task.cancelled():
            load_task = asyncio.create_task(self._load_projects())
            self._repository_projects_task = load_task

        projects = await asyncio.shield(load_task)
        self._repository_projects = projects
        return projects

    async def _iter_projects(self) -> AsyncIterator[JiraProject]:
        for project in await self._get_projects():
            yield project
