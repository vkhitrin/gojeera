import asyncio

from gojeera.app import JiraApp

from .test_helpers import (
    open_clone_work_item_screen,
    search_for_work_item_key_and_assert_single_result,
)


async def clone_and_search_work_item(pilot):
    screen = await open_clone_work_item_screen(pilot)

    assert screen.summary_input.value == 'CLONE - Update documentation for merge approval process'
    assert not screen.clone_button.disabled

    clone_button = screen.clone_button
    clone_button.press()

    await asyncio.sleep(1.5)

    assert isinstance(pilot.app, JiraApp)

    await search_for_work_item_key_and_assert_single_result(
        pilot,
        work_item_key='ENG-9',
        expected_summary='CLONE - Update documentation for merge approval process',
        mode='jql',
    )


class TestCloneWorkItem:
    """Test work item clone."""

    def test_clone_work_item_and_search(
        self, snap_compare, mock_configuration, mock_jira_api_with_clone_work_item, mock_user_info
    ):
        config = mock_configuration
        app = JiraApp(settings=config, user_info=mock_user_info)

        assert snap_compare(app, terminal_size=(120, 40), run_before=clone_and_search_work_item)
