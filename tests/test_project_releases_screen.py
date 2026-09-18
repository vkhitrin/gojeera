import asyncio
from typing import cast

from httpx import Response
import pytest
import respx

from gojeera.app import JiraApp
from gojeera.components.screens.project_releases_screen import ProjectReleasesScreen
from gojeera.internal.jira.controller import APIController, APIControllerResponse
from gojeera.internal.models.jira import (
    JiraProjectRelease,
    JiraServerInfo,
)

from .test_helpers import jira_global_settings, wait_until


@pytest.fixture
async def mock_jira_api_with_project_releases(
    mock_jira_api_sync,
    mock_jira_software_project_releases,
):
    def project_versions_handler(request):
        statuses = set(str(request.url.params.get('status', '')).split(','))
        releases = mock_jira_software_project_releases['values']

        if statuses and statuses != {''}:
            releases = [
                release
                for release in releases
                if (
                    ('archived' in statuses and release.get('archived'))
                    or (
                        'released' in statuses
                        and release.get('released')
                        and not release.get('archived')
                    )
                    or (
                        'unreleased' in statuses
                        and not release.get('released')
                        and not release.get('archived')
                    )
                )
            ]

        return Response(
            200,
            json={
                **mock_jira_software_project_releases,
                'total': len(releases),
                'values': releases,
            },
        )

    respx.get('https://example.atlassian.acme.net/rest/api/3/project/ENG/version').mock(
        side_effect=project_versions_handler
    )
    yield


async def open_project_releases_screen(pilot):
    await pilot.app.push_screen(ProjectReleasesScreen('ENG'))
    await wait_until(lambda: isinstance(pilot.app.screen, ProjectReleasesScreen), timeout=3.0)
    await wait_until(lambda: len(pilot.app.screen._rendered_releases) > 0, timeout=3.0)
    await pilot.pause()


async def filter_project_releases_screen(pilot):
    await open_project_releases_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectReleasesScreen)

    screen.text_filter.focus()
    screen.text_filter.value = 'backlog'

    await wait_until(
        lambda: (
            len(screen._rendered_releases) == 1
            and screen._rendered_releases[0].name == 'Platform 5.26 Backlog'
        ),
        timeout=3.0,
    )
    await pilot.pause()


async def filter_project_releases_screen_empty(pilot):
    await open_project_releases_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectReleasesScreen)

    screen.text_filter.focus()
    screen.text_filter.value = 'not-a-release'

    await wait_until(lambda: len(screen._rendered_releases) == 0, timeout=3.0)
    await pilot.pause()


async def open_project_releases_status_filter(pilot):
    await open_project_releases_screen(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectReleasesScreen)

    screen.status_filter_button.press()

    await wait_until(lambda: screen.status_filter.display, timeout=3.0)
    await wait_until(lambda: screen.status_filter.has_focus, timeout=3.0)
    await pilot.pause()


async def select_all_project_release_statuses(pilot):
    await open_project_releases_status_filter(pilot)

    screen = pilot.app.screen
    assert isinstance(screen, ProjectReleasesScreen)

    screen.status_filter.select_all()
    screen._start_releases_load()

    await wait_until(
        lambda: set(screen.status_filter.selected) == {'released', 'unreleased', 'archived'},
        timeout=3.0,
    )
    await wait_until(lambda: len(screen._rendered_releases) == 5, timeout=3.0)

    screen.status_filter_button.press()
    await wait_until(lambda: screen.status_filter.display, timeout=3.0)
    await wait_until(lambda: screen.status_filter.has_focus, timeout=3.0)
    await pilot.pause()


def assert_project_releases_snapshot(snap_compare, mock_configuration, mock_user_info, run_before):
    app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

    assert snap_compare(
        app,
        terminal_size=(120, 40),
        run_before=run_before,
    )


class TestProjectReleasesScreen:
    @pytest.mark.asyncio
    async def test_releases_render_the_first_page_while_later_pages_load(
        self,
        mock_configuration,
        mock_user_info,
    ):
        first_release = JiraProjectRelease(
            id='release-1',
            name='First release',
            release_date='2026-08-01',
        )
        second_release = JiraProjectRelease(
            id='release-2',
            name='Second release',
            release_date='2026-08-08',
        )
        first_page_published = asyncio.Event()
        release_second_page = asyncio.Event()

        class StreamingProjectReleasesAPI:
            async def server_info(self) -> APIControllerResponse:
                server_info = JiraServerInfo(
                    base_url='https://example.atlassian.acme.net',
                    version='1001.0.0',
                    build_number=1001,
                    build_date='2026-06-24T00:00:00.000+0000',
                    server_title='Example Jira',
                )
                return APIControllerResponse(result=server_info)

            async def global_settings(self) -> APIControllerResponse:
                return APIControllerResponse(result=jira_global_settings())

            async def get_project_releases(
                self,
                project_key: str,
                *,
                status=None,
                order_by=None,
                on_page=None,
            ) -> APIControllerResponse:
                assert project_key == 'ENG'
                assert status == 'unreleased'
                assert order_by == 'releaseDate'
                assert on_page is not None
                on_page([first_release])
                first_page_published.set()
                await release_second_page.wait()
                on_page([first_release, second_release])
                return APIControllerResponse(result=[first_release, second_release])

            async def close(self) -> None:
                pass

        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)
        app.api = cast(APIController, StreamingProjectReleasesAPI())

        async with app.run_test():
            await app.push_screen(ProjectReleasesScreen('ENG'))
            await asyncio.wait_for(first_page_published.wait(), timeout=1)
            screen = app.screen
            assert isinstance(screen, ProjectReleasesScreen)
            await wait_until(lambda: len(screen._rendered_releases) == 1, timeout=3.0)

            assert screen._rendered_releases[0] is first_release
            assert not screen.releases_scroll.loading
            assert screen.loading_label.display

            release_second_page.set()
            await wait_until(lambda: len(screen._rendered_releases) == 2, timeout=3.0)
            await wait_until(lambda: not screen.loading_label.display, timeout=3.0)
            assert [release.id for release in screen._rendered_releases] == [
                'release-2',
                'release-1',
            ]

    def test_project_releases_screen_initial_state(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self, mock_jira_api_with_project_releases
        assert_project_releases_snapshot(
            snap_compare, mock_configuration, mock_user_info, open_project_releases_screen
        )

    def test_project_releases_screen_text_filter(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self, mock_jira_api_with_project_releases
        assert_project_releases_snapshot(
            snap_compare, mock_configuration, mock_user_info, filter_project_releases_screen
        )

    def test_project_releases_screen_text_filter_empty(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self, mock_jira_api_with_project_releases
        assert_project_releases_snapshot(
            snap_compare, mock_configuration, mock_user_info, filter_project_releases_screen_empty
        )

    def test_project_releases_screen_status_filter_open(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self, mock_jira_api_with_project_releases
        assert_project_releases_snapshot(
            snap_compare, mock_configuration, mock_user_info, open_project_releases_status_filter
        )

    def test_project_releases_screen_status_filter_all_selected(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self, mock_jira_api_with_project_releases
        assert_project_releases_snapshot(
            snap_compare,
            mock_configuration,
            mock_user_info,
            select_all_project_release_statuses,
        )
