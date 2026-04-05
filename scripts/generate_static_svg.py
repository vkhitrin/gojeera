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
    test: str | None
    widget: str
    note: str = ''
    crop_start_line: int | None = None
    crop_line_count: int | None = None
    crop_min_x: float | None = None
    crop_max_x: float | None = None


STATIC_SVG_SCENARIOS: dict[str, StaticSvgScenario] = {
    'unified_search_basic_mode': StaticSvgScenario(
        name='unified_search_basic_mode',
        output='static/unified_search_basic_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_unified_search_basic_mode_initial.svg',
        source_kind='snapshot',
        template='static/unified_search_basic_mode.svg',
        test='tests/test_unified_search.py::TestUnifiedSearch::test_unified_search_basic_mode_initial',
        widget='src/gojeera/components/unified_search.py',
        note='Unified search widget in BASIC mode.',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'unified_search_text_mode': StaticSvgScenario(
        name='unified_search_text_mode',
        output='static/unified_search_text_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_unified_search_text_with_query.svg',
        source_kind='snapshot',
        template='static/unified_search_text_mode.svg',
        test='tests/test_unified_search.py::TestUnifiedSearch::test_unified_search_text_with_query',
        widget='src/gojeera/components/unified_search.py',
        note='Unified search widget in TEXT mode with a query.',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'unified_search_jql_mode': StaticSvgScenario(
        name='unified_search_jql_mode',
        output='static/unified_search_jql_mode.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_set_initial_jql_filter.svg',
        source_kind='snapshot',
        template='static/unified_search_jql_mode.svg',
        test='tests/test_unified_search.py::TestUnifiedSearch::test_set_initial_jql_filter',
        widget='src/gojeera/components/unified_search.py',
        note='Unified search widget in JQL mode with a query.',
        crop_start_line=1,
        crop_line_count=1,
    ),
    'unified_search_filters_view': StaticSvgScenario(
        name='unified_search_filters_view',
        output='static/unified_search_filters_view.svg',
        source='tests/__snapshots__/test_unified_search/TestUnifiedSearch.test_unified_search_jql_with_filters.svg',
        source_kind='snapshot',
        template='static/unified_search_filters_view.svg',
        test='tests/test_unified_search.py::TestUnifiedSearch::test_unified_search_jql_with_filters',
        widget='src/gojeera/components/unified_search.py',
        note='Unified search JQL autocomplete/filter view.',
        crop_start_line=1,
        crop_line_count=3,
    ),
    'work_item_description_tab': StaticSvgScenario(
        name='work_item_description_tab',
        output='static/work_item_description_tab.svg',
        source='tests/__snapshots__/test_work_item_description/TestWorkItemDescription.test_wrapped_link_snapshot.svg',
        source_kind='snapshot',
        template='static/work_item_description_tab.svg',
        test='tests/test_work_item_description.py::TestWorkItemDescription::test_wrapped_link_snapshot',
        widget='src/gojeera/components/work_item_description.py',
        note='Summary/description tab view.',
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
        test='tests/test_work_item_attachments.py::TestWorkItemAttachments::test_work_item_attachments_row_highlighted',
        widget='src/gojeera/components/work_item_attachments.py',
        note='Attachments tab with a highlighted row.',
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
        test=None,
        widget='src/gojeera/components/view_attachment_screen.py',
        note='Legacy static asset. No matching snapshot test is currently registered.',
    ),
    'work_item_subtasks_tab': StaticSvgScenario(
        name='work_item_subtasks_tab',
        output='static/work_item_subtasks_tab.svg',
        source='tests/__snapshots__/test_work_item_subtasks/TestWorkItemSubtasks.test_work_item_subtasks_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_subtasks_tab.svg',
        test='tests/test_work_item_subtasks.py::TestWorkItemSubtasks::test_work_item_subtasks_row_highlighted',
        widget='src/gojeera/components/work_item_subtasks.py',
        note='Subtasks tab with a highlighted row.',
        crop_start_line=6,
        crop_line_count=5,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_related_tab': StaticSvgScenario(
        name='work_item_related_tab',
        output='static/work_item_related_tab.svg',
        source='tests/__snapshots__/test_work_item_related_work_items/TestWorkItemRelatedWorkItems.test_work_item_related_work_items_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_related_tab.svg',
        test='tests/test_work_item_related_work_items.py::TestWorkItemRelatedWorkItems::test_work_item_related_work_items_row_highlighted',
        widget='src/gojeera/components/work_item_related_work_items.py',
        note='Related items tab with a highlighted row.',
        crop_start_line=6,
        crop_line_count=5,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'work_item_web_links_tab': StaticSvgScenario(
        name='work_item_web_links_tab',
        output='static/work_item_web_links_tab.svg',
        source='tests/__snapshots__/test_work_item_web_links/TestWorkItemWebLinks.test_work_item_web_links_row_highlighted.svg',
        source_kind='snapshot',
        template='static/work_item_web_links_tab.svg',
        test='tests/test_work_item_web_links.py::TestWorkItemWebLinks::test_work_item_web_links_row_highlighted',
        widget='src/gojeera/components/work_item_web_links.py',
        note='Web links tab with a highlighted row.',
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
        test='tests/test_work_item_comments.py::TestWorkItemComments::test_comments_display',
        widget='src/gojeera/components/work_item_comments.py',
        note='Comments tab display state.',
        crop_start_line=6,
        crop_line_count=13,
        crop_min_x=24.4,
        crop_max_x=963.0,
    ),
    'log_work_screen': StaticSvgScenario(
        name='log_work_screen',
        output='static/log_work_screen.svg',
        source='tests/__snapshots__/test_work_log_screen/TestLogWorkScreen.test_log_work_screen_valid_fields.svg',
        source_kind='snapshot',
        template='static/log_work_screen.svg',
        test='tests/test_work_log_screen.py::TestLogWorkScreen::test_log_work_screen_valid_fields',
        widget='src/gojeera/components/work_log_screen.py',
        note='Log work screen with populated valid fields.',
        crop_start_line=5,
        crop_line_count=30,
    ),
    'fields_panel': StaticSvgScenario(
        name='fields_panel',
        output='static/fields_panel.svg',
        source='tests/__snapshots__/test_work_item_fields/TestWorkItemFields.test_work_item_fields_initial_state.svg',
        source_kind='snapshot',
        template='static/fields_panel.svg',
        test='tests/test_work_item_fields.py::TestWorkItemFields::test_work_item_fields_initial_state',
        widget='src/gojeera/components/work_item_fields.py',
        note='Work item fields panel initial state.',
        crop_start_line=8,
        crop_line_count=30,
        crop_min_x=963.0,
        crop_max_x=1464.0,
    ),
    'new_work_item_screen': StaticSvgScenario(
        name='new_work_item_screen',
        output='static/new_work_item_screen.svg',
        source='tests/__snapshots__/test_new_work_item_screen/TestNewWorkItemScreen.test_new_work_item_all_required_filled.svg',
        source_kind='snapshot',
        template='static/new_work_item_screen.svg',
        test='tests/test_new_work_item_screen.py::TestNewWorkItemScreen::test_new_work_item_all_required_filled',
        widget='src/gojeera/components/new_work_item_screen.py',
        note='New work item screen with required fields filled.',
        crop_start_line=3,
        crop_line_count=35,
        crop_min_x=48.8,
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


def extract_plain_text(root: ET.Element) -> str:
    spans = sorted(extract_text_spans(root), key=lambda item: (item.line_index, item.x))
    by_line: dict[int, list[str]] = {}
    for span in spans:
        by_line.setdefault(span.line_index, []).append(span.text)
    lines = [''.join(by_line[index]).rstrip() for index in sorted(by_line)]
    return '\n'.join(lines).rstrip() + '\n'


def _extract_text_lines(root: ET.Element) -> list[str]:
    spans = sorted(extract_text_spans(root), key=lambda item: (item.line_index, item.x))
    by_line: dict[int, list[str]] = {}
    for span in spans:
        by_line.setdefault(span.line_index, []).append(span.text)
    return [''.join(by_line[index]).rstrip() for index in sorted(by_line)]


def _normalize_line(line: str) -> str:
    return line.replace('\xa0', ' ').rstrip()


def list_scenarios() -> int:
    for scenario in STATIC_SVG_SCENARIOS.values():
        test = scenario.test or '<missing>'
        sys.stdout.write(f'{scenario.name}\n')
        sys.stdout.write(f'  output:   {scenario.output}\n')
        sys.stdout.write(f'  source:   {scenario.source}\n')
        sys.stdout.write(f'  kind:     {scenario.source_kind}\n')
        sys.stdout.write(f'  test:     {test}\n')
        sys.stdout.write(f'  widget:   {scenario.widget}\n')
        if scenario.note:
            sys.stdout.write(f'  note:     {scenario.note}\n')
    return 0


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


def _text_intersects_crop(
    text: ET.Element,
    crop_min_x: float,
    crop_max_x: float,
    crop_start_line: int,
    crop_end_line: int,
) -> bool:
    line_index = _line_index_from_clip_path(text.get('clip-path'))
    if line_index is None or not (crop_start_line <= line_index < crop_end_line):
        return False

    x = float(text.get('x', '0'))
    text_length = float(text.get('textLength', '0'))
    return x < crop_max_x and (x + text_length) > crop_min_x


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

    for child in terminal_group:
        if child.tag == _qname('rect') and _rect_intersects_crop(
            child,
            crop_min_x,
            crop_max_x,
            start_y,
            crop_end_y,
        ):
            cropped_group.append(_clone_element(child))
            continue

        if child.tag != _qname('g'):
            continue

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
