from unittest.mock import Mock

import pytest
from textual.widget import Widget

from gojeera.internal.models.jira import JiraProjectRepository, WorkItemStatus
from gojeera.internal.models.work_items import JiraWorkItem

pytestmark = pytest.mark.usefixtures('mock_jira_api_sync')


@pytest.mark.asyncio
async def test_deferred_action_screen_css_is_applied_when_mounted(
    jira_app,
    monkeypatch,
) -> None:
    app = jira_app

    async with app.run_test(size=(120, 40)) as pilot:
        from gojeera.components.screens.comment_screen import CommentScreen
        from gojeera.components.screens.confirmation_screen import ConfirmationScreen
        from gojeera.components.screens.edit_work_item_info_screen import EditWorkItemInfoScreen
        from gojeera.components.screens.new_attachment_screen import AddAttachmentScreen
        from gojeera.components.screens.web_link_screen import RemoteLinkScreen
        from gojeera.components.screens.work_log_screen import LogWorkScreen

        screens = (
            (CommentScreen(), '60w', '100'),
            (RemoteLinkScreen(work_item_key='ENG-1'), '50w', '70'),
            (EditWorkItemInfoScreen(), '74w', '110'),
            (ConfirmationScreen('Continue?'), '50w', '60'),
            (LogWorkScreen(work_item_key='ENG-1'), '56w', '96'),
            (AddAttachmentScreen(work_item_key='ENG-1'), '50w', '70'),
        )
        reparse = Mock(wraps=app.stylesheet.reparse)
        monkeypatch.setattr(app.stylesheet, 'reparse', reparse)

        for screen, expected_width, expected_max_width in screens:
            assert not type(screen).__dict__.get('CSS')
            await app.push_screen(screen)
            await pilot.pause()

            modal_outer = screen.query_one('#modal_outer', Widget)
            assert str(modal_outer.styles.width) == expected_width
            assert str(modal_outer.styles.max_width) == expected_max_width

            screen.dismiss()
            await pilot.pause()

        reparse.assert_called_once_with()


@pytest.mark.asyncio
async def test_second_wave_deferred_screen_css_is_applied_when_mounted(
    jira_app,
    monkeypatch,
) -> None:
    app = jira_app
    async with app.run_test(size=(160, 50)) as pilot:
        from gojeera.components.screens.clone_work_item_screen import CloneWorkItemScreen
        from gojeera.components.screens.create_work_item_screen import AddWorkItemScreen
        from gojeera.components.screens.debug_screen import DebugInfoScreen
        from gojeera.components.screens.decision_picker_screen import DecisionPickerScreen
        from gojeera.components.screens.help_screen import HelpScreen
        from gojeera.components.screens.new_related_work_item_screen import (
            AddWorkItemRelationshipScreen,
        )
        from gojeera.components.screens.panel_picker_screen import PanelPickerScreen
        from gojeera.components.screens.parent_work_item_screen import ParentWorkItemScreen
        from gojeera.components.screens.project_releases_screen import ProjectReleasesScreen
        from gojeera.components.screens.project_repositories_screen import (
            ProjectRepositoriesScreen,
        )
        from gojeera.components.screens.quit_screen import QuitScreen
        from gojeera.components.screens.repository_pull_requests_screen import (
            RepositoryPullRequestsScreen,
        )
        from gojeera.components.screens.save_attachment_screen import SaveAttachmentScreen
        from gojeera.components.screens.user_mention_picker_screen import UserMentionPickerScreen
        from gojeera.components.screens.work_item_template_screen import (
            WorkItemTemplatePickerScreen,
        )
        from gojeera.components.screens.work_item_work_log_screen import WorkItemWorkLogScreen

        work_item = JiraWorkItem(
            id='1',
            key='ENG-1',
            summary='Test work item',
            status=WorkItemStatus(id='1', name='To Do'),
        )
        repository = JiraProjectRepository(id='1', name='platform-api')
        screens = (
            (HelpScreen(), '90w', '120', 44),
            (QuitScreen(), '34', '34', None),
            (AddWorkItemRelationshipScreen('ENG-1'), '50w', '70', None),
            (ParentWorkItemScreen(work_item), '45w', '64', None),
            (AddWorkItemScreen(), '72w', '120', None),
            (CloneWorkItemScreen('ENG-1', 'Test work item'), '50w', '70', None),
            (SaveAttachmentScreen('artifact.txt'), '50w', '70', None),
            (UserMentionPickerScreen('https://example.atlassian.net'), '42w', '60', None),
            (DecisionPickerScreen(), '42w', '60', None),
            (PanelPickerScreen(), '42w', '60', None),
            (DebugInfoScreen(), '90w', '120', 40),
            (ProjectReleasesScreen('ENG'), '90w', '140', 36),
            (ProjectRepositoriesScreen('ENG'), '90w', '140', 36),
            (RepositoryPullRequestsScreen('ENG', repository), '90w', '150', 36),
            (WorkItemWorkLogScreen('ENG-1'), '68w', '96', None),
            (WorkItemTemplatePickerScreen(), '80', 'None', None),
        )

        for screen, _, _, _ in screens:
            monkeypatch.setattr(type(screen), 'on_mount', lambda self: None, raising=False)

        reparse = Mock(wraps=app.stylesheet.reparse)
        monkeypatch.setattr(app.stylesheet, 'reparse', reparse)
        for screen, expected_width, expected_max_width, expected_region_height in screens:
            assert not type(screen).__dict__.get('CSS')
            await app.push_screen(screen)
            await pilot.pause()
            if isinstance(screen, RepositoryPullRequestsScreen):
                screen.pull_requests_scroll.loading = True
                await pilot.pause()

            modal_outer = screen.query_one('#modal_outer', Widget)
            assert str(modal_outer.styles.width) == expected_width
            assert str(modal_outer.styles.max_width) == expected_max_width
            if expected_region_height is not None:
                assert modal_outer.region.height == expected_region_height
            if isinstance(screen, RepositoryPullRequestsScreen):
                assert modal_outer.region.width == 144

            screen.dismiss()
            await pilot.pause()

        reparse.assert_called_once_with()
