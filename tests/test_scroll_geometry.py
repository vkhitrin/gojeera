from rich.cells import cell_len

from gojeera.utils.ui.scroll_geometry import (
    _wrap_text_cell_aware_cached,
    wrap_text_cell_aware,
)


def test_wrap_text_cell_aware_reuses_cached_layout_without_sharing_mutable_lists():
    _wrap_text_cell_aware_cached.cache_clear()

    first = wrap_text_cell_aware('A summary with repeated layout work', 12)
    first.append('changed by caller')
    second = wrap_text_cell_aware('A summary with repeated layout work', 12)

    assert 'changed by caller' not in second
    assert _wrap_text_cell_aware_cached.cache_info().hits == 1


def test_wrap_text_cell_aware_keeps_unicode_graphemes_within_terminal_width():
    lines = wrap_text_cell_aware('deploy-👩\u200d💻-界界界-with-a-long-token', 8)

    assert ''.join(lines) == 'deploy-👩\u200d💻-界界界-with-a-long-token'
    assert all(cell_len(line) <= 8 for line in lines)
