from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import cast

from gojeera.commands.providers.project_provider import ProjectSubPaletteProvider
from gojeera.internal.models.jira import JiraProject

RELEASES_PALETTE_ID = 'project-releases'
RELEASES_ACTION_LABEL = 'View Releases'
RELEASES_ACTION_HELP = 'Browse Jira software project releases'
RELEASES_PALETTE_PLACEHOLDER = 'Search projects with releases…'


# TODO: (vkhitrin) consider adding caching in SQLite
class ReleaseCommandProvider(ProjectSubPaletteProvider):
    """Expose Jira project releases in the command palette."""

    palette_id = RELEASES_PALETTE_ID
    palette_placeholder = RELEASES_PALETTE_PLACEHOLDER
    action_label = RELEASES_ACTION_LABEL
    action_help = RELEASES_ACTION_HELP
    action_name = 'show_releases_palette'

    def _build_project_callback(self, project: JiraProject):
        async def open_project_releases() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_view_project_releases(project.key)

        return open_project_releases

    async def _load_projects_with_releases(self) -> list[JiraProject]:
        from gojeera.app import JiraApp

        app = cast('JiraApp', self.app)
        response = await app.api.search_projects_with_releases(
            on_page=self._publish_projects_with_releases,
        )
        if not response.success:
            app.notify(
                response.error or 'Failed to load projects with releases',
                title='Releases',
                severity='error',
            )
            return []
        projects = sorted(
            cast(list[JiraProject], response.result or []),
            key=lambda project: project.key.casefold(),
        )
        self._publish_projects_with_releases(projects)
        return projects

    def _publish_projects_with_releases(self, projects: list[JiraProject]) -> None:
        self._projects_with_releases_partial = sorted(
            projects,
            key=lambda project: project.key.casefold(),
        )
        self._projects_with_releases_version = (
            getattr(self, '_projects_with_releases_version', 0) + 1
        )
        event = getattr(self, '_projects_with_releases_event', None)
        if event is not None:
            event.set()

    def _projects_with_releases_load_task(self) -> asyncio.Task[list[JiraProject]]:
        load_task = getattr(self, '_projects_with_releases_task', None)
        if load_task is None or load_task.done():
            self._projects_with_releases_partial = []
            load_task = asyncio.create_task(self._load_projects_with_releases())
            self._projects_with_releases_task = load_task
        return cast(asyncio.Task[list[JiraProject]], load_task)

    async def _iter_projects_with_releases(self) -> AsyncIterator[JiraProject]:
        event = getattr(self, '_projects_with_releases_event', None)
        if event is None:
            event = asyncio.Event()
            self._projects_with_releases_event = event
        load_task = self._projects_with_releases_load_task()
        yielded_keys: set[str] = set()

        while True:
            version = getattr(self, '_projects_with_releases_version', 0)
            partial_projects = cast(
                list[JiraProject],
                getattr(self, '_projects_with_releases_partial', []),
            )
            for project in partial_projects:
                normalized_key = project.key.casefold()
                if normalized_key in yielded_keys:
                    continue
                yielded_keys.add(normalized_key)
                yield project

            if load_task.done():
                projects = await asyncio.shield(load_task)
                for project in projects:
                    normalized_key = project.key.casefold()
                    if normalized_key in yielded_keys:
                        continue
                    yielded_keys.add(normalized_key)
                    yield project
                return

            event.clear()
            if getattr(self, '_projects_with_releases_version', 0) != version:
                continue

            event_wait = asyncio.create_task(event.wait())
            try:
                await asyncio.wait(
                    (load_task, event_wait),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                if not event_wait.done():
                    event_wait.cancel()
                    await asyncio.gather(event_wait, return_exceptions=True)

    def _iter_projects(self) -> AsyncIterator[JiraProject]:
        return self._iter_projects_with_releases()
