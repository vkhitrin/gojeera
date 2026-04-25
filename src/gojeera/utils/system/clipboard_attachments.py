from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from textual.widgets import TextArea

from gojeera.internal.models.jira import Attachment
from gojeera.utils.system.clipboard import (
    ClipboardAttachmentError,
    build_staged_attachment_reference_text,
    materialize_staged_attachment_references,
    prepare_staged_attachment_text,
    stage_clipboard_attachments,
)

if TYPE_CHECKING:
    from gojeera.app import JiraApp


def stage_clipboard_attachments_with_feedback(
    *,
    notify: Callable[..., None],
    stage_attachments: Callable[[], list[Path]] | None = None,
) -> list[Path] | None:
    stage_attachments = stage_attachments or stage_clipboard_attachments
    try:
        staged_paths = stage_attachments()
    except ClipboardAttachmentError as error:
        notify(str(error), severity='warning')
        return None

    if not staged_paths:
        notify(
            'Clipboard does not contain a supported file path or text payload.',
            severity='warning',
        )
        return None

    return staged_paths


def insert_staged_clipboard_attachments(
    *,
    staged_paths: list[Path],
    textarea: TextArea,
    clipboard_attachment_paths: list[Path],
    clipboard_attachment_names: list[str],
    notify: Callable[..., None],
    title: str | None = None,
) -> None:
    clipboard_attachment_paths.extend(staged_paths)
    clipboard_attachment_names.extend(path.name for path in staged_paths)

    references = '\n'.join(build_staged_attachment_reference_text() for _ in staged_paths)
    textarea.focus()
    textarea.insert(references)

    attachment_label = 'attachment' if len(staged_paths) == 1 else 'attachments'
    notify(
        f'Staged {len(staged_paths)} clipboard {attachment_label} for upload.',
        title=title,
    )


def stage_clipboard_attachments_into_textarea(
    *,
    textarea: TextArea,
    clipboard_attachment_paths: list[Path],
    clipboard_attachment_names: list[str],
    notify: Callable[..., None],
    title: str | None = None,
    stage_attachments: Callable[[], list[Path]] | None = None,
) -> bool:
    staged_paths = stage_clipboard_attachments_with_feedback(
        notify=notify,
        stage_attachments=stage_attachments,
    )
    if not staged_paths:
        return False

    insert_staged_clipboard_attachments(
        staged_paths=staged_paths,
        textarea=textarea,
        clipboard_attachment_paths=clipboard_attachment_paths,
        clipboard_attachment_names=clipboard_attachment_names,
        notify=notify,
        title=title,
    )
    return True


def cleanup_staged_clipboard_attachments(
    *,
    clipboard_attachment_paths: list[Path],
    clipboard_attachment_names: list[str],
    uploaded_clipboard_attachments: list[Attachment],
) -> None:
    for path in clipboard_attachment_paths:
        try:
            path.unlink(missing_ok=True)
            parent_dir = path.parent
            if parent_dir.name.startswith('gojeera-clipboard-'):
                parent_dir.rmdir()
        except OSError:
            pass

    clipboard_attachment_paths.clear()
    clipboard_attachment_names.clear()
    uploaded_clipboard_attachments.clear()


def materialize_uploaded_attachment_references(
    *,
    raw_text: str,
    clipboard_attachment_names: list[str],
    uploaded_clipboard_attachments: list[Attachment],
    app: JiraApp,
) -> str:
    uploaded_by_name = {
        attachment.filename: attachment for attachment in uploaded_clipboard_attachments
    }
    ordered_uploaded_attachments = [
        uploaded_by_name.get(filename) for filename in clipboard_attachment_names
    ]
    return prepare_staged_attachment_text(
        materialize_staged_attachment_references(
            raw_text,
            clipboard_attachment_names,
            ordered_uploaded_attachments,
            app=app,
        )
    ).strip()
