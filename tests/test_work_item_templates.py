from __future__ import annotations

import pytest

from gojeera.utils.work_item_templates import (
    WorkItemTemplateError,
    has_valid_work_item_templates,
    list_work_item_template_files,
    load_work_item_template,
)


def test_list_work_item_template_files_returns_yaml_files_in_order(tmp_path) -> None:
    templates_dir = tmp_path / 'templates'
    templates_dir.mkdir()
    (templates_dir / 'b.yml').write_text('template_name: B', encoding='utf-8')
    (templates_dir / 'a.yaml').write_text('template_name: A', encoding='utf-8')
    (templates_dir / 'ignored.json').write_text('{}', encoding='utf-8')

    assert [path.name for path in list_work_item_template_files(templates_dir)] == [
        'a.yaml',
        'b.yml',
    ]


def test_has_valid_work_item_templates_returns_false_when_all_templates_are_invalid(
    tmp_path,
) -> None:
    templates_dir = tmp_path / 'templates'
    templates_dir.mkdir()
    (templates_dir / 'invalid.yaml').write_text('[unclosed', encoding='utf-8')
    (templates_dir / 'list.yaml').write_text('- one\n- two\n', encoding='utf-8')

    assert has_valid_work_item_templates(templates_dir) is False


def test_has_valid_work_item_templates_returns_true_when_any_template_is_valid(tmp_path) -> None:
    templates_dir = tmp_path / 'templates'
    templates_dir.mkdir()
    (templates_dir / 'invalid.yaml').write_text('[unclosed', encoding='utf-8')
    (templates_dir / 'valid.yaml').write_text(
        'template_name: Valid\nsummary: Works\n', encoding='utf-8'
    )

    assert has_valid_work_item_templates(templates_dir) is True


def test_load_work_item_template_returns_empty_mapping_for_empty_file(tmp_path) -> None:
    template_file = tmp_path / 'empty.yaml'
    template_file.write_text('', encoding='utf-8')

    assert load_work_item_template(template_file) == {}


def test_load_work_item_template_rejects_non_mapping_yaml(tmp_path) -> None:
    template_file = tmp_path / 'list.yaml'
    template_file.write_text('- one\n- two\n', encoding='utf-8')

    with pytest.raises(WorkItemTemplateError, match='must be a mapping'):
        load_work_item_template(template_file)


def test_load_work_item_template_rejects_invalid_yaml(tmp_path) -> None:
    template_file = tmp_path / 'invalid.yaml'
    template_file.write_text(
        'template_name: Invalid\n---\nsummary: second document\n', encoding='utf-8'
    )

    with pytest.raises(WorkItemTemplateError, match='contains invalid YAML'):
        load_work_item_template(template_file)
