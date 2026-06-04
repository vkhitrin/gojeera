from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

YAML_LITERAL_BLOCK_UNFRIENDLY_CHARACTERS = {
    '\u200b',
    '\u200c',
    '\u200d',
    '\ufeff',
}


def compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in mapping.items() if value not in (None, '', [], {})}


class _MultilineStringDumper(yaml.SafeDumper):
    pass


def _clean_multiline_string(value: str) -> str:
    for character in YAML_LITERAL_BLOCK_UNFRIENDLY_CHARACTERS:
        value = value.replace(character, '')
    return '\n'.join(line.rstrip() for line in value.split('\n'))


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    if '\n' in value:
        value = _clean_multiline_string(value)
    style = '|' if '\n' in value else None
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style=style)


_MultilineStringDumper.add_representer(str, _represent_string)


def _format_comment(comment: str) -> str:
    return '\n'.join(f'# {line}' if line else '#' for line in comment.splitlines())


def _add_top_level_key_comments(yaml_text: str, comments: Mapping[str, str]) -> str:
    lines: list[str] = []
    for line in yaml_text.splitlines():
        key, separator, _value = line.partition(':')
        if separator and line == line.lstrip() and key in comments:
            lines.append(_format_comment(comments[key]))
        lines.append(line)
    return '\n'.join(lines) + ('\n' if yaml_text.endswith('\n') else '')


def dump_yaml(
    data: Any,
    *,
    multiline_strings: bool = False,
    top_level_key_comments: Mapping[str, str] | None = None,
) -> str:
    """Serialize data as YAML with project defaults."""
    dumper = _MultilineStringDumper if multiline_strings else yaml.SafeDumper
    yaml_text = yaml.dump(
        data,
        Dumper=dumper,
        sort_keys=False,
        allow_unicode=True,
    )
    if top_level_key_comments:
        yaml_text = _add_top_level_key_comments(yaml_text, top_level_key_comments)
    return yaml_text
