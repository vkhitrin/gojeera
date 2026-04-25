"""Command provider for inserting user mentions."""

from __future__ import annotations

from gojeera.commands.providers.editor_command_provider import EditorCommandProvider


class UserMentionCommandProvider(EditorCommandProvider):
    """Command provider for inserting user mentions in description/comment fields."""

    command_text = 'Insert Mention'
    command_help = 'Insert a user mention (@user)'
    action_name = 'action_insert_mention'
