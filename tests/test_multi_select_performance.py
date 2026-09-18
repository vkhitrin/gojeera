from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from textual_tags import Tag

from gojeera.utils.data.fields import FieldMode
from gojeera.widgets.selection.multi_select import ExtendedTag, MultiSelect


async def test_replace_selected_tags_mounts_all_tags_in_one_batch(monkeypatch) -> None:
    monkeypatch.setattr(MultiSelect, 'watch_selected_tags', lambda self: None)
    widget = MultiSelect(
        mode=FieldMode.UPDATE,
        field_id='components',
        options=[('API', '1'), ('UI', '2'), ('Platform', '3')],
    )
    remove_children = AsyncMock()
    mount = AsyncMock()
    monkeypatch.setattr(widget, 'remove_children', remove_children)
    monkeypatch.setattr(widget, 'mount', mount)
    monkeypatch.setattr(widget, '_sync_dropdown_arrow_visibility', lambda: None)

    await widget._replace_selected_tag_widgets(['API', 'UI', 'Platform'])

    remove_children.assert_awaited_once_with(Tag)
    mount.assert_awaited_once()
    mount_call = mount.await_args
    assert mount_call is not None
    assert all(isinstance(tag, ExtendedTag) for tag in mount_call.args)
    assert [str(tag.value) for tag in mount_call.args] == ['API', 'UI', 'Platform']
    assert widget.selected_tags == {'API', 'UI', 'Platform'}


def test_dropdown_arrow_sync_skips_redundant_class_write(monkeypatch) -> None:
    widget = MultiSelect(
        mode=FieldMode.UPDATE,
        field_id='components',
        options=[('API', '1')],
    )
    set_class = Mock()
    tag_input = SimpleNamespace(
        has_class=lambda _class_name: False,
        set_class=set_class,
    )
    monkeypatch.setattr(MultiSelect, 'multi_select_tag_input', tag_input)
    monkeypatch.setattr(widget, '_has_remaining_options', lambda: True)

    widget._sync_dropdown_arrow_visibility()

    set_class.assert_not_called()
