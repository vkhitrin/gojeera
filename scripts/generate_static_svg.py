from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

SVG_NS = 'http://www.w3.org/2000/svg'
TERMINAL_CELL_WIDTH = 12.2
ARTIFICIAL_SCROLLBAR_THUMB_FILL = '#1E1E1E'
ET.register_namespace('', SVG_NS)


def _qname(tag: str) -> str:
    return f'{{{SVG_NS}}}{tag}'


@dataclass(frozen=True)
class TextSpan:
    line_index: int
    x: float
    text: str


@dataclass(frozen=True)
class StaticSvgScenario:
    name: str
    output: str
    source: str
    source_kind: str
    template: str | None
    widget: str
    crop_start_line: int | None = None
    crop_line_count: int | None = None
    crop_min_x: float | None = None
    crop_max_x: float | None = None
    crop_body_start_line: int | None = None
    crop_body_max_x: float | None = None


STATIC_SVG_SCENARIOS: dict[str, StaticSvgScenario] = {
    'unified_search_basic_mode': StaticSvgScenario(
        name='unified_search_basic_mode',
        output='static/unified_search_basic_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_unified_search_basic_mode_initial.svg',
        source_kind='snapshot',
        template='static/unified_search_basic_mode.svg',
        widget='src/gojeera/components/unified_search.py',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'unified_search_text_mode': StaticSvgScenario(
        name='unified_search_text_mode',
        output='static/unified_search_text_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_unified_search_text_with_query.svg',
        source_kind='snapshot',
        template='static/unified_search_text_mode.svg',
        widget='src/gojeera/components/unified_search.py',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'unified_search_jql_mode': StaticSvgScenario(
        name='unified_search_jql_mode',
        output='static/unified_search_jql_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_set_initial_jql_filter.svg',
        source_kind='snapshot',
        template='static/unified_search_jql_mode.svg',
        widget='src/gojeera/components/unified_search.py',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'work_item_description_tab': StaticSvgScenario(
        name='work_item_description_tab',
        output='static/work_item_description_tab.svg',
        source='tests/__snapshots__/test_work_item_description/TestWorkItemDescription.test_wrapped_link_snapshot.svg',
        source_kind='snapshot',
        template='static/work_item_description_tab.svg',
        widget='src/gojeera/components/work_item_description.py',
        crop_start_line=6,
        crop_line_count=13,
        crop_min_x=24.4,
        crop_max_x=640.0,
    ),
    'work_item_attachments_tab': StaticSvgScenario(
        name='work_item_attachments_tab',
        output='static/work_item_attachments_tab.svg',
        source='tests/__snapshots__/test_work_item_attachments/TestWorkItemAttachments.test_work_item_attachments_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_attachments_tab.svg',
        widget='src/gojeera/components/work_item_attachments.py',
        crop_start_line=6,
        crop_line_count=4,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_attachment_screen': StaticSvgScenario(
        name='work_item_attachment_screen',
        output='static/work_item_attachment_screen.svg',
        source='static/work_item_attachment_screen.svg',
        source_kind='legacy-static',
        template='static/work_item_attachment_screen.svg',
        widget='src/gojeera/components/view_attachment_screen.py',
    ),
    'work_item_subtasks_tab': StaticSvgScenario(
        name='work_item_subtasks_tab',
        output='static/work_item_subtasks_tab.svg',
        source='tests/__snapshots__/test_work_item_subtasks/TestWorkItemSubtasks.test_work_item_subtasks_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_subtasks_tab.svg',
        widget='src/gojeera/components/work_item_subtasks.py',
        crop_start_line=6,
        crop_line_count=5,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_search_results': StaticSvgScenario(
        name='work_item_search_results',
        output='static/work_item_search_results.svg',
        source='tests/__snapshots__/test_app_appearance/TestAppAppearance.test_app_with_default_theme.svg',
        source_kind='snapshot',
        template='static/work_item_search_results.svg',
        widget='src/gojeera/widgets/work_item_search_results_scroll.py',
        crop_start_line=3,
        crop_line_count=36,
        crop_min_x=0.0,
        crop_max_x=378.2,
    ),
    'work_item_web_links_tab': StaticSvgScenario(
        name='work_item_web_links_tab',
        output='static/work_item_web_links_tab.svg',
        source='tests/__snapshots__/test_work_item_web_links/TestWorkItemWebLinks.test_work_item_web_links_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_web_links_tab.svg',
        widget='src/gojeera/components/work_item_web_links.py',
        crop_start_line=6,
        crop_line_count=9,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_comments_tab': StaticSvgScenario(
        name='work_item_comments_tab',
        output='static/work_item_comments_tab.svg',
        source='tests/__snapshots__/test_work_item_comments/TestWorkItemComments.test_comments_display.svg',
        source_kind='snapshot',
        template='static/work_item_comments_tab.svg',
        widget='src/gojeera/components/work_item_comments.py',
        crop_start_line=6,
        crop_line_count=13,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_history_tab': StaticSvgScenario(
        name='work_item_history_tab',
        output='static/work_item_history_tab.svg',
        source='tests/__snapshots__/test_work_item_history/TestWorkItemHistory.test_work_item_history_initial_state.svg',
        source_kind='snapshot',
        template='static/work_item_history_tab.svg',
        widget='src/gojeera/components/work_item_history.py',
        crop_start_line=6,
        crop_line_count=7,
        crop_min_x=24.4,
        crop_max_x=1122.0,
        crop_body_start_line=8,
        crop_body_max_x=950.8,
    ),
    'log_work_screen': StaticSvgScenario(
        name='log_work_screen',
        output='static/log_work_screen.svg',
        source='tests/__snapshots__/test_work_log_screen/TestLogWorkScreen.test_log_work_screen_valid_fields.svg',
        source_kind='snapshot',
        template='static/log_work_screen.svg',
        widget='src/gojeera/components/work_log_screen.py',
        crop_start_line=7,
        crop_line_count=26,
        crop_min_x=317.2,
        crop_max_x=1134.6,
    ),
    'fields_panel': StaticSvgScenario(
        name='fields_panel',
        output='static/fields_panel.svg',
        source='tests/__snapshots__/test_work_item_fields/TestWorkItemFields.test_work_item_fields_initial_state.svg',
        source_kind='snapshot',
        template='static/fields_panel.svg',
        widget='src/gojeera/components/work_item_fields.py',
        crop_start_line=8,
        crop_line_count=30,
        crop_min_x=963.0,
        crop_max_x=1464.0,
    ),
    'create_work_item_screen': StaticSvgScenario(
        name='create_work_item_screen',
        output='static/create_work_item_screen.svg',
        source='tests/__snapshots__/test_create_work_item_screen/TestCreateWorkItemScreen.test_create_work_item_all_required_filled.svg',
        source_kind='snapshot',
        template='static/create_work_item_screen.svg',
        widget='src/gojeera/components/screens/create_work_item_screen.py',
        crop_start_line=2,
        crop_line_count=36,
        crop_min_x=207.4,
        crop_max_x=1256.6,
    ),
}


def _load_svg(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _clone_element(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding='unicode'))


def _iter_text_nodes(root: ET.Element) -> list[ET.Element]:
    return list(root.iterfind(f'.//{_qname("text")}'))


def _line_index_from_clip_path(clip_path: str | None) -> int | None:
    if not clip_path:
        return None
    match = re.search(r'line-(\d+)\)', clip_path)
    if not match:
        return None
    return int(match.group(1))


def extract_text_spans(root: ET.Element) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for node in _iter_text_nodes(root):
        line_index = _line_index_from_clip_path(node.get('clip-path'))
        if line_index is None:
            continue
        text = ''.join(node.itertext())
        if not text:
            continue
        x = float(node.get('x', '0'))
        spans.append(TextSpan(line_index=line_index, x=x, text=unescape(text)))
    return spans


def _extract_text_lines(root: ET.Element) -> list[str]:
    spans = sorted(extract_text_spans(root), key=lambda item: (item.line_index, item.x))
    by_line: dict[int, list[str]] = {}
    for span in spans:
        by_line.setdefault(span.line_index, []).append(span.text)
    return [''.join(by_line[index]).rstrip() for index in sorted(by_line)]


def _normalize_line(line: str) -> str:
    return line.replace('\xa0', ' ').rstrip()


def _read_origin_main_file(path: str) -> str:
    result = subprocess.run(
        ['git', 'show', f'origin/main:{path}'],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _load_origin_main_svg(path: str) -> ET.Element:
    return ET.fromstring(_read_origin_main_file(path))


def _find_terminal_group(root: ET.Element) -> ET.Element:
    for group in root.iterfind(f'.//{_qname("g")}'):
        clip_path = group.get('clip-path', '')
        if 'clip-terminal' in clip_path:
            return group
    raise ValueError('Could not find terminal content group in snapshot SVG')


def _infer_crop_from_origin_main(scenario: StaticSvgScenario) -> tuple[int, int]:
    snapshot_root = _load_svg(Path(scenario.source))
    reference_root = _load_origin_main_svg(scenario.output)

    snapshot_lines = [_normalize_line(line) for line in _extract_text_lines(snapshot_root)]
    reference_lines = [_normalize_line(line) for line in _extract_text_lines(reference_root)]
    reference_lines = [line for line in reference_lines if line]
    if not reference_lines:
        raise ValueError(f'No reference lines found in origin/main:{scenario.output}')

    reference_len = len(reference_lines)
    for start_index in range(len(snapshot_lines) - reference_len + 1):
        candidate = snapshot_lines[start_index : start_index + reference_len]
        if candidate == reference_lines:
            return start_index, reference_len

    raise ValueError(
        f'Could not match origin/main crop for {scenario.name!r} '
        f'from {scenario.output!r} within {scenario.source!r}'
    )


def _find_clip_rect(defs: ET.Element, clip_path_id: str) -> ET.Element:
    clip_path = defs.find(f"./{_qname('clipPath')}[@id='{clip_path_id}']")
    if clip_path is None:
        raise ValueError(f'Missing clipPath {clip_path_id!r}')

    rect = clip_path.find(_qname('rect'))
    if rect is None:
        raise ValueError(f'Missing rect for clipPath {clip_path_id!r}')
    return rect


def _rect_intersects_crop(
    rect: ET.Element,
    crop_min_x: float,
    crop_max_x: float,
    crop_start_y: float,
    crop_end_y: float,
) -> bool:
    x = float(rect.get('x', '0'))
    y = float(rect.get('y', '0'))
    width = float(rect.get('width', '0'))
    height = float(rect.get('height', '0'))
    return (
        x < crop_max_x
        and (x + width) > crop_min_x
        and y < crop_end_y
        and (y + height) > crop_start_y
    )


def _body_crop_start_y(
    defs: ET.Element, terminal_prefix: str, line_index: int | None
) -> float | None:
    if line_index is None:
        return None
    rect = _find_clip_rect(defs, f'{terminal_prefix}-line-{line_index}')
    return float(rect.get('y', '0'))


def _clone_rect_for_crop(
    rect: ET.Element,
    *,
    body_crop_start_y: float | None,
    crop_body_max_x: float | None,
) -> ET.Element | None:
    clone = _clone_element(rect)
    if body_crop_start_y is None or crop_body_max_x is None:
        return clone

    y = float(rect.get('y', '0'))
    x = float(rect.get('x', '0'))
    width = float(rect.get('width', '0'))
    if y >= body_crop_start_y:
        if x >= crop_body_max_x:
            return None
        if x + width > crop_body_max_x:
            clone.set('width', str(crop_body_max_x - x))
    return clone


def _append_artificial_scrollbar_thumb(
    cropped_group: ET.Element,
    terminal_group: ET.Element,
    *,
    body_crop_start_y: float | None,
    crop_max_x: float,
    crop_end_y: float,
) -> None:
    if body_crop_start_y is None:
        return

    thumb_x = crop_max_x - TERMINAL_CELL_WIDTH
    for rect in terminal_group.findall(_qname('rect')):
        if rect.get('fill') != '#0053aa':
            continue
        y = float(rect.get('y', '0'))
        if y < body_crop_start_y or y >= crop_end_y:
            continue

        clone = _clone_element(rect)
        clone.set('x', str(thumb_x))
        clone.set('fill', ARTIFICIAL_SCROLLBAR_THUMB_FILL)
        cropped_group.append(clone)


def _text_intersects_crop(
    text: ET.Element,
    crop_min_x: float,
    crop_max_x: float,
    crop_start_line: int,
    crop_end_line: int,
    crop_body_start_line: int | None = None,
    crop_body_max_x: float | None = None,
) -> bool:
    line_index = _line_index_from_clip_path(text.get('clip-path'))
    if line_index is None or not (crop_start_line <= line_index < crop_end_line):
        return False

    x = float(text.get('x', '0'))
    text_length = float(text.get('textLength', '0'))
    effective_crop_max_x = crop_max_x
    if (
        crop_body_start_line is not None
        and crop_body_max_x is not None
        and line_index >= crop_body_start_line
    ):
        effective_crop_max_x = crop_body_max_x
    return x < effective_crop_max_x and (x + text_length) > crop_min_x


def _get_terminal_metrics(
    root: ET.Element, start_line: int, line_count: int
) -> tuple[float, float]:
    defs = root.find(_qname('defs'))
    if defs is None:
        raise ValueError('Missing defs in snapshot SVG')

    start_rect = _find_clip_rect(defs, f'{_terminal_id_prefix(root)}-line-{start_line}')
    end_rect = _find_clip_rect(
        defs, f'{_terminal_id_prefix(root)}-line-{start_line + line_count - 1}'
    )

    start_y = float(start_rect.get('y', '0'))
    width = float(start_rect.get('width', '0'))
    end_y = float(end_rect.get('y', '0'))
    end_height = float(end_rect.get('height', '0'))
    return width, (end_y + end_height) - start_y


def _terminal_id_prefix(root: ET.Element) -> str:
    defs = root.find(_qname('defs'))
    if defs is None:
        raise ValueError('Missing defs in snapshot SVG')

    for clip_path in defs.findall(_qname('clipPath')):
        clip_id = clip_path.get('id')
        if clip_id and clip_id.endswith('-clip-terminal'):
            return clip_id.removesuffix('-clip-terminal')
    raise ValueError('Missing terminal clip-path id in snapshot SVG')


def _build_cropped_terminal_svg(scenario: StaticSvgScenario) -> ET.Element:
    crop_start_line = scenario.crop_start_line
    crop_line_count = scenario.crop_line_count
    if crop_start_line is None or crop_line_count is None:
        crop_start_line, crop_line_count = _infer_crop_from_origin_main(scenario)

    source_root = _load_svg(Path(scenario.source))
    style = source_root.find(_qname('style'))
    defs = source_root.find(_qname('defs'))
    terminal_group = _find_terminal_group(source_root)
    if style is None or defs is None:
        raise ValueError('Snapshot SVG is missing style/defs')

    terminal_prefix = _terminal_id_prefix(source_root)
    start_rect = _find_clip_rect(defs, f'{terminal_prefix}-line-{crop_start_line}')
    start_y = float(start_rect.get('y', '0'))
    width, height = _get_terminal_metrics(
        source_root,
        crop_start_line,
        crop_line_count,
    )
    crop_min_x = scenario.crop_min_x if scenario.crop_min_x is not None else 0.0
    crop_max_x = scenario.crop_max_x if scenario.crop_max_x is not None else width
    body_crop_start_y = _body_crop_start_y(
        defs,
        terminal_prefix,
        scenario.crop_body_start_line,
    )
    width = crop_max_x - crop_min_x
    crop_end_y = start_y + height
    crop_end_line = crop_start_line + crop_line_count

    output_root = ET.Element(
        _qname('svg'),
        {
            'class': source_root.get('class', 'rich-terminal'),
            'viewBox': f'0 0 {width} {height}',
            'width': str(width),
            'height': str(height),
        },
    )
    output_root.append(ET.Comment(' Generated with Rich https://www.textualize.io '))
    output_root.append(_clone_element(style))
    output_root.append(_clone_element(defs))

    cropped_group = ET.Element(_qname('g'))
    for key, value in terminal_group.attrib.items():
        if key != 'transform':
            cropped_group.set(key, value)
    cropped_group.set('transform', f'translate(-{crop_min_x},-{start_y})')
    if body_crop_start_y is not None and scenario.crop_body_max_x is not None:
        cropped_group.append(
            ET.Element(
                _qname('rect'),
                {
                    'fill': '#121212',
                    'x': str(scenario.crop_body_max_x),
                    'y': str(body_crop_start_y),
                    'width': str(crop_max_x - scenario.crop_body_max_x),
                    'height': str(crop_end_y - body_crop_start_y),
                    'shape-rendering': 'crispEdges',
                },
            )
        )

    for child in terminal_group:
        if child.tag == _qname('rect') and _rect_intersects_crop(
            child,
            crop_min_x,
            crop_max_x,
            start_y,
            crop_end_y,
        ):
            cropped_rect = _clone_rect_for_crop(
                child,
                body_crop_start_y=body_crop_start_y,
                crop_body_max_x=scenario.crop_body_max_x,
            )
            if cropped_rect is not None:
                cropped_group.append(cropped_rect)
            continue

        if child.tag != _qname('g'):
            continue

        _append_artificial_scrollbar_thumb(
            cropped_group,
            terminal_group,
            body_crop_start_y=body_crop_start_y,
            crop_max_x=crop_max_x,
            crop_end_y=crop_end_y,
        )

        text_group = ET.Element(_qname('g'))
        for key, value in child.attrib.items():
            text_group.set(key, value)
        for text in child:
            if text.tag == _qname('text') and _text_intersects_crop(
                text,
                crop_min_x,
                crop_max_x,
                crop_start_line,
                crop_end_line,
                scenario.crop_body_start_line,
                scenario.crop_body_max_x,
            ):
                text_group.append(_clone_element(text))
        if len(text_group):
            cropped_group.append(text_group)

    output_root.append(cropped_group)
    return output_root


def _write_svg(root: ET.Element, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ET.tostring(root, encoding='unicode'), encoding='utf-8')
    return path


def _copy_scenario_output(scenario: StaticSvgScenario, output_override: str | None = None) -> Path:
    source_path = Path(scenario.source)
    output_path = Path(output_override or scenario.output)
    if scenario.source_kind == 'snapshot':
        return _write_svg(_build_cropped_terminal_svg(scenario), output_path)

    if scenario.output != scenario.source:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_read_origin_main_file(scenario.output), encoding='utf-8')
        return output_path

    if source_path.resolve() != output_path.resolve():
        shutil.copyfile(source_path, output_path)
    return output_path


def generate_all() -> int:
    for scenario in STATIC_SVG_SCENARIOS.values():
        output_path = _copy_scenario_output(scenario)
        sys.stdout.write(f'{scenario.name}: {scenario.source} -> {output_path}\n')
    return 0


def main() -> int:
    return generate_all()


if __name__ == '__main__':
    sys.exit(main())
