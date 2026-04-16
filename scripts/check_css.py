from __future__ import annotations

import ast
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import re
import sys

from pydantic import SecretStr
from textual.css.stylesheet import Stylesheet, StylesheetParseError

CLASS_PATTERN = re.compile(r'(?<![0-9])\.([a-zA-Z_][a-zA-Z0-9_-]*)')
ID_PATTERN = re.compile(r'#([a-zA-Z_][a-zA-Z0-9_-]*)')
RULE_PATTERN = re.compile(r'(?ms)([^{}]+)\{')
PROPERTY_PATTERN = re.compile(r'(?m)^\s*([a-zA-Z-]+)\s*:')
SINGLE_ID_WIDGET_CHILD_SELECTOR_RE = re.compile(
    r'^#([a-zA-Z_][a-zA-Z0-9_-]*)(?:\.[a-zA-Z_-][a-zA-Z0-9_-]*)*'
    r'\s*>\s*([A-Z][a-zA-Z0-9_]*)(?:\.[a-zA-Z_-][a-zA-Z0-9_-]*)*$'
)
QUOTED_STRING_PATTERN = re.compile(r'["\']([^"\']+)["\']')


@dataclass(frozen=True)
class CssDefinition:
    owner: str
    source: Path
    selector: str
    line: int
    properties: frozenset[str]


@dataclass(frozen=True)
class ProjectClassCss:
    qualified_name: str
    source: Path
    css: str
    bases: tuple[str, ...]
    component_classes: tuple[str, ...]


def compile_textual_css(tcss_file: Path, project_css: list[ProjectClassCss]) -> list[str]:
    """Validate project CSS with Textual's stylesheet parser."""
    from gojeera.app import JiraApp
    from gojeera.config import ApplicationConfiguration, JiraConfig

    app = JiraApp(
        settings=ApplicationConfiguration.model_construct(
            jira=JiraConfig.model_construct(
                api_username='',
                api_token=SecretStr(''),
                api_base_url='',
            )
        )
    )
    stylesheet = Stylesheet(variables=app.get_css_variables())

    try:
        stylesheet.read(tcss_file)
        for project_class_css in project_css:
            stylesheet.add_source(
                project_class_css.css,
                read_from=(
                    str(project_class_css.source),
                    f'{project_class_css.qualified_name}.DEFAULT_CSS',
                ),
                is_default_css=True,
            )
        stylesheet.parse()
    except StylesheetParseError as error:
        return [str(error)]

    return []


def extract_css_selectors(tcss_content: str) -> tuple[set[str], set[str]]:
    """Extract class and ID selectors from TCSS content."""
    classes = {
        match.group(1)
        for match in CLASS_PATTERN.finditer(tcss_content)
        if not match.group(1).startswith('-')
    }
    ids = {
        match.group(1)
        for match in ID_PATTERN.finditer(tcss_content)
        if not match.group(1).startswith('-')
    }
    return classes, ids


def extract_rule_definitions(
    css_content: str,
    *,
    owner: str,
    source: Path,
) -> list[CssDefinition]:
    """Extract flat CSS rule selectors with line numbers."""
    definitions: list[CssDefinition] = []
    for match in RULE_PATTERN.finditer(css_content):
        selector_block = match.group(1).strip()
        if not selector_block:
            continue

        block_start = match.end()
        block_end = css_content.find('}', block_start)
        if block_end == -1:
            continue
        declaration_block = css_content[block_start:block_end]
        properties = frozenset(
            property_match.group(1)
            for property_match in PROPERTY_PATTERN.finditer(declaration_block)
        )

        for selector in selector_block.split(','):
            normalized_selector = ' '.join(selector.split())
            if (
                not normalized_selector
                or normalized_selector.startswith('/*')
                or '&' in normalized_selector
            ):
                continue

            line = css_content.count('\n', 0, match.start(1)) + 1
            definitions.append(
                CssDefinition(
                    owner=owner,
                    source=source,
                    selector=normalized_selector,
                    line=line,
                    properties=properties,
                )
            )
    return definitions


def _pattern_from_string_expr(node: ast.AST) -> str | None:
    """Convert a string / f-string AST node to a regex pattern."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return f'^{re.escape(node.value)}$'

    if isinstance(node, ast.JoinedStr):
        parts: list[str] = ['^']
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(re.escape(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(r'.+')
            else:
                return None
        parts.append('$')
        return ''.join(parts)

    return None


def _subscript_key_name(node: ast.Subscript) -> str | None:
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def _collect_dynamic_selector_patterns(tree: ast.AST) -> list[str]:
    """Collect regex patterns for dynamically constructed class/id selectors."""
    patterns: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name in {'add_class', 'remove_class', 'has_class'} and node.args:
                pattern = _pattern_from_string_expr(node.args[0])
                if pattern is not None:
                    patterns.append(pattern)

            if func_name == 'set_class' and len(node.args) >= 2:
                pattern = _pattern_from_string_expr(node.args[1])
                if pattern is not None:
                    patterns.append(pattern)

            if func_name == 'attrSet' and len(node.args) >= 2:
                attr_name = _extract_string_literal(node.args[0])
                if attr_name in {'class', 'id'}:
                    pattern = _pattern_from_string_expr(node.args[1])
                    if pattern is not None:
                        patterns.append(pattern)

            for keyword in node.keywords:
                if keyword.arg in {'classes', 'id'}:
                    pattern = _pattern_from_string_expr(keyword.value)
                    if pattern is not None:
                        patterns.append(pattern)

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Subscript) and _subscript_key_name(target) in {
                    'class',
                    'id',
                }:
                    pattern = _pattern_from_string_expr(node.value)
                    if pattern is not None:
                        patterns.append(pattern)

    return patterns


def _collect_selector_search_data(content: str) -> tuple[set[str], list[str]]:
    """Collect static string literals and dynamic selector patterns from source."""
    try:
        tree = ast.parse(content)
    except Exception:
        return set(QUOTED_STRING_PATTERN.findall(content)), []

    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return string_literals, _collect_dynamic_selector_patterns(tree)


def _find_terms_in_content(
    search_terms: set[str],
    string_literals: set[str],
    dynamic_patterns: list[str],
) -> set[str]:
    """Return the subset of terms found in static literals or dynamic selector patterns."""
    return {
        term
        for term in search_terms
        if any(term in literal for literal in string_literals)
        or any(re.match(pattern, term) for pattern in dynamic_patterns)
    }


def _search_file_worker(args: tuple[Path, set[str], set[str]]) -> tuple[set[str], set[str]]:
    """Worker function to search a single file for classes and IDs."""
    file_path, classes, ids = args
    try:
        content = file_path.read_text(encoding='utf-8')
        string_literals, dynamic_patterns = _collect_selector_search_data(content)
        return (
            _find_terms_in_content(classes, string_literals, dynamic_patterns),
            _find_terms_in_content(ids, string_literals, dynamic_patterns),
        )
    except Exception as error:
        sys.stderr.write(f'Error: Could not read {file_path}: {error}\n')
        return set(), set()


def _module_name_for_path(src_dir: Path, file_path: Path) -> str:
    relative = file_path.relative_to(src_dir).with_suffix('')
    return '.'.join(relative.parts)


def _extract_string_literal(node: ast.AST) -> str | None:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _extract_string_set(node: ast.AST) -> set[str]:
    try:
        value = ast.literal_eval(node)
    except Exception:
        return set()

    if isinstance(value, (set, frozenset, list, tuple)):
        return {item for item in value if isinstance(item, str)}
    return set()


def collect_project_default_css(src_dir: Path) -> list[ProjectClassCss]:
    """Collect project class DEFAULT_CSS blocks via AST, avoiding imports."""
    classes: list[ProjectClassCss] = []
    for file_path in src_dir.rglob('*.py'):
        try:
            tree = ast.parse(file_path.read_text(encoding='utf-8'))
        except Exception as error:
            sys.stderr.write(f'Error: Could not parse {file_path}: {error}\n')
            continue

        module_name = _module_name_for_path(src_dir, file_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            css_value: str | None = None
            component_classes: set[str] = set()
            for class_node in node.body:
                if not isinstance(class_node, ast.Assign):
                    continue
                for target in class_node.targets:
                    if isinstance(target, ast.Name) and target.id == 'DEFAULT_CSS':
                        css_value = _extract_string_literal(class_node.value)
                        break
                    if isinstance(target, ast.Name) and target.id == 'COMPONENT_CLASSES':
                        component_classes.update(_extract_string_set(class_node.value))
                if css_value is not None:
                    continue

            if not css_value:
                continue

            bases: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)

            classes.append(
                ProjectClassCss(
                    qualified_name=f'{module_name}.{node.name}',
                    source=file_path,
                    css=css_value,
                    bases=tuple(bases),
                    component_classes=tuple(sorted(component_classes)),
                )
            )

    return classes


def get_textual_builtin_selectors() -> tuple[set[str], set[str]]:
    """Get CSS selectors from Textual and third-party widgets."""
    import importlib
    import inspect

    widget_classes = set()
    widget_ids = set()

    widget_modules = [
        'textual.widgets',
        'textual.widgets._markdown',
        'textual.command',
        'textual_autocomplete',
        'textual_fspicker',
        'textual_image',
        'textual_jumper',
        'textual_tags',
    ]

    for module_name in widget_modules:
        try:
            widget_module = importlib.import_module(module_name)
        except ImportError:
            continue

        if hasattr(widget_module, '__all__'):
            widget_names = widget_module.__all__
        else:
            widget_names = [
                name
                for name in dir(widget_module)
                if not name.startswith('_') and name[:1].isupper()
            ]

        for widget_name in widget_names:
            try:
                obj = getattr(widget_module, widget_name)
            except AttributeError:
                continue

            if not inspect.isclass(obj):
                continue

            widget_classes.add(re.sub(r'(?<!^)(?=[A-Z])', '-', widget_name).lower())

            css_content = getattr(obj, 'DEFAULT_CSS', None)
            if isinstance(css_content, str) and css_content:
                css_classes, css_ids = extract_css_selectors(css_content)
                widget_classes.update(css_classes)
                widget_ids.update(css_ids)

            component_classes = getattr(obj, 'COMPONENT_CLASSES', None)
            if isinstance(component_classes, (set, frozenset, list, tuple)):
                widget_classes.update(
                    component_class
                    for component_class in component_classes
                    if isinstance(component_class, str) and not component_class.startswith('-')
                )

    return widget_classes, widget_ids


def find_used_selectors(
    src_dir: Path,
    classes: set[str],
    ids: set[str],
    max_workers: int | None = None,
) -> tuple[set[str], set[str]]:
    """Find which CSS selectors are actually used in the codebase."""
    used_classes = set()
    used_ids = set()
    python_files = list(src_dir.rglob('*.py'))

    try:
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(_search_file_worker, (py_file, classes, ids)): py_file
                for py_file in python_files
            }
            for future in as_completed(future_to_file):
                found_classes, found_ids = future.result()
                used_classes.update(found_classes)
                used_ids.update(found_ids)
    except (OSError, PermissionError):
        for py_file in python_files:
            found_classes, found_ids = _search_file_worker((py_file, classes, ids))
            used_classes.update(found_classes)
            used_ids.update(found_ids)

    return used_classes, used_ids


def build_project_inheritance_map(project_css: list[ProjectClassCss]) -> dict[str, set[str]]:
    """Build a map of class -> all project ancestors by qualified name."""
    simple_name_to_qualified: dict[str, set[str]] = defaultdict(set)
    for cls in project_css:
        simple_name_to_qualified[cls.qualified_name.rsplit('.', 1)[-1]].add(cls.qualified_name)

    direct_bases: dict[str, set[str]] = defaultdict(set)
    for cls in project_css:
        for base in cls.bases:
            if base in simple_name_to_qualified and len(simple_name_to_qualified[base]) == 1:
                direct_bases[cls.qualified_name].update(simple_name_to_qualified[base])

    all_ancestors: dict[str, set[str]] = {}

    def walk(name: str) -> set[str]:
        if name in all_ancestors:
            return all_ancestors[name]

        ancestors = set(direct_bases.get(name, set()))
        for parent in tuple(ancestors):
            ancestors.update(walk(parent))
        all_ancestors[name] = ancestors
        return ancestors

    for cls in project_css:
        walk(cls.qualified_name)

    return all_ancestors


def are_related_owners(owner_a: str, owner_b: str, ancestors: dict[str, set[str]]) -> bool:
    """Return True when two CSS owners are in the same project inheritance chain."""
    if owner_a == owner_b:
        return True
    return owner_a in ancestors.get(owner_b, set()) or owner_b in ancestors.get(owner_a, set())


def find_duplicate_definitions(
    definitions: list[CssDefinition],
    project_css: list[ProjectClassCss],
) -> dict[str, list[CssDefinition]]:
    """Find duplicate selector definitions.

    Reports both:
    - repeated definitions within the same source / owner when they redefine
      overlapping CSS properties
    - duplicate definitions across unrelated owners

    Ignores likely inheritance-based overrides across related owners.
    """
    ancestors = build_project_inheritance_map(project_css)
    grouped: dict[str, list[CssDefinition]] = defaultdict(list)
    for definition in definitions:
        grouped[definition.selector].append(definition)

    duplicates: dict[str, list[CssDefinition]] = {}
    for selector, selector_definitions in grouped.items():
        if len(selector_definitions) < 2:
            continue

        definitions_by_source_owner: dict[tuple[Path, str], list[CssDefinition]] = defaultdict(list)
        for definition in selector_definitions:
            definitions_by_source_owner[(definition.source, definition.owner)].append(definition)

        has_same_source_duplicates = False
        for source_definitions in definitions_by_source_owner.values():
            if len(source_definitions) < 2:
                continue

            seen_property_sets: list[frozenset[str]] = []
            for definition in source_definitions:
                if any(
                    existing_properties & definition.properties
                    for existing_properties in seen_property_sets
                ):
                    has_same_source_duplicates = True
                    break
                seen_property_sets.append(definition.properties)

            if has_same_source_duplicates:
                break

        unrelated_definitions: list[CssDefinition] = []
        for definition in selector_definitions:
            if not unrelated_definitions:
                unrelated_definitions.append(definition)
                continue

            if all(
                not are_related_owners(definition.owner, existing.owner, ancestors)
                for existing in unrelated_definitions
            ):
                unrelated_definitions.append(definition)

        if has_same_source_duplicates or len(unrelated_definitions) >= 2:
            duplicates[selector] = selector_definitions

    return duplicates


def find_single_id_default_css_candidates(
    definitions: list[CssDefinition],
    project_css: list[ProjectClassCss],
) -> list[CssDefinition]:
    """Find likely widget-owned global selectors that should move to DEFAULT_CSS.

    This is intentionally conservative and only considers selectors from the
    global TCSS that:
    - reference a single ID selector
    - style that ID's direct child project widget / component state
    - avoid container/layout-only selectors
    """
    candidates: list[CssDefinition] = []
    project_widget_names = {
        project_class_css.qualified_name.rsplit('.', 1)[-1] for project_class_css in project_css
    }

    for definition in definitions:
        if definition.owner != 'src.gojeera.gojeera_tcss':
            continue
        match = SINGLE_ID_WIDGET_CHILD_SELECTOR_RE.fullmatch(definition.selector)
        if match is None:
            continue
        child_widget_name = match.group(2)
        if child_widget_name not in project_widget_names:
            continue
        candidates.append(definition)

    return sorted(candidates, key=lambda item: (str(item.source), item.line, item.selector))


def main() -> int:
    """Main entry point."""
    project_root = Path(__file__).parent.parent
    tcss_file = project_root / 'src' / 'gojeera' / 'gojeera.tcss'
    src_dir = project_root / 'src'

    if not tcss_file.exists():
        sys.stderr.write(f'Error: TCSS file not found: {tcss_file}\n')
        return 1

    if not src_dir.exists():
        sys.stderr.write(f'Error: Source directory not found: {src_dir}\n')
        return 1

    project_css = collect_project_default_css(src_dir)
    textual_parse_errors = compile_textual_css(tcss_file, project_css)

    tcss_content = tcss_file.read_text(encoding='utf-8')
    all_classes, all_ids = extract_css_selectors(tcss_content)
    all_definitions = extract_rule_definitions(
        tcss_content,
        owner='src.gojeera.gojeera_tcss',
        source=tcss_file,
    )

    for project_class_css in project_css:
        css_classes, css_ids = extract_css_selectors(project_class_css.css)
        all_classes.update(css_classes)
        all_ids.update(css_ids)
        all_classes.update(project_class_css.component_classes)
        all_definitions.extend(
            extract_rule_definitions(
                project_class_css.css,
                owner=project_class_css.qualified_name,
                source=project_class_css.source,
            )
        )

    textual_classes, textual_ids = get_textual_builtin_selectors()
    used_classes, used_ids = find_used_selectors(src_dir, all_classes, all_ids)
    used_classes.update(all_classes & textual_classes)
    used_ids.update(all_ids & textual_ids)
    used_classes.update(
        component_class
        for project_class_css in project_css
        for component_class in project_class_css.component_classes
    )

    unused_classes = all_classes - used_classes
    unused_ids = all_ids - used_ids
    duplicate_definitions = find_duplicate_definitions(all_definitions, project_css)
    single_id_candidates = find_single_id_default_css_candidates(all_definitions, project_css)

    has_errors = bool(
        textual_parse_errors
        or unused_classes
        or unused_ids
        or duplicate_definitions
        or single_id_candidates
    )
    if not has_errors:
        return 0

    if textual_parse_errors:
        sys.stderr.write('Textual CSS parse errors:\n')
        for error in textual_parse_errors:
            sys.stderr.write(f'{error}\n')

    if unused_classes:
        sys.stderr.write('Unused classes:\n')
        for class_name in sorted(unused_classes):
            sys.stderr.write(f'  .{class_name}\n')

    if unused_ids:
        sys.stderr.write('Unused IDs:\n')
        for id_name in sorted(unused_ids):
            sys.stderr.write(f'  #{id_name}\n')

    if duplicate_definitions:
        sys.stderr.write('Duplicate selector definitions:\n')
        for selector in sorted(duplicate_definitions):
            sys.stderr.write(f'  {selector}\n')
            for definition in sorted(
                duplicate_definitions[selector],
                key=lambda item: (str(item.source), item.line, item.owner),
            ):
                relative_source = definition.source.relative_to(project_root)
                sys.stderr.write(
                    f'    - {relative_source}:{definition.line} ({definition.owner})\n'
                )

    if single_id_candidates:
        sys.stderr.write(
            'Consider moving likely widget-owned single-ID selectors to DEFAULT_CSS:\n'
        )
        for definition in single_id_candidates:
            relative_source = definition.source.relative_to(project_root)
            sys.stderr.write(f'  {definition.selector}\n')
            sys.stderr.write(f'    - {relative_source}:{definition.line}\n')

    return 1


if __name__ == '__main__':
    sys.exit(main())
