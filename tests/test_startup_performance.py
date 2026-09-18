import subprocess
import sys
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock

import pytest
from textual.containers import Horizontal
from textual.theme import Theme

from gojeera.app import JiraApp
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.utils.data.fields import FieldMode
from gojeera.utils.ui.widgets_factory_utils import apply_field_control_classes
from gojeera.widgets.inputs.text_input import TextInput
from gojeera.widgets.layout.extended_footer import ExtendedFooter

if TYPE_CHECKING:
    from gojeera.internal.jira.controller import APIController

ACTION_ONLY_SCREEN_MODULES = (
    'gojeera.components.screens.clone_work_item_screen',
    'gojeera.components.screens.comment_screen',
    'gojeera.components.screens.confirmation_screen',
    'gojeera.components.screens.create_work_item_screen',
    'gojeera.components.screens.debug_screen',
    'gojeera.components.screens.decision_picker_screen',
    'gojeera.components.screens.edit_work_item_info_screen',
    'gojeera.components.screens.help_screen',
    'gojeera.components.screens.new_attachment_screen',
    'gojeera.components.screens.new_related_work_item_screen',
    'gojeera.components.screens.panel_picker_screen',
    'gojeera.components.screens.parent_work_item_screen',
    'gojeera.components.screens.project_releases_screen',
    'gojeera.components.screens.project_repositories_screen',
    'gojeera.components.screens.quit_screen',
    'gojeera.components.screens.repository_pull_requests_screen',
    'gojeera.components.screens.save_attachment_screen',
    'gojeera.components.screens.user_mention_picker_screen',
    'gojeera.components.screens.web_link_screen',
    'gojeera.components.screens.work_item_work_log_screen',
    'gojeera.components.screens.work_log_screen',
)

DEFERRED_ADF_MODULES = (
    'atlas_doc_parser.api',
    'gojeera.utils.markdown.adf_helpers',
    'gojeera.widgets.markdown.adf_textarea',
)

DEFERRED_WORK_ITEM_MODULES = (
    'gojeera.components.work_item.work_item_attachments',
    'gojeera.components.work_item.work_item_comments',
    'gojeera.components.work_item.work_item_description',
    'gojeera.components.work_item.work_item_development',
    'gojeera.components.work_item.work_item_fields',
    'gojeera.components.work_item.work_item_history',
    'gojeera.components.work_item.work_item_information',
    'gojeera.components.work_item.work_item_related_work_items',
    'gojeera.components.work_item.work_item_subtasks',
    'gojeera.components.work_item.work_item_web_links',
    'gojeera.widgets.markdown.gojeera_markdown',
    'gojeera.widgets.work_item.work_item_breadcrumb',
)
DEFERRED_SEARCH_MODULES = (
    'gojeera.widgets.search.search_autocomplete',
    'textual_autocomplete',
)
DEFERRED_ATTACHMENT_MODULES = ('magic',)


pytestmark = pytest.mark.usefixtures('mock_jira_api_sync')


def _assert_app_import_defers(module_names: tuple[str, ...]) -> None:
    modules = repr(module_names)
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import sys; import gojeera.app; '
                f'modules = {modules}; '
                'print(",".join(name for name in modules if name in sys.modules))'
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ''


def test_app_import_defers_action_only_screens() -> None:
    _assert_app_import_defers(ACTION_ONLY_SCREEN_MODULES)


def test_app_import_defers_adf_conversion_stack() -> None:
    _assert_app_import_defers(DEFERRED_ADF_MODULES)


def test_app_import_defers_work_item_detail_stack() -> None:
    _assert_app_import_defers(DEFERRED_WORK_ITEM_MODULES)


def test_app_import_defers_search_autocomplete_stack() -> None:
    _assert_app_import_defers(DEFERRED_SEARCH_MODULES)


def test_app_import_defers_attachment_mime_detection() -> None:
    _assert_app_import_defers(DEFERRED_ATTACHMENT_MODULES)


def test_search_bar_preseeds_initial_mode_class() -> None:
    search_bar = UnifiedSearchBar(
        api=cast('APIController', object()),
        classes='custom-search-class',
    )

    assert search_bar.has_class('mode-basic')
    assert search_bar.has_class('custom-search-class')


def test_field_control_classes_are_applied_in_one_batch(monkeypatch) -> None:
    widget = TextInput(mode=FieldMode.UPDATE, field_id='summary')
    add_class = Mock(wraps=widget.add_class)
    monkeypatch.setattr(widget, 'add_class', add_class)

    apply_field_control_classes(widget)

    add_class.assert_called_once_with('field_control', 'field-control-input')
    assert str(widget.styles.width) == '1fr'


def test_footer_preseeds_configured_visibility(mock_configuration) -> None:
    mock_configuration.show_footer = False

    footer = ExtendedFooter(show_command_palette=False)

    assert not footer.display


def _directory_theme_app(monkeypatch, mock_configuration, mock_user_info, theme_name: str):
    custom_theme = Theme(name='directory-custom', primary='#00ff00')
    load_themes = Mock(return_value=[custom_theme])
    monkeypatch.setattr('gojeera.app.load_themes_from_directory', load_themes)
    mock_configuration.theme = theme_name
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
    return app, custom_theme, load_themes


def test_builtin_theme_defers_directory_themes_until_picker_opens(
    monkeypatch,
    mock_configuration,
    mock_user_info,
) -> None:
    app, custom_theme, load_themes = _directory_theme_app(
        monkeypatch, mock_configuration, mock_user_info, 'dracula'
    )

    load_themes.assert_not_called()
    assert not app._directory_themes_registered
    assert app.theme == 'dracula'

    push_screen = Mock()
    monkeypatch.setattr(app, '_push_screen_exclusive_sync', push_screen)
    app.search_themes()
    app.search_themes()

    load_themes.assert_called_once()
    assert app._directory_themes_registered
    assert app.get_theme(custom_theme.name) is custom_theme
    assert push_screen.call_count == 2


def test_configured_directory_theme_loads_before_activation(
    monkeypatch,
    mock_configuration,
    mock_user_info,
) -> None:
    app, custom_theme, load_themes = _directory_theme_app(
        monkeypatch, mock_configuration, mock_user_info, 'directory-custom'
    )

    load_themes.assert_called_once()
    assert app._directory_themes_registered
    assert app.theme == custom_theme.name


def test_preloaded_directory_themes_remain_available_without_directory_io(
    monkeypatch,
    mock_configuration,
    mock_user_info,
) -> None:
    custom_theme = Theme(name='directory-custom', primary='#00ff00')
    load_themes = Mock()
    monkeypatch.setattr('gojeera.app.load_themes_from_directory', load_themes)

    app = JiraApp(
        settings=mock_configuration,
        user_info=mock_user_info,
        directory_themes=[custom_theme],
    )

    load_themes.assert_not_called()
    assert app._directory_themes_registered
    assert app.get_theme(custom_theme.name) is custom_theme


@pytest.mark.asyncio
async def test_app_initial_widget_state_matches_preseeded_startup_state(
    jira_app,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        await pilot.pause()

        search_bar = app.unified_search_bar
        three_split_layout = app.query_one('#three-split-layout', Horizontal)

        assert search_bar.has_class('mode-basic')
        assert search_bar.assignee_selector.disabled
        assert search_bar.type_selector.disabled
        assert search_bar.status_selector.disabled
        assert not search_bar.unified_input.display
        assert search_bar.unified_input.placeholder == ''
        assert search_bar._jql_autocomplete is None
        assert search_bar._search_history_autocomplete is None
        assert three_split_layout.has_class('-search-inactive')
        assert app.tabs.disabled
        assert app._fields_panel is None
        assert app._information_panel is None


@pytest.mark.asyncio
async def test_search_autocomplete_mounts_only_for_the_selected_mode(
    jira_app,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        search_bar = app.unified_search_bar

        search_bar.mode_selector.value = 'text'
        await pilot.pause()

        assert search_bar._search_history_autocomplete is not None
        assert search_bar._search_history_autocomplete.is_mounted
        assert not search_bar._search_history_autocomplete.disabled
        assert search_bar._jql_autocomplete is None

        search_bar.mode_selector.value = 'jql'
        await pilot.pause()

        assert search_bar._jql_autocomplete is not None
        assert search_bar._jql_autocomplete.is_mounted
        assert not search_bar._jql_autocomplete.disabled
        assert search_bar._search_history_autocomplete.disabled


@pytest.mark.asyncio
async def test_work_item_details_mount_completely_before_first_binding(
    jira_app,
) -> None:
    app = jira_app

    async with app.run_test() as pilot:
        await app._ensure_work_item_details_mounted()
        await pilot.pause()

        assert app.information_panel.is_mounted
        assert app.fields_panel.is_mounted
        assert app.query_one('#pane-description')
        assert app.query_one('#pane-attachments')
        assert app.query_one('#pane-subtasks')
        assert app.query_one('#pane-related')
        assert app.query_one('#pane-links')
        assert app.query_one('#pane-comments')
        assert app.query_one('#pane-development')
        assert app.query_one('#pane-history')
        assert app.query_one('#status-field-container')
        assert app.query_one('#dynamic-fields-section')
        assert app.query_one('#due-date-container')

        await app._ensure_work_item_details_mounted()

        assert list(app.details_content_row.children) == [
            app.information_panel,
            app.fields_panel,
        ]


@pytest.mark.asyncio
async def test_cache_pruning_runs_after_app_mount(
    mock_configuration,
    mock_user_info,
    monkeypatch,
) -> None:
    cache = Mock()
    monkeypatch.setattr('gojeera.app.get_cache', lambda: cache)
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

    async with app.run_test() as pilot:
        await pilot.pause()

    cache.prune_expired.assert_called_once_with()
