from __future__ import annotations

from typing import Any, Callable

from textual.widgets import TextArea


async def insert_picker_markup(
    *,
    app: Any,
    textarea: TextArea,
    picker_screen: Any,
    build_insertion_text: Callable[[Any], str],
) -> None:
    cursor_position = textarea.cursor_location
    result = await app.push_screen_wait(picker_screen)
    if not result:
        return

    textarea.focus()
    textarea.move_cursor(cursor_position)
    textarea.insert(build_insertion_text(result))


async def insert_picker_markup_from_getter(
    *,
    app: Any,
    get_textarea: Callable[[], TextArea],
    picker_screen: Any,
    build_insertion_text: Callable[[Any], str],
    logger: Any,
    error_context: str = 'TextArea',
) -> None:
    try:
        textarea = get_textarea()
    except Exception:
        logger.error('Failed to get %s', error_context, exc_info=True)
        return

    await insert_picker_markup(
        app=app,
        textarea=textarea,
        picker_screen=picker_screen,
        build_insertion_text=build_insertion_text,
    )
