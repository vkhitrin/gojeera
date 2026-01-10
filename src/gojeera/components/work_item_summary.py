import traceback
from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Center, Container, Vertical, VerticalGroup, VerticalScroll
from textual.reactive import Reactive, reactive
from textual.widgets import LoadingIndicator, Static

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
        padding: 1 2;
        width: 100%;
        content-align: left middle;
        background: $background-lighten-1;
    }
    """

    def __init__(self):
        super().__init__('', id='work_item_summary', markup=False)
        self.can_focus = False


class WorkItemSummaryContainer(Container, can_focus=False):
    """The container that holds the read-only summary of the work item."""

    def __init__(self):
        super().__init__()
        self.visible = False
        self.can_focus = False


class WorkItemInfoContainer(Vertical, can_focus=False):
    """The container for all the widgets that store/show information (description and other text-based fields) of a
    work item."""

    work_item: Reactive[JiraWorkItem | None] = reactive(None, always_update=True)
    clear_information: Reactive[bool] = reactive(False, always_update=True)

    def __init__(self):
        super().__init__(id='work_item_summary_container')
        self._content_ready = False
        self._fields_widget_ready = False

    @property
    def help_anchor(self) -> str:
        return '#work-item-info'

    @property
    def work_item_summary_widget(self) -> WorkItemSummary:
        return self.query_one(WorkItemSummary)

    @property
    def work_item_description_widget(self) -> WorkItemDescription:
        return self.query_one(WorkItemDescription)

    @property
    def summary_container_widget(self) -> WorkItemSummaryContainer:
        return self.query_one(WorkItemSummaryContainer)

    @property
    def description_container(self) -> VerticalScroll:
        return self.query_one(
            '#work-item-info-description-scroll-container', expect_type=VerticalScroll
        )

    @property
    def loading_container(self) -> Center:
        return self.query_one('#work-item-info-loading-container', expect_type=Center)

    @property
    def content_container(self) -> VerticalGroup:
        return self.query_one('#work-item-info-content', expect_type=VerticalGroup)

    def compose(self) -> ComposeResult:
        with Center(id='work-item-info-loading-container') as loading_container:
            loading_container.display = False
            yield LoadingIndicator()
        with VerticalGroup(id='work-item-info-content'):
            with WorkItemSummaryContainer():
                yield WorkItemSummary()
            with VerticalScroll(id='work-item-info-description-scroll-container', can_focus=True):
                yield WorkItemDescription()

    async def _setup_work_item_description(self, work_item: JiraWorkItem) -> None:
        if work_item.description:
            base_url = getattr(getattr(self.app, 'server_info', None), 'base_url', None)
            content: str = work_item.get_description(base_url=base_url)
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

        self.work_item_summary_widget.update(work_item.summary)

        self.run_worker(self._setup_work_item_description(work_item))
        return None

    async def reset_description(self) -> None:
        await self.work_item_description_widget.update('')

    def watch_clear_information(self, clear: bool = False) -> None:
        if clear:
            self.work_item_summary_widget.update('')
            self.work_item_summary_widget.visible = False
            self.summary_container_widget.visible = False

            self.run_worker(self.reset_description())
            self.description_container.visible = False
            self.work_item_description_widget.visible = False

    def show_loading(self) -> None:
        self.loading_container.display = True
        self.content_container.display = False

    def hide_loading(self) -> None:
        self.loading_container.display = False
        self.content_container.display = True

        self.work_item_summary_widget.visible = True
        self.summary_container_widget.visible = True

    def signal_fields_widget_ready(self) -> None:
        self._fields_widget_ready = True
        self._call_coordinated_loading()

    def _call_coordinated_loading(self) -> None:
        try:
            main_screen = self.screen

            if hasattr(main_screen, '_try_hide_loading_coordinated'):
                main_screen._try_hide_loading_coordinated()  # type: ignore[call-non-callable]
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

                screen.current_loaded_work_item_key = None
                self.run_worker(screen.fetch_work_items(current_work_item.key), exclusive=True)
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
