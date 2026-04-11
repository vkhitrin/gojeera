from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static

from gojeera.components.parent_work_item_screen import ParentWorkItemScreen
from gojeera.models import JiraWorkItem
from gojeera.utils.fields import supports_parent_work_item
from gojeera.widgets.extended_button import ExtendedButton
from gojeera.widgets.extended_jumper import set_jump_mode
from gojeera.widgets.gojeera_markdown import (
    WORK_ITEM_TOOLTIP_FIELDS,
    build_loading_work_item_tooltip,
    build_work_item_tooltip,
)

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class WorkItemBreadcrumb(Horizontal, can_focus=False):
    """Breadcrumb widget with an inline parent action."""

    DEFAULT_CSS = """
    WorkItemBreadcrumb {
        height: auto;
        width: 1fr;
        padding: 0;
        color: $text-muted;
        background: $background;
        layout: horizontal;
    }

    WorkItemBreadcrumb > .breadcrumb-text {
        width: auto;
        color: $text-muted;
        text-style: bold;
        padding: 0;
    }

    WorkItemBreadcrumb > .breadcrumb-separator {
        width: auto;
        color: $text-muted;
        text-style: bold;
        padding: 0 1 0 1;
    }

    #breadcrumb-project-sep {
        padding: 0 0 0 1;
    }

    #breadcrumb-parent-sep {
        padding: 0 1 0 0;
    }

    WorkItemBreadcrumb > .breadcrumb-parent-work_item {
        width: auto;
        min-width: 0;
        margin: 0;
        color: $accent;
        text-style: bold;
        padding: 0;
        background: transparent;
        border: none;
        tint: transparent;
        content-align: left middle;
    }

    WorkItemBreadcrumb > .breadcrumb-parent-work_item:hover {
        color: $accent-lighten-3;
        text-style: bold;
        background: transparent;
        border: none;
        tint: transparent;
    }

    WorkItemBreadcrumb > .breadcrumb-parent-work_item:focus {
        color: $accent-lighten-3;
        text-style: bold;
        background: transparent;
        border: none;
        tint: transparent;
    }

    WorkItemBreadcrumb > .breadcrumb-parent-work_item.-active {
        color: $accent-lighten-3;
        text-style: bold;
        background: transparent;
        border: none;
        tint: transparent;
    }
    """

    def __init__(self):
        super().__init__(id='work-item-breadcrumb')
        self.can_focus = False
        self.display = False
        self._work_item: JiraWorkItem | None = None
        self._parent_tooltip_cache: dict[str, Text] = {}
        self._skip_next_parent_action_press = False

    def compose(self) -> ComposeResult:
        project = Static('', classes='breadcrumb-text', id='breadcrumb-project')
        project.display = False
        yield project

        project_separator = Static('/', classes='breadcrumb-separator', id='breadcrumb-project-sep')
        project_separator.display = False
        yield project_separator

        yield ExtendedButton(
            '',
            classes='breadcrumb-parent-work_item',
            id='breadcrumb-parent-work_item',
            compact=True,
        )

        parent_separator = Static('/', classes='breadcrumb-separator', id='breadcrumb-parent-sep')
        parent_separator.display = False
        yield parent_separator

        yield Static('', classes='breadcrumb-text', id='breadcrumb-current')

    @property
    def project_widget(self) -> Static:
        return self.query_one('#breadcrumb-project', Static)

    @property
    def project_separator_widget(self) -> Static:
        return self.query_one('#breadcrumb-project-sep', Static)

    @property
    def parent_action_widget(self) -> ExtendedButton:
        return self.query_one('#breadcrumb-parent-work_item', ExtendedButton)

    @property
    def parent_separator_widget(self) -> Static:
        return self.query_one('#breadcrumb-parent-sep', Static)

    @property
    def current_work_item_widget(self) -> Static:
        return self.query_one('#breadcrumb-current', Static)

    def _reset_parent_action_active_state(self) -> None:
        self.parent_action_widget.remove_class('-active')
        self.screen.set_focus(None)

    def _sync_parent_action_jump_mode(self, parent_supported: bool) -> None:
        set_jump_mode(self.parent_action_widget, 'click' if parent_supported else None)

    def handle_parent_work_item_selected(self, data: dict[str, str] | None) -> None:
        if data:
            self.run_worker(self._update_parent_work_item(data), exclusive=False)

    async def open_parent_work_item_screen(self) -> None:
        if self._work_item is None:
            return

        self._reset_parent_action_active_state()
        await self.app.push_screen(
            ParentWorkItemScreen(work_item=self._work_item),
            callback=self.handle_parent_work_item_selected,
        )

    async def _load_parent_tooltip(self, parent_key: str) -> None:
        application = cast('JiraApp', self.app)
        response = await application.api.get_work_item(
            work_item_id_or_key=parent_key,
            fields=WORK_ITEM_TOOLTIP_FIELDS,
        )
        if not response.success or not response.result or not response.result.work_items:
            return

        work_item = response.result.work_items[0]
        tooltip = build_work_item_tooltip(
            getattr(work_item, 'work_item_type_name', '') or 'Work Item',
            getattr(work_item, 'summary', '') or parent_key,
            getattr(getattr(work_item, 'status', None), 'name', '') or 'Unknown',
        )
        tooltip.append('\n')
        tooltip.append('Left mouse click to change parent work item', style='dim')
        self._parent_tooltip_cache[parent_key] = tooltip

        if self._work_item is not None and self._work_item.parent_key.strip() == parent_key:
            self.parent_action_widget.tooltip = tooltip

    def _refresh_loaded_work_item_parent_fields(
        self, screen: 'MainScreen', work_item: JiraWorkItem, parent_key: str
    ) -> None:
        work_item.parent_work_item_key = parent_key or None
        work_item.parent_work_item_type = None

        self.set_work_item(work_item)
        screen.information_panel.work_item = work_item
        screen.work_item_info_container.work_item = work_item
        screen.work_item_fields_widget.work_item = work_item

    async def _update_parent_work_item(self, data: dict[str, str]) -> None:
        work_item = self._work_item
        if work_item is None:
            return

        parent_key = (data.get('parent_key') or '').strip()
        current_parent_key = work_item.parent_key.strip()

        if parent_key == current_parent_key:
            return

        application = cast('JiraApp', self.app)
        screen = cast('MainScreen', self.screen)

        try:
            response = await application.api.update_work_item(
                work_item=work_item, updates={'parent': parent_key}
            )
        except Exception as e:
            self.notify(
                f'Failed to update the parent work item: {e}',
                severity='error',
                title=work_item.key,
            )
            return

        if response.success:
            self._refresh_loaded_work_item_parent_fields(screen, work_item, parent_key)
            self.notify(f'Parent updated for {work_item.key}', title=work_item.key)
            await screen.fetch_work_items(work_item.key)
        else:
            self.notify(
                f'Failed to update the parent work item: {response.error}',
                severity='error',
                title=work_item.key,
            )

    def set_work_item(self, work_item: JiraWorkItem | None) -> None:
        self._work_item = work_item

        if work_item is None:
            self.project_widget.update('')
            self.project_widget.display = False
            self.project_separator_widget.display = False
            self.parent_action_widget.display = False
            self._sync_parent_action_jump_mode(False)
            self.parent_action_widget.label = ''
            self.parent_action_widget.tooltip = None
            self.parent_separator_widget.display = False
            self.current_work_item_widget.update('')
            self.display = False
            return

        project_text = (
            work_item.project.name if work_item.project and work_item.project.name else ''
        )
        parent_supported = supports_parent_work_item(work_item)
        if work_item.parent_key and work_item.parent_key.strip():
            parent_text = Text()
            if work_item.parent_work_item_type:
                parent_text.append(f'[{work_item.parent_work_item_type}] ')
            parent_text.append(work_item.parent_key.strip())
        else:
            parent_text = Text('+ Add parent')

        current_text = Text()
        if work_item.work_item_type and work_item.work_item_type.name:
            current_text.append(f'[{work_item.work_item_type.name}] ')
        current_text.append(work_item.key)

        self.project_widget.update(project_text)
        self.project_widget.display = bool(project_text)
        self.project_separator_widget.display = bool(project_text)

        self.parent_action_widget.display = parent_supported
        self._sync_parent_action_jump_mode(parent_supported)
        if parent_supported:
            self.parent_action_widget.label = parent_text
            parent_key = work_item.parent_key.strip()
            if parent_key:
                cached_tooltip = self._parent_tooltip_cache.get(parent_key)
                if cached_tooltip is not None:
                    self.parent_action_widget.tooltip = cached_tooltip
                else:
                    self.parent_action_widget.tooltip = build_loading_work_item_tooltip()
                    self.run_worker(self._load_parent_tooltip(parent_key), exclusive=False)
            else:
                self.parent_action_widget.tooltip = None
        else:
            self.parent_action_widget.tooltip = None
        self.parent_separator_widget.display = parent_supported

        self.current_work_item_widget.update(current_text)
        self.display = True

    @on(ExtendedButton.Pressed, '#breadcrumb-parent-work_item')
    async def handle_parent_action_pressed(self) -> None:
        if self._work_item is None or not supports_parent_work_item(self._work_item):
            return

        if self._skip_next_parent_action_press:
            self._skip_next_parent_action_press = False
            self._reset_parent_action_active_state()
            return

        await self.open_parent_work_item_screen()

    def _event_targets_parent_action(self, event: events.MouseDown) -> bool:
        return self.parent_action_widget.region.contains(*event.screen_offset)

    async def on_mouse_down(self, event: events.MouseDown) -> None:
        if (
            not event.ctrl
            or self._work_item is None
            or not supports_parent_work_item(self._work_item)
        ):
            return

        if not self._event_targets_parent_action(event):
            return

        self._skip_next_parent_action_press = True
        event.prevent_default()
        event.stop()
        self._reset_parent_action_active_state()
        await self.load_parent_work_item()

    async def load_parent_work_item(self) -> None:
        if self._work_item is None:
            return

        parent_key = self._work_item.parent_key.strip()
        if not parent_key:
            return

        fetch_work_items = getattr(self.screen, 'fetch_work_items', None)
        if callable(fetch_work_items):
            await fetch_work_items(parent_key)
