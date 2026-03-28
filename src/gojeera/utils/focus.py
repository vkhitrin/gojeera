from __future__ import annotations

from textual.widget import Widget


def resolve_focus_target(widget: Widget | None) -> Widget | None:
    """Resolve a widget that should receive focus."""

    if widget is None:
        return None

    get_focus_target = getattr(widget, 'get_jumper_focus_target', None)
    if callable(get_focus_target):
        resolved_target = get_focus_target()
        if isinstance(resolved_target, Widget):
            return resolved_target

    return widget


def focus_first_available(*widgets: Widget | None) -> Widget | None:
    """Focus the first visible, enabled widget from the provided candidates."""

    for widget in widgets:
        target = resolve_focus_target(widget)
        if target is None:
            continue
        if not target.display or not target.visible:
            continue
        if getattr(target, 'disabled', False):
            continue
        if not getattr(target, 'can_focus', False):
            continue
        target.focus()
        return target

    return None
