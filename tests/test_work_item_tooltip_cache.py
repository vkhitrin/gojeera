from types import SimpleNamespace
from typing import Any, cast

from gojeera.internal.jira.controller import APIController
from gojeera.widgets.markdown.gojeera_markdown import WorkItemLinkTooltipProvider


def _tooltip_provider(controller: APIController) -> WorkItemLinkTooltipProvider:
    markdown = SimpleNamespace(app=SimpleNamespace(api=controller))
    return WorkItemLinkTooltipProvider(cast(Any, markdown))


def test_work_item_tooltip_cache_is_shared_between_markdown_widgets():
    controller = APIController.__new__(APIController)
    controller.cache_work_item_tooltip('ENG-1', 'Task', 'Shared tooltip', 'Open')

    first_tooltip = _tooltip_provider(controller).get_cached('ENG-1')
    second_tooltip = _tooltip_provider(controller).get_cached('ENG-1')

    assert first_tooltip is not None
    assert second_tooltip is not None
    assert first_tooltip.plain == second_tooltip.plain
    assert 'Shared tooltip' in second_tooltip.plain

    controller.invalidate_work_item_tooltip('ENG-1')

    assert _tooltip_provider(controller).get_cached('ENG-1') is None
