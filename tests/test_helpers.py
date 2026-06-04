import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

from textual.widgets import Button, Input, TextArea
from textual.widgets._tabbed_content import ContentTabs

from gojeera.app import JiraApp
from gojeera.components.screens.clone_work_item_screen import CloneWorkItemScreen
from gojeera.components.screens.comment_screen import CommentScreen
from gojeera.components.screens.confirmation_screen import ConfirmationScreen
from gojeera.components.screens.new_related_work_item_screen import AddWorkItemRelationshipScreen
from gojeera.components.search.unified_search import UnifiedSearchBar
from gojeera.components.work_item.work_item_related_work_items import RelatedWorkItemsWidget
from gojeera.internal.store.config import ApplicationConfiguration
from gojeera.widgets.markdown.gojeera_markdown import (
    ExtendedMarkdownParagraph,
    get_markdown_link_href,
)
from gojeera.widgets.search.work_item_search_results_scroll import WorkItemSearchResultsScroll
from gojeera.widgets.selection.vim_select import VimSelect


class CommentPickerFlowConfig(NamedTuple):
    action_name: str
    screen_type: type
    options_attr: str
    select_attr: str
    insert_button_selector: str
    cancel_selector: str | None = None
    wait_for_enable: bool = False
    post_insert_focus_save_button: bool = False


async def wait_for_mount(pilot):
    del pilot
    await asyncio.sleep(0.1)


async def wait_for_worker_idle(pilot, *, timeout: float = 3.0) -> None:
    del timeout
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def wait_for_screen_to_settle(pilot, *, timeout: float = 3.0) -> None:
    await wait_for_worker_idle(pilot, timeout=timeout)
    await wait_until(lambda: not getattr(pilot.app, 'is_loading', False), timeout=timeout)
    await wait_until(
        lambda: getattr(pilot.app, '_active_work_item_load_key', None) is None,
        timeout=timeout,
    )


async def choose_select_option(pilot, *, direction: str = 'down', steps: int = 1) -> None:
    await pilot.press('enter')
    await asyncio.sleep(0.2)

    for _ in range(steps):
        await pilot.press(direction)
        await asyncio.sleep(0.2)

    await pilot.press('enter')
    await asyncio.sleep(0.3)


def find_markdown_link_offset(
    paragraph: ExtendedMarkdownParagraph, href_substring: str
) -> tuple[int, int]:
    return next(
        (x, y)
        for y in range(paragraph.size.height)
        for x in range(paragraph.size.width)
        if (
            (href := get_markdown_link_href(paragraph.get_style_at(x, y))) is not None
            and href_substring in href
        )
    )


def find_markdown_paragraph_containing_text(
    query_root: Any, text: str
) -> ExtendedMarkdownParagraph:
    return next(
        paragraph
        for paragraph in query_root.query(ExtendedMarkdownParagraph)
        if text in paragraph.content.plain
    )


async def wait_for_markdown_paragraph_containing_text(
    pilot,
    text: str,
    *,
    timeout: float = 3.0,
    render_delay: float = 0.3,
) -> ExtendedMarkdownParagraph:
    await pilot.app.workers.wait_for_complete()
    await wait_until(
        lambda: bool(list(pilot.app.screen.query(ExtendedMarkdownParagraph))),
        timeout=timeout,
    )
    await asyncio.sleep(render_delay)
    return find_markdown_paragraph_containing_text(pilot.app.screen, text)


def stage_clipboard_upload(monkeypatch, clipboard_module: Any, staged_upload_file: Path) -> None:
    monkeypatch.setattr(
        clipboard_module,
        'stage_clipboard_attachments',
        lambda: [staged_upload_file],
    )


async def search_for_work_item_key_and_assert_single_result(
    pilot,
    *,
    work_item_key: str,
    expected_summary: str,
    mode: str = 'basic',
) -> Any:
    await pilot.press('ctrl+j')
    await wait_until(
        lambda: pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar).display,
        timeout=3.0,
    )

    search_bar = pilot.app.screen.query_one('#unified-search-bar', UnifiedSearchBar)

    if mode == 'jql':
        mode_selector = search_bar.query_one('#search-mode-selector', VimSelect)
        mode_selector.value = 'jql'
        await wait_until(lambda: search_bar.search_mode == 'jql', timeout=3.0)
        assert search_bar.search_mode == 'jql', f'Expected jql mode, got {search_bar.search_mode}'
        search_input = search_bar.query_one('#unified-search-input', Input)
        search_input.value = f'key = {work_item_key}'
    else:
        assert search_bar.search_mode == mode, f'Expected {mode} mode, got {search_bar.search_mode}'
        assert search_bar.set_initial_work_item_key(work_item_key)

    search_button = search_bar.query_one('#unified-search-button', Button)
    await wait_until(lambda: not search_button.disabled, timeout=3.0)
    search_button.press()
    await wait_for_screen_to_settle(pilot)

    search_results_list = pilot.app.screen.query_one(WorkItemSearchResultsScroll)
    await wait_until(
        lambda: (
            search_results_list.work_item_search_results is not None
            and search_results_list.work_item_search_results.work_items is not None
            and len(search_results_list.work_item_search_results.work_items) == 1
            and search_results_list.work_item_search_results.work_items[0].key == work_item_key
        ),
        timeout=3.0,
    )
    assert search_results_list.work_item_search_results is not None, (
        'Search results should be populated'
    )

    search_results = search_results_list.work_item_search_results
    assert search_results.work_items is not None, 'Search results should have work_items'
    assert len(search_results.work_items) == 1, (
        f'Expected 1 work item in results, got {len(search_results.work_items)}'
    )

    work_item = search_results.work_items[0]
    assert work_item.key == work_item_key, (
        f'Expected work item key "{work_item_key}", got "{work_item.key}"'
    )
    assert work_item.summary == expected_summary, (
        f'Expected summary "{expected_summary}", got "{work_item.summary}"'
    )
    return work_item


async def open_first_work_item_from_search(pilot) -> None:
    await wait_for_mount(pilot)

    await pilot.press('ctrl+j')
    await asyncio.sleep(0.5)

    await pilot.press('enter')
    await asyncio.sleep(0.8)

    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.5)


async def open_clone_work_item_screen(
    pilot,
    *,
    work_item_key: str = 'ENG-3',
    original_summary: str = 'Update documentation for merge approval process',
) -> CloneWorkItemScreen:
    # NOTE: (vkhitrin) we directly "enter" the screen without navigating the UI.
    screen = CloneWorkItemScreen(work_item_key=work_item_key, original_summary=original_summary)
    await pilot.app.push_screen(screen)
    await asyncio.sleep(0.3)

    assert isinstance(pilot.app.screen, CloneWorkItemScreen)
    assert pilot.app.screen.work_item_key == work_item_key
    assert pilot.app.screen.original_summary == original_summary
    return screen


async def load_work_item_from_search(pilot, work_item_key: str = 'ENG-1'):
    await asyncio.sleep(0.1)
    screen = assert_main_screen(pilot.app)
    await screen.load_work_item(work_item_key)
    await wait_for_worker_idle(pilot)
    await wait_until(
        lambda: screen.current_loaded_work_item_key == work_item_key,
        timeout=3.0,
    )
    await wait_until(lambda: not screen.is_loading, timeout=3.0)
    await wait_until(lambda: screen._active_work_item_load_key is None, timeout=3.0)


async def focus_work_item_tab(
    pilot,
    *,
    work_item_key: str = 'ENG-3',
    right_presses: int,
    key: str = 'right',
    step_delay: float = 0.2,
    final_delay: float = 0.5,
):
    await load_work_item_from_search(pilot, work_item_key)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await pilot.pause()

    for _ in range(right_presses):
        await pilot.press(key)
        await asyncio.sleep(step_delay)

    await asyncio.sleep(final_delay)


async def prepare_related_work_items_widget(
    pilot,
    *,
    work_item_key: str = 'ENG-3',
    right_presses: int = 3,
) -> RelatedWorkItemsWidget:
    await focus_work_item_tab(pilot, work_item_key=work_item_key, right_presses=right_presses)
    related_widget = pilot.app.screen.query_one(RelatedWorkItemsWidget)
    await wait_for_worker_idle(pilot)
    await pilot.pause()
    return related_widget


async def create_related_work_item_link(
    pilot,
    *,
    related_widget: RelatedWorkItemsWidget,
    linked_key: str = 'ENG-8',
    relationship_value: str = '10000:outward',
) -> None:
    related_widget.focus()
    await pilot.pause()

    await related_widget.action_link_work_item()
    await wait_until(
        lambda: isinstance(pilot.app.screen, AddWorkItemRelationshipScreen),
        timeout=3.0,
    )

    screen = pilot.app.screen
    assert isinstance(screen, AddWorkItemRelationshipScreen), (
        f'Expected AddWorkItemRelationshipScreen, got {type(screen)}'
    )
    await wait_until(lambda: bool(getattr(screen.relationship_type, '_options', [])), timeout=3.0)

    work_item_key_field = screen.linked_work_item_key
    work_item_key_field.focus()
    await pilot.pause()
    work_item_key_field.value = linked_key
    await wait_until(lambda: screen._resolved_work_item is not None, timeout=3.0)

    screen.relationship_type.value = relationship_value
    await wait_until(lambda: screen.relationship_type.value == relationship_value, timeout=3.0)
    await wait_until(lambda: not screen.save_button.disabled, timeout=3.0)

    assert not screen.save_button.disabled, 'Save button should be enabled'
    screen.save_button.press()

    await wait_until(
        lambda: not isinstance(pilot.app.screen, AddWorkItemRelationshipScreen),
        timeout=3.0,
    )
    await wait_for_screen_to_settle(pilot)
    assert not isinstance(pilot.app.screen, AddWorkItemRelationshipScreen), (
        f'Expected to leave AddWorkItemRelationshipScreen, got {type(pilot.app.screen)}'
    )


async def accept_confirmation(pilot, *, wait_before: float = 1.0, wait_after: float = 1.0) -> None:
    await asyncio.sleep(wait_before)
    screen = assert_confirmation_screen(pilot.app.screen)
    screen.query_one('#confirmation-button-accept', Button).press()
    await wait_until(lambda: not isinstance(pilot.app.screen, ConfirmationScreen), timeout=3.0)
    await wait_for_screen_to_settle(pilot)
    await asyncio.sleep(wait_after)


def assert_confirmation_screen(screen) -> ConfirmationScreen:
    assert isinstance(screen, ConfirmationScreen), (
        f'Expected ConfirmationScreen, got {type(screen)}'
    )
    return screen


def assert_main_screen(app) -> JiraApp:
    assert isinstance(app, JiraApp), f'Expected JiraApp, got {type(app)}'
    return app


async def wait_until(predicate, timeout: float = 2.0, interval: float = 0.05):
    """Poll until a predicate becomes true or raise on timeout."""

    deadline = asyncio.get_running_loop().time() + timeout

    while True:
        if predicate():
            return

        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError('Timed out waiting for condition')

        await asyncio.sleep(interval)


async def navigate_to_comments_tab(pilot, work_item_key: str = 'ENG-3') -> None:
    """Navigate to a work item and focus its Comments tab."""

    await load_work_item_from_search(pilot, work_item_key)
    await wait_for_worker_idle(pilot)

    tabs = pilot.app.screen.query_one(ContentTabs)
    tabs.focus()
    await pilot.pause()

    for _ in range(5):
        await pilot.press('right')
        await asyncio.sleep(0.1)

    await wait_for_worker_idle(pilot)
    await pilot.pause()


async def open_add_comment_screen(pilot, work_item_key: str = 'ENG-3') -> CommentScreen:
    """Navigate to Comments and open the add-comment modal."""

    await navigate_to_comments_tab(pilot, work_item_key)
    await pilot.press('ctrl+n')
    await wait_until(lambda: isinstance(pilot.app.screen, CommentScreen), timeout=3.0)
    await wait_for_worker_idle(pilot)

    assert isinstance(pilot.app.screen, CommentScreen)
    assert pilot.app.screen.mode == 'new'

    textarea = pilot.app.screen.query_one(TextArea)
    textarea.focus()
    await wait_until(lambda: textarea.has_focus, timeout=3.0)
    return pilot.app.screen


async def open_picker_from_comment_screen(pilot, *, action_name: str, screen_type: type):
    comment_screen = await open_add_comment_screen(pilot)
    await pilot.app.workers.wait_for_complete()
    await asyncio.sleep(0.2)
    getattr(comment_screen, action_name)()

    # The worker blocks on push_screen_wait until the picker is dismissed.
    await asyncio.sleep(1.0)

    assert isinstance(pilot.app.screen, screen_type), (
        f'Expected {screen_type.__name__}, got {type(pilot.app.screen)}'
    )
    return pilot.app.screen


def create_open_picker_via_comment_flow(
    *,
    action_name: str,
    screen_type: type,
    cancel_selector: str | None = None,
):
    """Create a helper that opens a picker from the add-comment flow."""

    async def open_picker_via_comment_flow(pilot):
        screen = await open_picker_from_comment_screen(
            pilot, action_name=action_name, screen_type=screen_type
        )

        notifications = list(pilot.app._notifications)
        assert len(notifications) == 0, (
            f'Expected no notifications, but found {len(notifications)} notification(s)'
        )
        assert screen.insert_button.disabled, 'Insert button should be disabled initially'

        if cancel_selector is not None:
            screen.set_focus(screen.query_one(cancel_selector))
            await asyncio.sleep(0.1)

    return open_picker_via_comment_flow


def create_open_picker_with_selection(
    *,
    open_picker,
    screen_type: type,
    options_attr: str,
    select_attr: str,
    wait_for_enable: bool = False,
):
    """Create a helper that opens a picker and selects its first option."""

    async def open_picker_with_selection(pilot):
        await open_picker(pilot)

        screen = pilot.app.screen
        assert isinstance(screen, screen_type)

        first_option = getattr(screen, options_attr)[0]
        getattr(screen, select_attr).value = first_option[1]

        if wait_for_enable:
            await wait_until(lambda: not screen.insert_button.disabled)
        else:
            await asyncio.sleep(0.1)

        assert not screen.insert_button.disabled, (
            'Insert button should be enabled after selecting an option'
        )
        assert getattr(screen, select_attr).value == first_option[1], (
            f'Expected selected value to be first option tuple, got {getattr(screen, select_attr).value}'
        )

        screen.set_focus(screen.insert_button)
        await asyncio.sleep(0.1)

    return open_picker_with_selection


def create_insert_picker_and_return_to_comment_screen(
    *,
    config: CommentPickerFlowConfig,
):
    """Create a helper that inserts picker content and returns to CommentScreen."""

    async def insert_picker_and_return_to_comment_screen(pilot):
        picker_screen = await open_picker_from_comment_screen(
            pilot, action_name=config.action_name, screen_type=config.screen_type
        )

        first_option = getattr(picker_screen, config.options_attr)[0]
        getattr(picker_screen, config.select_attr).value = first_option[1]

        if config.wait_for_enable:
            await wait_until(lambda: not picker_screen.insert_button.disabled)
        else:
            await asyncio.sleep(0.2)

        await pilot.click(config.insert_button_selector)
        await asyncio.sleep(0.3)

        await pilot.app.workers.wait_for_complete()
        await asyncio.sleep(0.2)

        assert isinstance(pilot.app.screen, CommentScreen), (
            f'Expected CommentScreen after dismissal, got {type(pilot.app.screen)}'
        )

        if config.post_insert_focus_save_button:
            pilot.app.screen.set_focus(pilot.app.screen.save_button)
            await asyncio.sleep(0.1)

    return insert_picker_and_return_to_comment_screen


def create_comment_picker_flow_helpers(
    *,
    config: CommentPickerFlowConfig,
) -> tuple[Callable[..., Any], Callable[..., Any], Callable[..., Any]]:
    open_picker = create_open_picker_via_comment_flow(
        action_name=config.action_name,
        screen_type=config.screen_type,
        cancel_selector=config.cancel_selector,
    )
    open_picker_with_selection = create_open_picker_with_selection(
        open_picker=open_picker,
        screen_type=config.screen_type,
        options_attr=config.options_attr,
        select_attr=config.select_attr,
        wait_for_enable=config.wait_for_enable,
    )
    insert_and_return = create_insert_picker_and_return_to_comment_screen(
        config=config,
    )
    return open_picker, open_picker_with_selection, insert_and_return


def assert_snapshot_matches(
    snap_compare,
    configuration,
    user_info,
    run_before,
    terminal_size: tuple[int, int] = (120, 40),
    configure_configuration: Callable[[ApplicationConfiguration], None] | None = None,
    configure_app: Callable[[JiraApp], None] | None = None,
) -> None:
    if configure_configuration is not None:
        configure_configuration(configuration)

    app = JiraApp(settings=configuration, user_info=user_info)
    if configure_app is not None:
        configure_app(app)

    assert snap_compare(app, terminal_size=terminal_size, run_before=run_before)


def with_snapshot_assertion(
    run_before,
    *,
    terminal_size: tuple[int, int] = (120, 40),
    configure_configuration: Callable[[ApplicationConfiguration], None] | None = None,
    configure_app: Callable[[JiraApp], None] | None = None,
):
    return with_snapshot_assertion_fixture(
        run_before,
        fixture_name='mock_jira_api_with_search_results',
        terminal_size=terminal_size,
        configure_configuration=configure_configuration,
        configure_app=configure_app,
    )


def with_snapshot_assertion_fixture(
    run_before,
    *,
    fixture_name: str,
    terminal_size: tuple[int, int] = (120, 40),
    configure_configuration: Callable[[ApplicationConfiguration], None] | None = None,
    configure_app: Callable[[JiraApp], None] | None = None,
):
    def decorator(_):
        def wrapper(self, request, snap_compare, mock_configuration, mock_user_info):
            del self
            request.getfixturevalue(fixture_name)
            assert_snapshot_matches(
                snap_compare,
                mock_configuration,
                mock_user_info,
                run_before,
                terminal_size=terminal_size,
                configure_configuration=configure_configuration,
                configure_app=configure_app,
            )

        return wrapper

    return decorator
