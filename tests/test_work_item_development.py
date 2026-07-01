from typing import Any, cast

from gojeera.app import JiraApp
from gojeera.components.work_item.work_item_development import WorkItemDevelopmentWidget
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import JiraRepositoryPullRequest

from .test_helpers import assert_snapshot_matches, focus_work_item_tab, wait_until


async def open_work_item_development(pilot):
    await focus_work_item_tab(pilot, work_item_key='ENG-3', right_presses=6)

    pilot.app.tabs.active = 'tab-development'
    development_widget = pilot.app.screen.query_one(WorkItemDevelopmentWidget)
    development_widget.load_if_needed()

    await wait_until(lambda: development_widget.displayed_count == 2, timeout=3.0)
    assert development_widget.pull_requests is not None
    assert len(development_widget.pull_requests) == 2
    await pilot.pause()


def build_configure_development_api(
    pull_requests_payload: list[dict[str, Any]],
):
    pull_requests = [
        JiraRepositoryPullRequest(**pull_request) for pull_request in pull_requests_payload
    ]

    def configure_app(app: JiraApp) -> None:
        async def get_work_item_development_pull_requests(
            work_item_key: str,
            work_item_id: str | None = None,
            project_key: str | None = None,
        ) -> APIControllerResponse:
            assert work_item_key == 'ENG-3'
            assert work_item_id == '94266'
            assert project_key == 'ENG'
            return APIControllerResponse(result=pull_requests)

        cast(
            Any, app.api
        ).get_work_item_development_pull_requests = get_work_item_development_pull_requests

    return configure_app


class TestWorkItemDevelopment:
    def test_work_item_development_initial_state(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_with_search_results,
        mock_user_info,
        mock_jira_repository_pull_requests_payload,
    ):
        del self, mock_jira_api_with_search_results
        assert_snapshot_matches(
            snap_compare,
            mock_configuration,
            mock_user_info,
            open_work_item_development,
            configure_app=build_configure_development_api(
                mock_jira_repository_pull_requests_payload
            ),
        )
