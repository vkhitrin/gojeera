from __future__ import annotations

from textual.command import DiscoveryHit, Hit

SUB_COMMAND_PALETTE_ID_ATTRIBUTE = 'sub_command_palette_id'


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
