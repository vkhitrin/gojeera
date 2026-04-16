from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Select

from gojeera.widgets.extended_jumper import set_jump_mode
from gojeera.widgets.vim_select import VimSelect

if TYPE_CHECKING:
    from gojeera.app import MainScreen


class WorkItemSearchResultsControls(Horizontal):
    DEFAULT_CSS = """
    WorkItemSearchResultsControls {
        height: auto;
        width: 1fr;
        layout: grid;
        grid-size: 3;
        grid-columns: 1fr 3 3;
        grid-gutter: 1;
        padding: 0;
        margin: 0 0 1 0;
    }

    WorkItemSearchResultsControls > #search-results-order-by {
        width: 100%;
        min-width: 0;
    }

    WorkItemSearchResultsControls > #search-results-order-direction-button {
        width: 3;
        min-width: 3;
        padding: 0;
    }

    WorkItemSearchResultsControls > #search-results-refresh-button {
        width: 3;
        min-width: 3;
        padding: 0;
    }

    WorkItemSearchResultsControls > Button.-style-default > Static {
        color: $text-primary;
        background: transparent;
        text-style: bold;
    }

    WorkItemSearchResultsControls > Button.-style-default {
        background: $primary-muted;
        color: $text-primary;
        text-align: center;
        content-align: center middle;
        border: none;
        border-top: none;
        border-bottom: none;
    }

    WorkItemSearchResultsControls > Button.-style-default:hover {
        background: $primary;
        color: $text;
        border: none;
        border-top: none;
        border-bottom: none;
    }

    WorkItemSearchResultsControls > Button.-style-default:hover > Static {
        color: $text;
        background: transparent;
        text-style: bold;
    }

    WorkItemSearchResultsControls > Button.-style-default:disabled {
        background: $primary-darken-3;
        color: $text-disabled;
    }

    WorkItemSearchResultsControls > Button.-style-default:disabled > Static {
        color: $text-disabled;
        background: transparent;
        text-style: bold;
    }

    WorkItemSearchResultsControls > Button.-style-default:disabled:hover {
        background: $primary-darken-3;
        color: $text-disabled;
    }

    WorkItemSearchResultsControls > Button.-style-default:disabled:hover > Static {
        color: $text-disabled;
        background: transparent;
        text-style: bold;
    }

    WorkItemSearchResultsControls > Button.-style-default:focus {
        background: $primary-muted;
        color: $text-primary;
        text-style: bold;
        border: none;
        border-top: none;
        border-bottom: none;
    }

    WorkItemSearchResultsControls > Button.-style-default:focus > Static {
        color: $text-primary;
        background: transparent;
        text-style: bold;
    }
    """

    ORDER_BY_OPTIONS = [
        ('Created', 'created'),
        ('Key', 'key'),
        ('Last viewed', 'lastViewed'),
        ('Priority', 'priority'),
        ('Resolved', 'resolved'),
        ('Status', 'status'),
        ('Updated', 'updated'),
    ]

    def compose(self) -> ComposeResult:
        yield VimSelect(
            options=[(label, value) for label, value in self.ORDER_BY_OPTIONS],
            prompt='ORDER BY',
            id='search-results-order-by',
            value='created',
            allow_blank=False,
            compact=True,
        )
        yield Button('⇊', id='search-results-order-direction-button', compact=True)
        yield Button('↺', id='search-results-refresh-button', compact=True)

    @property
    def order_by(self) -> VimSelect:
        return self.query_one('#search-results-order-by', VimSelect)

    @property
    def direction_button(self) -> Button:
        return self.query_one('#search-results-order-direction-button', Button)

    @property
    def refresh_button(self) -> Button:
        return self.query_one('#search-results-refresh-button', Button)

    def on_mount(self) -> None:
        self.display = False
        set_jump_mode(self.order_by, 'focus')
        set_jump_mode(self.direction_button, 'click')
        set_jump_mode(self.refresh_button, 'click')

    @staticmethod
    def _button_label_text(button: Button) -> str:
        return getattr(button.label, 'plain', str(button.label))

    @property
    def current_order_by(self) -> str:
        value = self.order_by.value
        field = str(value) if value else 'created'
        direction = 'ASC' if self._button_label_text(self.direction_button) == '⇈' else 'DESC'
        return f'{field} {direction}'

    def set_search_mode(self, mode: str, search_data: dict | None = None) -> None:
        ordering_disabled = mode == 'jql'
        refresh_disabled = False
        if mode == 'jql':
            jql_value = ''
            if search_data is not None:
                jql_value = str(search_data.get('jql') or '').strip()
            refresh_disabled = not bool(jql_value)

        self.order_by.disabled = ordering_disabled
        self.direction_button.disabled = ordering_disabled
        self.refresh_button.disabled = refresh_disabled

        set_jump_mode(self.order_by, None if ordering_disabled else 'focus')
        set_jump_mode(self.direction_button, None if ordering_disabled else 'click')
        set_jump_mode(self.refresh_button, None if refresh_disabled else 'click')

    def _rerun_active_search(self) -> None:
        screen = cast('MainScreen', self.screen)
        work_items_container = self.parent
        if getattr(work_items_container, 'search_active', False) is not True:
            return
        screen._rerun_active_search()

    @on(Button.Pressed, '#search-results-refresh-button')
    def handle_refresh(self) -> None:
        screen = cast('MainScreen', self.screen)
        work_items_container = self.parent
        if (
            getattr(work_items_container, 'search_active', False) is not True
            or screen.is_search_request_in_progress
        ):
            return
        self._rerun_active_search()

    @on(Button.Pressed, '#search-results-order-direction-button')
    async def handle_order_direction_toggle(self) -> None:
        button = self.direction_button
        if button.disabled:
            return
        button.label = '⇈' if self._button_label_text(button) == '⇊' else '⇊'
        self._rerun_active_search()

    @on(Select.Changed, '#search-results-order-by')
    async def handle_order_by_changed(self, event: Select.Changed) -> None:
        if not event.value or str(event.value) == Select.BLANK:
            return
        if self.order_by.disabled:
            return
        self._rerun_active_search()
