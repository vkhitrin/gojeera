from __future__ import annotations

import asyncio
from typing import cast

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.visual import VisualType

from gojeera.internal.models.jira import JiraProject
from gojeera.widgets.layout.sub_palette import (
    mark_sub_command_palette_hit,
    mark_sub_command_palette_launcher_hit,
)

REPOSITORIES_PALETTE_ID = 'project-repositories'
REPOSITORIES_ACTION_LABEL = 'View Repositories'
REPOSITORIES_ACTION_HELP = 'Browse repositories associated with a Jira project'
REPOSITORIES_PALETTE_PLACEHOLDER = 'Search projects for repositories...'


class RepositoryCommandProvider(Provider):
    """Expose project repository lookup in the command palette."""

    def _build_project_callback(self, project: JiraProject):
        async def open_project_repositories() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_view_project_repositories(project.key)

        return open_project_repositories

    def _build_repositories_action_callback(self):
        async def show_repositories_palette() -> None:
            await self.app.run_action('show_repositories_palette')

        return show_repositories_palette

    def _build_repositories_discovery_hit(self) -> DiscoveryHit:
        return DiscoveryHit(
            REPOSITORIES_ACTION_LABEL,
            self._build_repositories_action_callback(),
            help=REPOSITORIES_ACTION_HELP,
        )

    def _build_repositories_hit(self, score: float, label: VisualType) -> Hit:
        return Hit(
            score,
            label,
            self._build_repositories_action_callback(),
            help=REPOSITORIES_ACTION_HELP,
        )

    def _is_repositories_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == REPOSITORIES_PALETTE_ID

    @staticmethod
    def _format_label(project: JiraProject) -> str:
        return f'[{project.key}] {project.name}'

    @staticmethod
    def _mark_project_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, REPOSITORIES_PALETTE_ID)

    @staticmethod
    def _mark_repositories_launcher_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_launcher_hit(
            hit,
            REPOSITORIES_PALETTE_ID,
            REPOSITORIES_PALETTE_PLACEHOLDER,
        )

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

    def _build_project_discovery_hit(self, project: JiraProject) -> DiscoveryHit:
        label = self._format_label(project)
        return DiscoveryHit(
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_project_callback(project),
            text=label,
        )

    def _build_project_hit(self, project: JiraProject, score: float) -> Hit:
        label = self._format_label(project)
        return Hit(
            score,
            Text(label, no_wrap=True, overflow='ellipsis'),
            self._build_project_callback(project),
            text=label,
        )

    async def discover(self) -> Hits:
        yield self._mark_repositories_launcher_hit(self._build_repositories_discovery_hit())

        if not self._is_repositories_palette_active():
            return

        for project in await self._get_projects():
            yield self._mark_project_hit(self._build_project_discovery_hit(project))

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(REPOSITORIES_ACTION_LABEL)
        if action_score > 0:
            yield self._mark_repositories_launcher_hit(
                self._build_repositories_hit(
                    action_score,
                    matcher.highlight(REPOSITORIES_ACTION_LABEL),
                )
            )

        if not self._is_repositories_palette_active():
            return

        for project in await self._get_projects():
            label = self._format_label(project)
            score = matcher.match(label)
            if score <= 0 and query.strip():
                continue
            yield self._mark_project_hit(
                self._build_project_hit(project, score if score > 0 else 1.0)
            )
