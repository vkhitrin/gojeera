import pytest
from textual.app import App
from textual.widgets import Input
from textual_autocomplete import TargetState

from gojeera.widgets.search.search_autocomplete import SearchAutoComplete


@pytest.mark.parametrize('label', ['Team', 'Team (shared)'])
@pytest.mark.parametrize('long_expression', [False, True])
async def test_same_name_filters_complete_the_selected_full_expression(label, long_expression):
    prefix = 'summary ~ "' + 'x' * 100 + '" AND ' if long_expression else ''
    first = prefix + 'project = FIRST'
    second = prefix + 'project = SECOND'
    target = Input()
    autocomplete = SearchAutoComplete(
        target,
        jql_filters=[
            {'label': label, 'expression': first, 'source': 'local', 'starred': False},
            {'label': label, 'expression': second, 'source': 'remote', 'starred': True},
        ],
    )
    async with App().run_test() as pilot:
        await pilot.app.mount(target, autocomplete)
        target.focus()
        target.value = label
        await pilot.pause()
        assert autocomplete.option_list.option_count == 2
        if long_expression:
            assert autocomplete._candidates[0].main == autocomplete._candidates[1].main

        autocomplete.action_show()
        autocomplete.option_list.highlighted = 0
        await pilot.press('enter')
        assert target.value == second
        assert target.cursor_position == len(second)

        target.value = label
        await pilot.pause()
        autocomplete.action_show()
        autocomplete.option_list.highlighted = 1
        await pilot.press('tab')
        assert target.value == first


async def test_history_and_filter_display_collisions_do_not_change_completion():
    target = Input()
    history = 'Team (project = ENG)'
    autocomplete = SearchAutoComplete(
        target,
        history_queries=[history],
        jql_filters=[{'label': 'Team', 'expression': 'project = ENG'}],
    )
    async with App().run_test() as pilot:
        await pilot.app.mount(target, autocomplete)
        target.focus()
        await pilot.pause()
        autocomplete._show_all_candidates()
        autocomplete._complete(1)
        assert target.value == 'project = ENG'
        autocomplete._show_all_candidates()
        autocomplete._complete(0)
        assert target.value == history


async def test_candidate_search_uses_full_label_and_preserves_full_jql():
    target = Input()
    autocomplete = SearchAutoComplete(
        target,
        jql_filters=[
            {'label': 'Team (shared)', 'expression': '  project = ENG\nAND\tstatus = Open  '}
        ],
    )
    matches = autocomplete.get_matches(TargetState('', 0), autocomplete._candidates, 'shared')
    assert len(matches) == 1
    assert matches[0].value == 'project = ENG AND status = Open'
    async with App().run_test() as pilot:
        await pilot.app.mount(target, autocomplete)
        autocomplete.apply_completion(matches[0].value, TargetState('', 0))
        assert target.value == 'project = ENG AND status = Open'
