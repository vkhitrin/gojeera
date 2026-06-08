"""Reusable overlay popup menu widget for choosing an option."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Iterable

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.geometry import Offset
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


@dataclass(frozen=True)
class PopupMenuItem:
    """Single option displayed by :class:`PopupMenu`."""

    id: str
    title: str
    description: str = ''
    shortcut: str = ''
    icon: str = ''
    payload: Any = None
    separator: bool = False


class PopupMenuItemWidget(Static):
    """Jumpable visual item in a :class:`PopupMenu`."""

    DEFAULT_CSS = """
    PopupMenuItemWidget {
        height: auto;
        background: $surface-lighten-1;
        color: $text;
    }

    PopupMenuItemWidget.highlighted {
        background: $primary-muted;
        color: $text-primary;
    }
    """

    def __init__(self, item: PopupMenuItem, index: int) -> None:
        self.item = item
        self.item_index = index
        self._title, self._description = PopupMenu.item_lines(item)
        super().__init__('', id=f'popup-menu-item-{item.id}')

    @property
    def menu(self) -> 'PopupMenu | None':
        return self.parent if isinstance(self.parent, PopupMenu) else None

    def render(self) -> Text:
        menu = self.menu
        width = max(1, self.size.width or (menu.content_width if menu else 1))
        if self.item.separator:
            return Text('─' * width)

        text = Text()
        text.append(self._title[:width].ljust(width))
        if self._description:
            text.append('\n')
            text.append(self._description[:width].ljust(width))
        return text

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        if self.item.separator:
            event.stop()
            return
        if menu := self.menu:
            menu.highlighted_index = self.item_index
            menu.refresh_items()
        event.stop()

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        event.stop()
        if self.item.separator:
            return
        if menu := self.menu:
            menu.highlighted_index = self.item_index
            menu._take_focus()
            await menu.action_select_cursor()


class PopupMenu(Static, can_focus=True):
    """Keyboard and mouse navigable overlay popup menu."""

    BINDINGS = [
        Binding('down', 'cursor_down', show=False),
        Binding('up', 'cursor_up', show=False),
        Binding('ctrl+j', 'cursor_down', show=False),
        Binding('ctrl+k', 'cursor_up', show=False),
        Binding('enter', 'select_cursor', show=False),
        Binding('space', 'select_cursor', show=False),
        Binding('escape', 'dismiss', show=False),
    ]

    DEFAULT_CSS = """
    PopupMenu {
        width: auto;
        height: auto;
        min-width: 1;
        min-height: 1;
        background: $surface-lighten-1;
        color: $text;
        padding: 0;
        border: none;
        overlay: screen;
        constrain: none inside;
        position: absolute;
        layer: overlay;
    }

    PopupMenu.loading {
        min-width: 18;
        min-height: 1;
    }

    .popup-menu-loading-indicator,
    .popup-menu-loading-indicator.-textual-loading-indicator {
        background: $surface-lighten-1;
        color: $accent;
    }
    """

    highlighted_index: reactive[int | None] = reactive(None)
    expanded: reactive[bool] = reactive(False)
    blocks_global_actions_when_expanded = True

    class Selected(Message):
        """Posted when an option is selected."""

        def __init__(self, menu: 'PopupMenu', item: PopupMenuItem) -> None:
            self.menu = menu
            self.item = item
            super().__init__()

        @property
        def control(self) -> 'PopupMenu':
            return self.menu

    class Dismissed(Message):
        """Posted when the popup should be dismissed."""

        def __init__(self, menu: 'PopupMenu') -> None:
            self.menu = menu
            super().__init__()

        @property
        def control(self) -> 'PopupMenu':
            return self.menu

    def __init__(
        self,
        items: Iterable[PopupMenuItem] = (),
        *,
        id: str | None = None,
        classes: str | None = None,
        dismiss_on_blur: bool = True,
        anchor: Widget | Callable[[], Widget] | None = None,
    ) -> None:
        self.items: list[PopupMenuItem] = list(items)
        self.dismiss_on_blur = dismiss_on_blur
        self._anchor: Widget | Callable[[], Widget] | None = anchor
        super().__init__('', id=id, classes=classes)
        self.display = False
        self.styles.height = self.content_height
        self.styles.width = self.content_width
        self.highlighted_index = 0 if self.items else None

    @staticmethod
    def item_lines(item: PopupMenuItem) -> tuple[str, str]:
        icon = f' {item.icon} ' if item.icon else ''
        title = f'{icon}{item.title}'
        if item.shortcut:
            title = f'{title}  {item.shortcut}'
        description = f'{" " * len(icon)}{item.description}'
        return title, description

    @property
    def content_width(self) -> int:
        lines = [line for item in self.items for line in self.item_lines(item)]
        return max([1, *map(len, lines)]) + 1

    @property
    def content_height(self) -> int:
        return max(
            1, sum(2 if item.description and not item.separator else 1 for item in self.items)
        )

    def compose(self) -> ComposeResult:
        for index, item in enumerate(self.items):
            yield PopupMenuItemWidget(item, index)

    def on_mount(self) -> None:
        self.refresh_items()

    def set_menu_loading(self, loading: bool) -> None:
        self.set_class(loading, 'loading')
        self.loading = loading
        if loading and self._cover_widget is not None:
            self._cover_widget.add_class('popup-menu-loading-indicator')
            self._cover_widget.styles.background = self.styles.background

    def _take_focus(self) -> None:
        if self.is_attached:
            self.screen.set_focus(self, scroll_visible=False)
            self.focus(scroll_visible=False)

    def _anchor_widget(self) -> Widget | None:
        if self._anchor is None:
            return None
        if isinstance(self._anchor, Widget):
            return self._anchor
        return self._anchor()

    def open(self) -> None:
        """Show this menu below its anchor and focus it."""
        if anchor := self._anchor_widget():
            anchor_region = anchor.region
            self.absolute_offset = Offset(anchor_region.x, anchor_region.y + anchor_region.height)
        self.expanded = True

    def toggle(self) -> None:
        """Toggle this menu relative to its anchor."""
        if self.expanded:
            self.action_dismiss()
            return
        self.open()

    def watch_expanded(self, expanded: bool) -> None:
        self.display = expanded
        if expanded:
            self.call_after_refresh(self._take_focus)

    def _refresh_item_highlight(self, index: int | None) -> None:
        if index is None:
            return
        try:
            child = self.children[index]
        except IndexError:
            return
        if isinstance(child, PopupMenuItemWidget):
            child.set_class(child.item_index == self.highlighted_index, 'highlighted')
            child.refresh()

    def refresh_items(self) -> None:
        for child in self.query(PopupMenuItemWidget):
            child.set_class(child.item_index == self.highlighted_index, 'highlighted')
            child.refresh()

    def watch_highlighted_index(self, old: int | None, new: int | None) -> None:
        self._refresh_item_highlight(old)
        self._refresh_item_highlight(new)

    async def replace_options(self, items: Iterable[PopupMenuItem]) -> None:
        self.items = list(items)
        self.styles.height = self.content_height
        self.styles.width = self.content_width
        self.highlighted_index = 0 if self.items else None
        await self.remove_children()
        await self.mount_all(
            PopupMenuItemWidget(item, index) for index, item in enumerate(self.items)
        )
        self.refresh()

    async def toggle_with_loader(
        self,
        loader: Callable[[], Awaitable[Iterable[PopupMenuItem]]],
    ) -> None:
        """Toggle this menu, loading options asynchronously when opened."""
        self.toggle()
        if not self.expanded:
            return

        self.set_menu_loading(True)
        try:
            await self.replace_options(await loader())
        finally:
            self.set_menu_loading(False)

        if self.expanded:
            self._take_focus()

    def _highlight_delta(self, delta: int) -> None:
        if not self.items or all(item.separator for item in self.items):
            return
        current = self.highlighted_index if self.highlighted_index is not None else 0
        next_index = (current + delta) % len(self.items)
        while self.items[next_index].separator:
            next_index = (next_index + delta) % len(self.items)
        self.highlighted_index = next_index

    def action_cursor_down(self) -> None:
        self._highlight_delta(1)

    def action_cursor_up(self) -> None:
        self._highlight_delta(-1)

    async def action_select_cursor(self) -> None:
        if self.highlighted_index is None or not self.items:
            return
        item = self.items[self.highlighted_index]
        if item.separator:
            return
        self.expanded = False
        self.post_message(self.Selected(self, item))

    def action_dismiss(self) -> None:
        if not self.expanded:
            return
        self.expanded = False
        self.post_message(self.Dismissed(self))

    def _on_blur(self, event: events.Blur) -> None:
        _ = event
        if not self.dismiss_on_blur:
            return
        self.action_dismiss()
        self.suppress_click()

    async def _on_click(self, event: events.Click) -> None:
        event.prevent_default()
        event.stop()
        self._take_focus()

    async def _on_key(self, event: events.Key) -> None:
        if event.key in {'down', 'j', 'ctrl+j'}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if event.key in {'up', 'k', 'ctrl+k'}:
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return
        if event.key in {'enter', 'space'}:
            event.prevent_default()
            event.stop()
            await self.action_select_cursor()
            return
        if event.key in {'escape', 'esc'}:
            event.prevent_default()
            event.stop()
            self.action_dismiss()
            return
        await super()._on_key(event)
