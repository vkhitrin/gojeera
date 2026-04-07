import pytest

from gojeera.utils import clipboard as clipboard_module


def test_stage_clipboard_attachments_prefers_image_payload(monkeypatch, tmp_path):
    source_dir = tmp_path / 'source'
    source_dir.mkdir()
    image_path = source_dir / 'clipboard.png'
    image_path.write_bytes(b'png')
    staging_dir = tmp_path / 'staging'
    staging_dir.mkdir()

    monkeypatch.setattr(clipboard_module, '_create_staging_dir', lambda: staging_dir)
    monkeypatch.setattr(
        clipboard_module,
        '_read_text_clipboard',
        lambda: str(image_path),
    )

    staged_paths = clipboard_module.stage_clipboard_attachments()

    assert staged_paths == [staging_dir / 'clipboard.png']


def test_stage_clipboard_attachments_falls_back_to_plain_text(monkeypatch, tmp_path):
    text_path = tmp_path / 'clipboard.txt'
    text_path.write_text('text')

    monkeypatch.setattr(clipboard_module, '_create_staging_dir', lambda: tmp_path)
    monkeypatch.setattr(clipboard_module, '_read_text_clipboard', lambda: 'text')
    monkeypatch.setattr(clipboard_module, '_stage_plain_text_from_clipboard', lambda _: text_path)

    staged_paths = clipboard_module.stage_clipboard_attachments()

    assert staged_paths == [text_path]


def test_stage_clipboard_attachments_raises_when_clipboard_unsupported(monkeypatch, tmp_path):
    monkeypatch.setattr(clipboard_module, '_create_staging_dir', lambda: tmp_path)
    monkeypatch.setattr(clipboard_module, '_read_text_clipboard', lambda: None)
    monkeypatch.setattr(clipboard_module, '_stage_plain_text_from_clipboard', lambda _: None)

    with pytest.raises(clipboard_module.ClipboardAttachmentError):
        clipboard_module.stage_clipboard_attachments()


def test_stage_non_text_clipboard_attachments_skips_plain_text(monkeypatch, tmp_path):
    staged_paths = clipboard_module.stage_non_text_clipboard_attachments('plain text')

    assert staged_paths == []


def test_stage_non_text_clipboard_attachments_supports_file_paths(tmp_path):
    source_path = tmp_path / 'pasted.pdf'
    source_path.write_bytes(b'%PDF')
    staged_paths = clipboard_module.stage_non_text_clipboard_attachments(str(source_path))

    assert len(staged_paths) == 1
    assert staged_paths[0].name == 'pasted.pdf'
    assert staged_paths[0].read_bytes() == b'%PDF'


def test_parse_clipboard_text_paths_handles_shell_escaped_spaces(tmp_path):
    source_path = tmp_path / 'screencapture 574.png'
    source_path.write_bytes(b'png')

    parsed_paths = clipboard_module._parse_clipboard_text_paths(
        str(source_path).replace(' ', '\\ ')
    )

    assert parsed_paths == [source_path]


def test_sanitize_staged_attachment_text_removes_trailing_local_path(tmp_path):
    source_path = tmp_path / 'screencapture 574.png'
    source_path.write_bytes(b'png')

    text = '<!-- gojeera:staged-clipboard-attachment -->' + str(source_path).replace(' ', '\\ ')

    assert clipboard_module.sanitize_staged_attachment_text(text) == (
        '<!-- gojeera:staged-clipboard-attachment -->'
    )


def test_prepare_staged_attachment_text_preserves_non_marker_content():
    cleaned_text = clipboard_module.prepare_staged_attachment_text(
        'before\n<!-- gojeera:staged-clipboard-attachment -->\nafter'
    )

    assert cleaned_text == 'before\n\nafter'
