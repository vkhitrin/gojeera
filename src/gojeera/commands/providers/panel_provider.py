from __future__ import annotations

from gojeera.commands.providers.editor_command_provider import EditorCommandProvider


class PanelCommandProvider(EditorCommandProvider):
    """Command provider for inserting ADF panel markers in description/comment fields."""

    command_text = 'Insert Panel'
    command_help = 'Insert an ADF panel ([!NOTE], [!WARNING], etc.)'
    action_name = 'action_insert_alert'
