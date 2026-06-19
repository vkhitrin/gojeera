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

RELEASES_PALETTE_ID = 'project-releases'
RELEASES_ACTION_LABEL = 'View Releases'
RELEASES_ACTION_HELP = 'Browse Jira software project releases'
RELEASES_PALETTE_PLACEHOLDER = 'Search projects with releases…'


# TODO: (vkhitrin) consider adding caching in SQLite
class ReleaseCommandProvider(Provider):
    """Expose Jira project releases in the command palette."""

    def _build_project_callback(self, project: JiraProject):
        async def open_project_releases() -> None:
            from gojeera.app import JiraApp

            app = cast('JiraApp', self.app)
            app.active_sub_command_palette_id = None
            await app.action_view_project_releases(project.key)

        return open_project_releases

    def _build_releases_action_callback(self):
        async def show_releases_palette() -> None:
            await self.app.run_action('show_releases_palette')

        return show_releases_palette

    def _build_releases_discovery_hit(self) -> DiscoveryHit:
        return DiscoveryHit(
            RELEASES_ACTION_LABEL,
            self._build_releases_action_callback(),
            help=RELEASES_ACTION_HELP,
        )

    def _build_releases_hit(self, score: float, label: VisualType) -> Hit:
        return Hit(
            score,
            label,
            self._build_releases_action_callback(),
            help=RELEASES_ACTION_HELP,
        )

    def _is_releases_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == RELEASES_PALETTE_ID

    @staticmethod
    def _format_label(project: JiraProject) -> str:
        return f'[{project.key}] {project.name}'

    @staticmethod
    def _mark_project_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, RELEASES_PALETTE_ID)

    @staticmethod
    def _mark_releases_launcher_hit(hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_launcher_hit(
            hit,
            RELEASES_PALETTE_ID,
            RELEASES_PALETTE_PLACEHOLDER,
        )

    async def _load_projects_with_releases(self) -> list[JiraProject]:
        from gojeera.app import JiraApp

        app = cast('JiraApp', self.app)
        response = await app.api.search_projects_with_releases()
        if not response.success:
            app.notify(
                response.error or 'Failed to load projects with releases',
                title='Releases',
                severity='error',
            )
            return []
        return sorted(
            cast(list[JiraProject], response.result or []),
            key=lambda project: project.key.casefold(),
        )

    async def _get_projects_with_releases(self) -> list[JiraProject]:
        cached_projects = getattr(self, '_projects_with_releases', None)
        if cached_projects is not None:
            return cast(list[JiraProject], cached_projects)

        load_task = getattr(self, '_projects_with_releases_task', None)
        if load_task is None or load_task.cancelled():
            load_task = asyncio.create_task(self._load_projects_with_releases())
            self._projects_with_releases_task = load_task

        projects = await asyncio.shield(load_task)
        self._projects_with_releases = projects
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
        yield self._mark_releases_launcher_hit(self._build_releases_discovery_hit())

        if not self._is_releases_palette_active():
            return

        for project in await self._get_projects_with_releases():
            yield self._mark_project_hit(self._build_project_discovery_hit(project))

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(RELEASES_ACTION_LABEL)
        if action_score > 0:
            yield self._mark_releases_launcher_hit(
                self._build_releases_hit(action_score, matcher.highlight(RELEASES_ACTION_LABEL))
            )

        if not self._is_releases_palette_active():
            return

        for project in await self._get_projects_with_releases():
            label = self._format_label(project)
            score = matcher.match(label)
            if score <= 0 and query.strip():
                continue
            yield self._mark_project_hit(
                self._build_project_hit(project, score if score > 0 else 1.0)
            )
