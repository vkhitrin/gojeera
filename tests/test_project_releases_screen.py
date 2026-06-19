from httpx import Response
import pytest
import respx

from gojeera.app import JiraApp
from gojeera.components.screens.project_releases_screen import ProjectReleasesScreen

from .test_helpers import wait_until


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


def build_project_releases_snapshot_test(run_before):
    def test_project_releases_snapshot(
        self, snap_compare, mock_configuration, mock_jira_api_with_project_releases, mock_user_info
    ):
        del self
        assert_project_releases_snapshot(
            snap_compare, mock_configuration, mock_user_info, run_before
        )

    return test_project_releases_snapshot


class TestProjectReleasesScreen:
    test_project_releases_screen_initial_state = build_project_releases_snapshot_test(
        open_project_releases_screen
    )
    test_project_releases_screen_text_filter = build_project_releases_snapshot_test(
        filter_project_releases_screen
    )
    test_project_releases_screen_text_filter_empty = build_project_releases_snapshot_test(
        filter_project_releases_screen_empty
    )
    test_project_releases_screen_status_filter_open = build_project_releases_snapshot_test(
        open_project_releases_status_filter
    )
    test_project_releases_screen_status_filter_all_selected = build_project_releases_snapshot_test(
        select_all_project_release_statuses
    )
