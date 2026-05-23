from __future__ import annotations

from dataclasses import dataclass

from gojeera.internal.models.jira import JiraGlobalSettings, JiraMyselfInfo, JiraServerInfo


@dataclass
class AtlassianContext:
    """Runtime-derived Atlassian context for the current application process."""

    server_info: JiraServerInfo | None = None
    global_settings: JiraGlobalSettings | None = None
    user_info: JiraMyselfInfo | None = None
