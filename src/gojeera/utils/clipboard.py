from pathlib import Path
import re
import shutil
from tempfile import mkdtemp
from typing import Sequence
from urllib.parse import unquote, urlparse

from gojeera.models import Attachment
from gojeera.utils.urls import build_external_url_for_attachment


class ClipboardAttachmentError(RuntimeError):
    """Raised when clipboard contents cannot be staged as attachments."""


STAGED_ATTACHMENT_REFERENCE_TEXT = '<!-- gojeera:staged-clipboard-attachment -->'
STAGED_ATTACHMENT_REFERENCE_PATTERN = re.compile(re.escape(STAGED_ATTACHMENT_REFERENCE_TEXT))
STAGED_ATTACHMENT_WITH_TRAILING_PATH_PATTERN = re.compile(
    rf'({re.escape(STAGED_ATTACHMENT_REFERENCE_TEXT)})(?:\s*)(?:file://\S+|/(?:[^\n\\]|\\.)+)',
)


def _escape_markdown_link_text(text: str) -> str:
    return text.replace('\\', '\\\\').replace('[', '\\[').replace(']', '\\]')


def build_attachment_reference_markdown(
    attachment: Attachment,
    *,
    app=None,
) -> str:
    """Return markdown for an uploaded attachment link."""
    label = _escape_markdown_link_text(attachment.filename)
    if url := build_external_url_for_attachment(attachment.id, attachment.filename, app):
        return f'[{label}]({url})'
    return label


def build_staged_attachment_reference_text(filename: str | None = None) -> str:
    """Return the inline text shown in drafts before an attachment is uploaded."""
    return STAGED_ATTACHMENT_REFERENCE_TEXT


def materialize_staged_attachment_references(
    text: str,
    staged_filenames: list[str],
    uploaded_attachments: Sequence[Attachment | None],
    *,
    app=None,
) -> str:
    """Replace staged attachment markers with final references or remove them."""
    resolved_text = text
    for staged_filename, uploaded_attachment in zip(
        staged_filenames, uploaded_attachments, strict=False
    ):
        resolved_text = resolved_text.replace(
            build_staged_attachment_reference_text(staged_filename),
            (
                build_attachment_reference_markdown(uploaded_attachment, app=app)
                if uploaded_attachment
                else ''
            ),
            1,
        )

    return resolved_text


def sanitize_staged_attachment_text(text: str) -> str:
    """Remove leaked local file paths from text that contains staged attachment markers."""
    sanitized_text = STAGED_ATTACHMENT_WITH_TRAILING_PATH_PATTERN.sub(r'\1', text)

    sanitized_lines: list[str] = []
    for line in sanitized_text.splitlines():
        if _parse_clipboard_text_paths(line):
            continue
        sanitized_lines.append(line)

    return '\n'.join(sanitized_lines)


def prepare_staged_attachment_text(text: str) -> str:
    """Strip staged attachment markers from draft text."""
    sanitized_text = sanitize_staged_attachment_text(text)
    return STAGED_ATTACHMENT_REFERENCE_PATTERN.sub('', sanitized_text)


def _create_staging_dir() -> Path:
    staging_dir = Path(mkdtemp(prefix='gojeera-clipboard-'))
    staging_dir.mkdir(parents=True, exist_ok=True)
    return staging_dir


def _build_staged_file_path(staging_dir: Path, source_name: str) -> Path:
    safe_name = Path(source_name).name or 'clipboard.bin'
    return staging_dir / safe_name


def _parse_clipboard_text_paths(clipboard_text: str) -> list[Path]:
    parsed_paths: list[Path] = []

    for line in clipboard_text.splitlines():
        value = line.strip()
        if not value:
            continue

        # Terminal paste can contain shell-escaped spaces for filesystem paths.
        value = value.replace('\\ ', ' ')

        if value.startswith('file://'):
            parsed_url = urlparse(value)
            candidate = Path(unquote(parsed_url.path))
        else:
            candidate = Path(value).expanduser()

        if candidate.exists() and candidate.is_file():
            parsed_paths.append(candidate)

    return parsed_paths


def _read_text_clipboard() -> str | None:
    try:
        import tkinter
    except Exception:
        return None

    clipboard_text = ''
    root = None
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.update()
        clipboard_text = root.clipboard_get()
    except Exception:
        return None
    finally:
        if root is not None:
            root.destroy()

    if not clipboard_text.strip():
        return None

    return clipboard_text


def _stage_file_list(staging_dir: Path, file_paths: list[Path]) -> list[Path]:
    staged_paths: list[Path] = []
    for file_path in file_paths:
        staged_path = _build_staged_file_path(staging_dir, file_path.name)
        shutil.copy2(file_path, staged_path)
        staged_paths.append(staged_path)
    return staged_paths


def _stage_plain_text_from_clipboard(staging_dir: Path) -> Path | None:
    clipboard_text = _read_text_clipboard()
    if not clipboard_text:
        return None

    if _parse_clipboard_text_paths(clipboard_text):
        return None

    staged_path = _build_staged_file_path(staging_dir, 'clipboard.txt')
    staged_path.write_text(clipboard_text, encoding='utf-8')
    return staged_path


def stage_file_paths_from_text(clipboard_text: str) -> list[Path]:
    """Stage pasted file paths from text, returning copied temp files."""
    file_paths = _parse_clipboard_text_paths(clipboard_text)
    if not file_paths:
        return []

    staging_dir = _create_staging_dir()
    staged_paths = _stage_file_list(staging_dir, file_paths)
    if staged_paths:
        return staged_paths

    shutil.rmtree(staging_dir, ignore_errors=True)
    return []


def stage_clipboard_attachments() -> list[Path]:
    """Copy supported clipboard contents into temporary files for later upload."""
    staging_dir = _create_staging_dir()

    clipboard_text = _read_text_clipboard()
    staged_paths = _stage_file_list(staging_dir, _parse_clipboard_text_paths(clipboard_text or ''))
    if staged_paths:
        return staged_paths

    staged_text = _stage_plain_text_from_clipboard(staging_dir)
    if staged_text is not None:
        return [staged_text]

    shutil.rmtree(staging_dir, ignore_errors=True)
    raise ClipboardAttachmentError(
        'Clipboard does not contain a supported file path or text payload.'
    )


def stage_non_text_clipboard_attachments(clipboard_text: str | None = None) -> list[Path]:
    """Stage file paths from pasted clipboard text for later upload."""
    source_text = clipboard_text if clipboard_text is not None else (_read_text_clipboard() or '')
    return stage_file_paths_from_text(source_text)
