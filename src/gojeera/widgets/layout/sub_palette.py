from __future__ import annotations

from textual.command import DiscoveryHit, Hit

SUB_COMMAND_PALETTE_ID_ATTRIBUTE = 'sub_command_palette_id'
SUB_COMMAND_PALETTE_LAUNCH_ATTRIBUTE = 'sub_command_palette_launch'


def mark_sub_command_palette_hit(
    hit: DiscoveryHit | Hit,
    palette_id: str,
) -> DiscoveryHit | Hit:
    """Mark a command hit as belonging to a sub command palette."""
    setattr(hit, SUB_COMMAND_PALETTE_ID_ATTRIBUTE, palette_id)
    return hit


def is_sub_command_palette_hit(hit: DiscoveryHit | Hit, palette_id: str) -> bool:
    """Return whether a command hit belongs to the requested sub command palette."""
    return getattr(hit, SUB_COMMAND_PALETTE_ID_ATTRIBUTE, None) == palette_id


def mark_sub_command_palette_launcher_hit(
    hit: DiscoveryHit | Hit,
    palette_id: str,
    placeholder: str,
) -> DiscoveryHit | Hit:
    """Mark a command hit as opening a sub command palette in place."""
    setattr(hit, SUB_COMMAND_PALETTE_LAUNCH_ATTRIBUTE, (palette_id, placeholder))
    return hit


def get_sub_command_palette_launch(hit: DiscoveryHit | Hit) -> tuple[str, str] | None:
    """Return sub command palette launch details for a command hit."""
    launch_details = getattr(hit, SUB_COMMAND_PALETTE_LAUNCH_ATTRIBUTE, None)
    if (
        isinstance(launch_details, tuple)
        and len(launch_details) == 2
        and isinstance(launch_details[0], str)
        and isinstance(launch_details[1], str)
    ):
        return launch_details
    return None
