from abc import abstractmethod
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from rich.text import Text
from textual.command import DiscoveryHit, Hit, Hits, Provider

from gojeera.internal.models.jira import JiraProject
from gojeera.widgets.layout.sub_palette import (
    mark_sub_command_palette_hit,
    mark_sub_command_palette_launcher_hit,
)

ProjectCallback = Callable[[], Coroutine[Any, Any, None]]


def format_project_label(project: JiraProject) -> str:
    return f'[{project.key}] {project.name}'


def build_project_discovery_hit(
    project: JiraProject,
    callback: ProjectCallback,
) -> DiscoveryHit:
    label = format_project_label(project)
    return DiscoveryHit(
        Text(label, no_wrap=True, overflow='ellipsis'),
        callback,
        text=label,
    )


def build_project_hit(
    project: JiraProject,
    score: float,
    callback: ProjectCallback,
) -> Hit:
    label = format_project_label(project)
    return Hit(
        score,
        Text(label, no_wrap=True, overflow='ellipsis'),
        callback,
        text=label,
    )


def match_project_hit(
    matcher: Any,
    query: str,
    project: JiraProject,
    callback: ProjectCallback,
) -> Hit | None:
    label = format_project_label(project)
    score = matcher.match(label)
    if score <= 0 and query.strip():
        return None
    return build_project_hit(project, score if score > 0 else 1.0, callback)


class ProjectSubPaletteProvider(Provider):
    """Shared command-palette flow for project-backed subpalettes."""

    palette_id: str
    palette_placeholder: str
    action_label: str
    action_help: str
    action_name: str

    @abstractmethod
    def _build_project_callback(self, project: JiraProject) -> ProjectCallback: ...

    @abstractmethod
    def _iter_projects(self) -> AsyncIterator[JiraProject]: ...

    def _action_callback(self):
        return lambda: self.app.run_action(self.action_name)

    def _mark_project_hit(self, hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_hit(hit, self.palette_id)

    def _mark_launcher_hit(self, hit: DiscoveryHit | Hit) -> DiscoveryHit | Hit:
        return mark_sub_command_palette_launcher_hit(
            hit,
            self.palette_id,
            self.palette_placeholder,
        )

    def _is_palette_active(self) -> bool:
        return getattr(self.app, 'active_sub_command_palette_id', None) == self.palette_id

    async def _active_projects(self) -> AsyncIterator[JiraProject]:
        if not self._is_palette_active():
            return
        async for project in self._iter_projects():
            yield project

    async def discover(self) -> Hits:
        yield self._mark_launcher_hit(
            DiscoveryHit(
                self.action_label,
                self._action_callback(),
                help=self.action_help,
            )
        )
        async for project in self._active_projects():
            yield self._mark_project_hit(
                build_project_discovery_hit(project, self._build_project_callback(project))
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        action_score = matcher.match(self.action_label)
        if action_score > 0:
            yield self._mark_launcher_hit(
                Hit(
                    action_score,
                    matcher.highlight(self.action_label),
                    self._action_callback(),
                    help=self.action_help,
                )
            )
        async for project in self._active_projects():
            hit = match_project_hit(
                matcher,
                query,
                project,
                self._build_project_callback(project),
            )
            if hit is not None:
                yield self._mark_project_hit(hit)
