import traceback
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Container, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import Static

from gojeera.api_controller.controller import APIControllerResponse
from gojeera.components.edit_work_item_info_screen import EditWorkItemInfoScreen
from gojeera.models import JiraWorkItem
from gojeera.widgets.gojeera_markdown import GojeeraMarkdown

if TYPE_CHECKING:
    from gojeera.app import JiraApp, MainScreen


class WorkItemDescription(GojeeraMarkdown):
    """A widget to display the work item description with custom GojeeraMarkdown styling."""

    DEFAULT_CSS = """
    WorkitemDescriptionWidget {
        border: none;
    }
    """

    def __init__(self):
        super().__init__(id='work_item_description_text')


class WorkItemSummary(Static, can_focus=False):
    """A widget to display the work item summary."""

    DEFAULT_CSS = """
    WorkItemSummary {
        border: none;
        text-style: bold;
        color: $accent;
        padding: 0 2 1 2;
        width: 100%;
        content-align: left middle;
        background: transparent;
    }
    """

    def __init__(self, widget_id: str = 'work_item_description_summary'):
        super().__init__('', id=widget_id, markup=False)
        self.can_focus = False


class WorkItemInfoContainer(Container, can_focus=False):
    """The container for all the widgets that store/show information (description and other text-based fields) of a
    work item."""

    DEFAULT_CSS = """
    WorkItemInfoContainer {
        width: 100%;
        height: 1fr;
        layout: vertical;
    }

    #work-item-info-content {
        width: 100%;
        height: 1fr;
    }

    #work-item-info-description-scroll-container {
        width: 100%;
        height: 1fr;
    }
    """

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)
    clear_information: Reactive[bool] = reactive(False, always_update=True)
    is_loading: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(id='work_item_description_container')
        self._content_ready = False
        self._fields_widget_ready = False

    @property
    def help_anchor(self) -> str:
        return '#work-item-info'

    @property
    def work_item_description_widget(self) -> WorkItemDescription:
        return self.query_one(WorkItemDescription)

    @property
    def header_summary_widget(self) -> WorkItemSummary:
        return self.screen.query_one('#details-work-item-summary', WorkItemSummary)

    @property
    def description_container(self) -> VerticalScroll:
        return self.query_one(
            '#work-item-info-description-scroll-container', expect_type=VerticalScroll
        )

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('#work-item-info-content', expect_type=VerticalGroup)

    def compose(self) -> ComposeResult:
        with VerticalGroup(id='work-item-info-content'):
            with VerticalScroll(id='work-item-info-description-scroll-container', can_focus=True):
                yield WorkItemDescription()
        yield Static(classes='work-item-info-bottom-reserve')

    async def _setup_work_item_description(self, work_item: JiraWorkItem) -> None:
        if work_item.description:
            base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)
            content: str = work_item.get_description(base_url=base_url)
            self.work_item_description_widget.jira_base_url = base_url
            if content:
                await self.work_item_description_widget.update(content)
            else:
                await self.work_item_description_widget.update('Unable to display the description.')
            self.work_item_description_widget.visible = True
            self.description_container.visible = True

            is_required = False
            if work_item_edit_metadata := work_item.get_edit_metadata():
                description_field = work_item_edit_metadata.get('description', {})
                is_required = description_field.get('required', False)

            if is_required:
                self.description_container.add_class('required')
            else:
                self.description_container.remove_class('required')
        else:
            self.description_container.visible = False
            self.work_item_description_widget.visible = False
            await self.work_item_description_widget.update('')

        self._content_ready = True
        self._call_coordinated_loading()

    def watch_work_item(self, work_item: JiraWorkItem | None) -> None:
        self.clear_information = True

        self._content_ready = False
        self._fields_widget_ready = False

        if not work_item:
            return None

        self.show_loading()

        self.header_summary_widget.update(work_item.summary)

        self.run_worker(self._setup_work_item_description(work_item))
        return None

    async def reset_description(self) -> None:
        await self.work_item_description_widget.update('')

    def watch_clear_information(self, clear: bool = False) -> None:
        if clear:
            self.header_summary_widget.update('')
            self.header_summary_widget.display = False

            self.run_worker(self.reset_description())
            self.description_container.visible = False
            self.work_item_description_widget.visible = False

    def show_loading(self) -> None:
        self.is_loading = True

    def hide_loading(self) -> None:
        self.is_loading = False

        self.header_summary_widget.display = self.work_item is not None
        self.header_summary_widget.refresh(layout=True)
        self.description_container.refresh(layout=True)
        self.content_container.refresh(layout=True)

    def watch_is_loading(self, loading: bool) -> None:
        self.content_container.loading = loading

    def signal_fields_widget_ready(self) -> None:
        self._fields_widget_ready = True
        self._call_coordinated_loading()

    def _call_coordinated_loading(self) -> None:
        try:
            main_screen = self.screen

            hide_loading = getattr(main_screen, '_try_hide_loading_coordinated', None)
            if callable(hide_loading):
                hide_loading()
            else:
                self.app.log.error(
                    f'Screen does not have _try_hide_loading_coordinated method. '
                    f'Screen type: {type(main_screen).__name__}'
                )
        except Exception as e:
            self.app.log.error(f'Failed to call coordinated loading: {e}\n{traceback.format_exc()}')

    async def action_edit_work_item_info(self) -> None:
        current_work_item = self.work_item

        if not current_work_item:
            self.notify(
                'No work item is currently loaded. Please select a work item first.',
                severity='warning',
            )
            return

        await self.app.push_screen(
            EditWorkItemInfoScreen(work_item=current_work_item),
            callback=self.handle_edit_work_item_info,
        )

    async def _apply_updated_work_item_info(
        self,
        work_item: JiraWorkItem,
        updates: dict,
        screen: 'MainScreen',
    ) -> None:
        if 'summary' in updates:
            work_item.summary = str(updates.get('summary') or '').strip()

        if 'description' in updates:
            description = updates.get('description')
            work_item.description = description if description else None

        self.header_summary_widget.update(work_item.summary)
        await self._setup_work_item_description(work_item)

        await screen.search_results_list.update_work_item_in_list(work_item)

    async def handle_edit_work_item_info(self, updates: dict | None) -> None:
        if not updates:
            return

        current_work_item = self.work_item
        if not current_work_item:
            self.notify(
                'No work item is currently loaded.',
                severity='error',
            )
            return

        application = cast('JiraApp', self.app)  # noqa: F821
        screen = cast('MainScreen', self.screen)  # noqa: F821

        try:
            response: APIControllerResponse = await application.api.update_work_item(
                work_item=current_work_item,
                updates=updates,
            )

            if response.success:
                self.notify(
                    f'Work item {current_work_item.key} updated successfully',
                )
                await self._apply_updated_work_item_info(current_work_item, updates, screen)
            else:
                application.logger.error(
                    'Failed to update the work item',
                    extra={'error': response.error, 'work_item_key': current_work_item.key},
                )
                self.notify(
                    f'Failed to update the work item: {response.error}',
                    severity='error',
                )
        except Exception as e:
            application.logger.error(
                'Exception while updating work item',
                extra={'error': str(e), 'work_item_key': current_work_item.key},
            )
            self.notify(
                f'An error occurred while updating the work item: {e}',
                severity='error',
            )
