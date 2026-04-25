"""Tests for decision_picker_screen.py component."""

from gojeera.components.screens.decision_picker_screen import DecisionPickerScreen

from .test_helpers import (
    CommentPickerFlowConfig,
    create_comment_picker_flow_helpers,
    with_snapshot_assertion,
)

(
    _open_decision_picker_via_full_flow,
    _open_decision_picker_via_full_flow_with_selection,
    _insert_decision_and_return_to_comment_screen,
) = create_comment_picker_flow_helpers(
    config=CommentPickerFlowConfig(
        action_name='action_insert_decision',
        screen_type=DecisionPickerScreen,
        options_attr='DECISION_TYPES',
        select_attr='option_select',
        insert_button_selector='#decision-button-insert',
        cancel_selector='#decision-button-quit',
        wait_for_enable=True,
    )
)


def create_open_decision_picker_via_full_flow():
    return _open_decision_picker_via_full_flow


def create_open_decision_picker_via_full_flow_with_selection():
    return _open_decision_picker_via_full_flow_with_selection


def create_insert_decision_and_return_to_comment_screen():
    return _insert_decision_and_return_to_comment_screen


class TestDecisionPickerScreen:
    @with_snapshot_assertion(create_open_decision_picker_via_full_flow())
    def test_decision_screen_initial_state(self):
        pass

    @with_snapshot_assertion(create_open_decision_picker_via_full_flow_with_selection())
    def test_decision_screen_picker_with_selection(self):
        pass

    @with_snapshot_assertion(create_insert_decision_and_return_to_comment_screen())
    def test_decision_insert_decision(self):
        pass
