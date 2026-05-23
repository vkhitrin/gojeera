import asyncio

from gojeera.app import JiraApp
from gojeera.internal.store.cache import get_cache
from gojeera.widgets.navigation.extended_palette import ExtendedPalette

from .conftest import get_issue_by_key
from .test_helpers import wait_for_mount


async def open_empty_recently_viewed_work_items_palette(pilot):
    await wait_for_mount(pilot)

    pilot.app.action_show_recently_viewed_work_items_palette()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, ExtendedPalette)


def seed_recently_viewed_work_item(cache, issue: dict) -> None:
    fields = issue.get('fields', {})
    work_item_type = fields.get('issuetype') or {}
    cache.add_recently_viewed_work_item(
        issue['key'],
        fields.get('summary'),
        work_item_type.get('name'),
    )


async def open_recently_viewed_work_items_palette(pilot):
    await wait_for_mount(pilot)

    pilot.app.action_show_recently_viewed_work_items_palette()
    await asyncio.sleep(0.5)

    assert isinstance(pilot.app.screen, ExtendedPalette)


class TestRecentlyViewedWorkItemsProvider:
    def test_recently_viewed_work_items_palette_empty(
        self,
        snap_compare,
        mock_configuration,
        mock_jira_api_sync,
        mock_user_info,
    ):
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_empty_recently_viewed_work_items_palette,
        )

    def test_recently_viewed_work_items_palette_with_items(
        self,
        monkeypatch,
        snap_compare,
        mock_configuration,
        mock_jira_api_sync,
        mock_user_info,
        mock_jira_search_with_results,
    ):
        cache = get_cache()
        seed_recently_viewed_work_item(
            cache,
            get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-1'),
        )
        seed_recently_viewed_work_item(
            cache,
            get_issue_by_key(mock_jira_search_with_results['issues'], 'ENG-2'),
        )

        monkeypatch.setattr(
            'gojeera.commands.providers.recently_viewed_work_items_provider.humanize.naturaltime',
            lambda _: '5 minutes ago',
        )
        app = JiraApp(settings=mock_configuration, user_info=mock_user_info)

        assert snap_compare(
            app,
            terminal_size=(120, 40),
            run_before=open_recently_viewed_work_items_palette,
        )
