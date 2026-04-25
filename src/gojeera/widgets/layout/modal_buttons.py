from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_modal_confirm_button(
    button_factory: Callable[..., Any],
    *,
    button_id: str,
    label: str = 'Save',
    disabled: bool = False,
) -> Any:
    return button_factory(
        label,
        variant='success',
        id=button_id,
        classes='modal-action-button modal-action-button--confirm',
        disabled=disabled,
        compact=True,
    )


def build_modal_cancel_button(
    button_factory: Callable[..., Any],
    *,
    button_id: str,
    label: str = 'Cancel',
) -> Any:
    return button_factory(
        label,
        variant='error',
        id=button_id,
        classes='modal-action-button modal-action-button--danger',
        compact=True,
    )
