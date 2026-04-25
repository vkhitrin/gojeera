"""Tests for panel_picker_screen.py component."""

from gojeera.components.screens.panel_picker_screen import PanelPickerScreen

from .test_helpers import (
    CommentPickerFlowConfig,
    create_comment_picker_flow_helpers,
    with_snapshot_assertion,
)

(
    _open_panel_picker_via_full_flow,
    _open_panel_picker_via_full_flow_with_selection,
    _insert_panel_and_return_to_comment_screen,
) = create_comment_picker_flow_helpers(
    config=CommentPickerFlowConfig(
        action_name='action_insert_alert',
        screen_type=PanelPickerScreen,
        options_attr='ALERT_TYPES',
        select_attr='option_select',
        insert_button_selector='#alert-button-insert',
        post_insert_focus_save_button=True,
    )
)


def create_open_panel_picker_via_full_flow():
    return _open_panel_picker_via_full_flow


def create_open_panel_picker_via_full_flow_with_selection():
    return _open_panel_picker_via_full_flow_with_selection


def create_insert_panel_and_return_to_comment_screen():
    return _insert_panel_and_return_to_comment_screen


class TestPanelPickerScreen:
    """Snapshot tests to verify PanelPickerScreen via complete user navigation flow."""

    @with_snapshot_assertion(create_open_panel_picker_via_full_flow())
    def test_panel_initial_state(self):
        """Snapshot: Panel Picker via full flow (Search → Comments → Add Comment → Insert Panel)."""

    @with_snapshot_assertion(create_open_panel_picker_via_full_flow_with_selection())
    def test_panel_picker_with_selection(self):
        """Snapshot: Panel Picker via full flow with panel selected (Insert button enabled)."""

    @with_snapshot_assertion(create_insert_panel_and_return_to_comment_screen())
    def test_panel_insert_panel(self):
        """Snapshot: CommentScreen after panel inserted (verify panel text in textarea)."""
