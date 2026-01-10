from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
import importlib
import inspect
from pathlib import Path
import re
import sys


def extract_css_selectors(tcss_content: str) -> tuple[set[str], set[str]]:
    """Extract class and ID selectors from TCSS content.

    Args:
        tcss_content: The content of the TCSS file.

    Returns:
        A tuple of (class_names, id_names) sets.
    """
    classes = set()
    ids = set()

    class_pattern = r'(?<![0-9])\.([a-zA-Z_][a-zA-Z0-9_-]*)'

    id_pattern = r'#([a-zA-Z_][a-zA-Z0-9_-]*)'

    for match in re.finditer(class_pattern, tcss_content):
        class_name = match.group(1)

        if not class_name.startswith('-'):
            classes.add(class_name)

    for match in re.finditer(id_pattern, tcss_content):
        id_name = match.group(1)

        if not id_name.startswith('-'):
            ids.add(id_name)

    return classes, ids


def _search_file_worker(args: tuple[Path, set[str], set[str]]) -> tuple[set[str], set[str]]:
    """Worker function to search a single file for classes and IDs.

    Args:
        args: Tuple of (file_path, classes_to_search, ids_to_search).

    Returns:
        Tuple of (found_classes, found_ids) sets.
    """
    file_path, classes, ids = args
    return search_in_file(file_path, classes), search_in_file(file_path, ids)


def search_in_file(file_path: Path, search_terms: set[str]) -> set[str]:
    """Search for terms in a file and return which ones were found.

    Args:
        file_path: Path to the file to search.
        search_terms: Set of terms to search for.

    Returns:
        Set of terms that were found in the file.
    """
    try:
        content = file_path.read_text(encoding='utf-8')
        found = set()
        for term in search_terms:
            patterns = [
                re.compile(rf'["\'].*{re.escape(term)}.*["\']'),
                re.compile(rf'\bid\s*=\s*["\'].*{re.escape(term)}.*["\']'),
                re.compile(rf'\bclasses\s*=\s*["\'].*{re.escape(term)}.*["\']'),
                re.compile(rf'\badd_class\(["\'].*{re.escape(term)}.*["\']\)'),
                re.compile(rf'\bremove_class\(["\'].*{re.escape(term)}.*["\']\)'),
                re.compile(rf'\bhas_class\(["\'].*{re.escape(term)}.*["\']\)'),
                re.compile(rf'\bset_class\(["\'].*{re.escape(term)}.*["\']\)'),
            ]

            for pattern in patterns:
                if pattern.search(content):
                    found.add(term)
                    break

        return found
    except Exception as e:
        msg = f'Warning: Could not read {file_path}: {e}'
        sys.stderr.write(f'{msg}\n')
        return set()


def get_textual_builtin_selectors() -> tuple[set[str], set[str]]:
    """Get CSS selectors from Textual's built-in and custom widgets.

    Checks both Textual's built-in widgets and custom third-party widgets
    used by gojeera (textual-autocomplete, textual-fspicker, textual-image,
    textual-jumper, textual-tags).

    Returns:
        A tuple of (widget_classes, widget_ids) sets.
    """
    widget_classes = set()
    widget_ids = set()

    widget_modules = [
        'textual.widgets',
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

            widget_names = []
            if hasattr(widget_module, '__all__'):
                widget_names = widget_module.__all__
            else:
                widget_names = [
                    name
                    for name in dir(widget_module)
                    if not name.startswith('_') and name[0].isupper()
                ]

            for widget_name in widget_names:
                try:
                    obj = getattr(widget_module, widget_name)

                    if not inspect.isclass(obj):
                        continue

                    css_name = re.sub(r'(?<!^)(?=[A-Z])', '-', widget_name).lower()
                    widget_classes.add(css_name)

                    if hasattr(obj, 'DEFAULT_CSS') and obj.DEFAULT_CSS:
                        css_content = obj.DEFAULT_CSS

                        class_pattern = r'(?<![0-9])\.([a-zA-Z_][a-zA-Z0-9_-]*)'
                        id_pattern = r'#([a-zA-Z_][a-zA-Z0-9_-]*)'

                        for match in re.finditer(class_pattern, css_content):
                            cls = match.group(1)
                            if not cls.startswith('-'):
                                widget_classes.add(cls)

                        for match in re.finditer(id_pattern, css_content):
                            id_name = match.group(1)
                            if not id_name.startswith('-'):
                                widget_ids.add(id_name)

                except (TypeError, AttributeError, ImportError):
                    continue

        except ImportError:
            continue

    return widget_classes, widget_ids


def find_used_selectors(
    src_dir: Path,
    classes: set[str],
    ids: set[str],
    max_workers: int | None = None,
) -> tuple[set[str], set[str]]:
    """Find which CSS selectors are actually used in the codebase.

    Args:
        src_dir: Root directory to search.
        classes: Set of class names to search for.
        ids: Set of ID names to search for.
        max_workers: Maximum number of parallel workers (defaults to CPU count).

    Returns:
        A tuple of (used_classes, used_ids) sets.
    """
    used_classes = set()
    used_ids = set()

    python_files = list(src_dir.rglob('*.py'))

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(_search_file_worker, (py_file, classes, ids)): py_file
            for py_file in python_files
        }

        for future in as_completed(future_to_file):
            found_classes, found_ids = future.result()
            used_classes.update(found_classes)
            used_ids.update(found_ids)

    return used_classes, used_ids


def main() -> int:
    """Main entry point."""

    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    tcss_file = project_root / 'src' / 'gojeera' / 'gojeera.tcss'
    src_dir = project_root / 'src'

    if not tcss_file.exists():
        msg = f'Error: TCSS file not found: {tcss_file}'
        sys.stderr.write(f'{msg}\n')
        return 1

    if not src_dir.exists():
        msg = f'Error: Source directory not found: {src_dir}'
        sys.stderr.write(f'{msg}\n')
        return 1

    tcss_content = tcss_file.read_text(encoding='utf-8')
    all_classes, all_ids = extract_css_selectors(tcss_content)

    textual_classes, textual_ids = get_textual_builtin_selectors()

    used_classes, used_ids = find_used_selectors(src_dir, all_classes, all_ids)

    used_classes.update(all_classes & textual_classes)
    used_ids.update(all_ids & textual_ids)

    unused_classes = all_classes - used_classes
    unused_ids = all_ids - used_ids

    textual_matched_classes = all_classes & textual_classes
    textual_matched_ids = all_ids & textual_ids

    sys.stdout.write(f'Classes: {len(unused_classes)}/{len(all_classes)} unused')
    if textual_matched_classes:
        sys.stdout.write(f' ({len(textual_matched_classes)} matched Textual widgets)')
    sys.stdout.write('\n')

    sys.stdout.write(f'IDs:     {len(unused_ids)}/{len(all_ids)} unused')
    if textual_matched_ids:
        sys.stdout.write(f' ({len(textual_matched_ids)} matched Textual widgets)')
    sys.stdout.write('\n')

    if textual_matched_classes:
        sys.stdout.write('\nClasses matched to Textual widgets:\n')
        for cls in sorted(textual_matched_classes):
            sys.stdout.write(f'  .{cls}\n')

    if textual_matched_ids:
        sys.stdout.write('\nIDs matched to Textual widgets:\n')
        for id_name in sorted(textual_matched_ids):
            sys.stdout.write(f'  #{id_name}\n')

    if unused_classes:
        sys.stdout.write('\nUnused classes:\n')
        for cls in sorted(unused_classes):
            sys.stdout.write(f'  .{cls}\n')

    if unused_ids:
        sys.stdout.write('\nUnused IDs:\n')
        for id_name in sorted(unused_ids):
            sys.stdout.write(f'  #{id_name}\n')

    return 1 if (unused_classes or unused_ids) else 0


if __name__ == '__main__':
    sys.exit(main())
