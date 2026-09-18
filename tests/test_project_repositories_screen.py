import asyncio
from typing import cast
from unittest.mock import Mock

import pytest

from gojeera.app import JiraApp
from gojeera.components.screens.project_repositories_screen import ProjectRepositoriesScreen
from gojeera.components.screens.repository_pull_requests_screen import RepositoryPullRequestsScreen
from gojeera.internal.jira.controller import (
    API_TOKEN_FALLBACK_REQUIRED_ERROR,
    APIController,
    APIControllerResponse,
)
from gojeera.internal.models.jira import (
    JiraProjectRepository,
    JiraRepositoryPullRequest,
    JiraServerInfo,
)

from .test_helpers import jira_global_settings, wait_until


class FakeProjectRepositoriesAPI:
    def __init__(
        self,
        repositories: list[JiraProjectRepository] | None = None,
        pull_requests: list[JiraRepositoryPullRequest] | None = None,
    ) -> None:
        self.repositories = repositories
        self.pull_requests = pull_requests

    async def server_info(self) -> APIControllerResponse:
        return APIControllerResponse(
            result=JiraServerInfo(
                base_url='https://example.atlassian.acme.net',
                version='1001.0.0',
                build_number=1001,
                build_date='2026-06-24T00:00:00.000+0000',
                server_title='Example Jira',
                deployment_type='Cloud',
            )
        )

    async def global_settings(self) -> APIControllerResponse:
        return APIControllerResponse(result=jira_global_settings())

    async def get_project_repositories(
        self,
        project_key: str,
        on_page=None,
    ) -> APIControllerResponse:
        assert project_key == 'ENG'
        if self.repositories is not None:
            if on_page is not None:
                on_page(self.repositories)
            return APIControllerResponse(result=self.repositories)

        return APIControllerResponse(
            success=False,
            error=API_TOKEN_FALLBACK_REQUIRED_ERROR,
        )

    async def get_repository_pull_requests(
        self,
        requested_project_key: str,
        selected_repository: JiraProjectRepository,
        on_page=None,
    ) -> APIControllerResponse:
        assert requested_project_key == 'ENG'
        assert selected_repository.name == 'platform-api'
        pull_requests = self.pull_requests or []
        if on_page is not None:
            await on_page(pull_requests)
        return APIControllerResponse(result=pull_requests)

    async def close(self) -> None:
        pass


async def open_project_repositories_oauth2_notification(pilot):
    await pilot.app.push_screen(ProjectRepositoriesScreen('ENG'))
    await wait_until(lambda: isinstance(pilot.app.screen, ProjectRepositoriesScreen), timeout=3.0)
    await wait_until(lambda: pilot.app._notifications, timeout=3.0)
    await pilot.pause()


async def open_project_repositories_screen(pilot):
    await pilot.app.push_screen(ProjectRepositoriesScreen('ENG'))
    await wait_until(lambda: isinstance(pilot.app.screen, ProjectRepositoriesScreen), timeout=3.0)
    await wait_until(lambda: len(pilot.app.screen._rendered_repositories) == 2, timeout=3.0)
    await pilot.pause()


async def filter_project_repositories_screen(pilot):
    await open_project_repositories_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectRepositoriesScreen)

    screen.text_filter.focus()
    screen.text_filter.value = 'gitlab'

    await wait_until(
        lambda: (
            len(screen._rendered_repositories) == 1
            and screen._rendered_repositories[0].name == 'platform-api'
        ),
        timeout=3.0,
    )
    await pilot.pause()


async def open_repository_pull_requests_screen(pilot):
    await open_project_repositories_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectRepositoriesScreen)

    await screen.action_view_repository_pull_requests()
    await wait_until(
        lambda: isinstance(pilot.app.screen, RepositoryPullRequestsScreen),
        timeout=3.0,
    )
    await wait_until(
        lambda: len(pilot.app.screen._rendered_pull_requests) == 2,
        timeout=3.0,
    )
    await pilot.pause()


def assert_project_repositories_snapshot(
    snap_compare,
    mock_configuration,
    mock_user_info,
    run_before,
    repositories: list[JiraProjectRepository] | None = None,
    pull_requests: list[JiraRepositoryPullRequest] | None = None,
):
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
    app.api = cast(APIController, FakeProjectRepositoriesAPI(repositories, pull_requests))

    assert snap_compare(
        app,
        terminal_size=(120, 40),
        run_before=run_before,
    )


def build_project_repositories(
    repositories_payload: list[dict],
) -> list[JiraProjectRepository]:
    return [JiraProjectRepository(**repository) for repository in repositories_payload]


def build_repository_pull_requests(
    pull_requests_payload: list[dict],
) -> list[JiraRepositoryPullRequest]:
    return [JiraRepositoryPullRequest(**pull_request) for pull_request in pull_requests_payload]


def assert_project_repositories_payload_snapshot(
    snap_compare,
    mock_configuration,
    mock_user_info,
    run_before,
    repositories_payload: list[dict],
    pull_requests_payload: list[dict] | None = None,
) -> None:
    assert_project_repositories_snapshot(
        snap_compare,
        mock_configuration,
        mock_user_info,
        run_before,
        repositories=build_project_repositories(repositories_payload),
        pull_requests=(
            build_repository_pull_requests(pull_requests_payload)
            if pull_requests_payload is not None
            else None
        ),
    )


class TestProjectRepositoriesScreen:
    @pytest.mark.asyncio
    async def test_repositories_render_the_first_page_while_later_pages_load(
        self,
        mock_configuration,
        mock_user_info,
    ):
        first_repository = JiraProjectRepository(id='repo-1', name='platform-api')
        second_repository = JiraProjectRepository(id='repo-2', name='platform-web')
        first_page_published = asyncio.Event()
        release_second_page = asyncio.Event()

        class StreamingProjectRepositoriesAPI(FakeProjectRepositoriesAPI):
            async def get_project_repositories(self, project_key: str, on_page=None):
                assert project_key == 'ENG'
                assert on_page is not None
                on_page([first_repository])
                first_page_published.set()
                await release_second_page.wait()
                on_page([first_repository, second_repository])
                return APIControllerResponse(result=[first_repository, second_repository])

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app.api = cast(APIController, StreamingProjectRepositoriesAPI())

        async with app.run_test():
            await app.push_screen(ProjectRepositoriesScreen('ENG'))
            await asyncio.wait_for(first_page_published.wait(), timeout=1)
            screen = app.screen
            assert isinstance(screen, ProjectRepositoriesScreen)
            await wait_until(lambda: len(screen._rendered_repositories) == 1, timeout=3.0)

            assert screen._rendered_repositories[0] is first_repository
            assert not screen.repositories_scroll.loading
            assert screen.loading_label.display
            replace_rows = Mock(wraps=screen.table.replace_rows)
            screen.table.replace_rows = replace_rows

            release_second_page.set()
            await wait_until(lambda: len(screen._rendered_repositories) == 2, timeout=3.0)
            await wait_until(lambda: not screen.loading_label.display, timeout=3.0)
            replace_rows.assert_not_called()

    @pytest.mark.asyncio
    async def test_pull_requests_render_the_first_page_while_later_pages_load(
        self,
        mock_configuration,
        mock_user_info,
    ):
        repository = JiraProjectRepository(id='repo-1', name='platform-api')
        first_page = JiraRepositoryPullRequest(
            id='pr-1',
            title='First pull request',
            work_item_key='ENG-1',
            work_item_id='1',
        )
        second_page = JiraRepositoryPullRequest(
            id='pr-2',
            title='Second pull request',
            work_item_key='ENG-2',
            work_item_id='2',
        )
        first_page_published = asyncio.Event()
        release_second_page = asyncio.Event()

        class StreamingProjectRepositoriesAPI(FakeProjectRepositoriesAPI):
            async def get_repository_pull_requests(self, *args, **kwargs) -> APIControllerResponse:
                requested_project_key, selected_repository = args
                on_page = kwargs.get('on_page')
                assert requested_project_key == 'ENG'
                assert selected_repository is repository
                assert on_page is not None
                await on_page([first_page])
                first_page_published.set()
                await release_second_page.wait()
                await on_page([second_page])
                return APIControllerResponse(result=[first_page, second_page])

        fake_api = StreamingProjectRepositoriesAPI()
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app.api = cast(APIController, fake_api)

        async with app.run_test() as pilot:
            screen = RepositoryPullRequestsScreen('ENG', repository)
            await app.push_screen(screen)
            await asyncio.wait_for(first_page_published.wait(), timeout=3.0)
            await wait_until(lambda: screen.table.row_count == 1, timeout=3.0)

            assert not screen.pull_requests_scroll.loading
            assert screen.loading_label.display

            release_second_page.set()
            await wait_until(lambda: screen.table.row_count == 2, timeout=3.0)
            await wait_until(lambda: not screen.loading_label.display, timeout=3.0)
            await pilot.pause()

            assert [item.id for item in screen._rendered_pull_requests] == ['pr-1', 'pr-2']

    @staticmethod
    def test_project_repositories_screen_oauth2_missing_fallback_notification(
        snap_compare,
        mock_configuration,
        mock_user_info,
    ):
        assert_project_repositories_snapshot(
            snap_compare,
            mock_configuration,
            mock_user_info,
            open_project_repositories_oauth2_notification,
        )

    @pytest.mark.parametrize(
        'run_before',
        [
            open_project_repositories_screen,
            filter_project_repositories_screen,
        ],
        ids=[
            'initial-state-with-api-token-fallback',
            'text-filter',
        ],
    )
    @staticmethod
    def test_project_repositories_screen_repository_states(
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_graphql_project_repositories_payload,
        run_before,
    ):
        assert_project_repositories_payload_snapshot(
            snap_compare,
            mock_configuration,
            mock_user_info,
            run_before,
            mock_jira_graphql_project_repositories_payload,
        )

    @staticmethod
    def test_project_repositories_screen_opens_repository_pull_requests(
        snap_compare,
        mock_configuration,
        mock_user_info,
        mock_jira_graphql_project_repositories_payload,
        mock_jira_repository_pull_requests_payload,
    ):
        assert_project_repositories_payload_snapshot(
            snap_compare,
            mock_configuration,
            mock_user_info,
            open_repository_pull_requests_screen,
            mock_jira_graphql_project_repositories_payload,
            mock_jira_repository_pull_requests_payload,
        )
