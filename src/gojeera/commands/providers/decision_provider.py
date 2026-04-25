"""Command provider for inserting decision markers."""

from __future__ import annotations

from gojeera.commands.providers.editor_command_provider import EditorCommandProvider


class DecisionCommandProvider(EditorCommandProvider):
    """Command provider for inserting decision markers in description/comment fields."""

    command_text = 'Insert Decision'
    command_help = 'Insert a decision marker ([decision:d/a/u])'
    action_name = 'action_insert_decision'
