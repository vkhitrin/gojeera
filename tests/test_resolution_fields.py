from unittest.mock import AsyncMock

import pytest

from gojeera.components.work_item.work_item_fields import WorkItemFields
from gojeera.internal.models.jira import WorkItemStatus
from gojeera.internal.models.work_items import JiraWorkItem
from gojeera.widgets.inputs.read_only_input_field import ReadOnlyInputField
from gojeera.widgets.selection.selection import SelectionWidget


@pytest.mark.asyncio
@pytest.mark.parametrize('resolution', ["Won't Do", 'Done', None])
async def test_resolution_uses_only_its_static_field_with_additional_fields_enabled(
    jira_app,
    monkeypatch,
    resolution,
):
    jira_app.config.enable_updating_additional_fields = True
    work_item = JiraWorkItem(
        id='1',
        key='ENG-1',
        summary='Resolved work',
        status=WorkItemStatus(id='1', name='Done'),
        resolution=resolution,
        edit_meta={
            'fields': {
                'resolution': {
                    'fieldId': 'resolution',
                    'key': 'resolution',
                    'name': 'Resolution',
                    'required': False,
                    'operations': ['set'],
                    'schema': {'type': 'resolution', 'system': 'resolution'},
                    'allowedValues': [
                        {'id': '10000', 'name': 'Done'},
                        {'id': '10001', 'name': "Won't Do"},
                    ],
                },
                'customfield_12345': {
                    'fieldId': 'customfield_12345',
                    'key': 'customfield_12345',
                    'name': 'Category',
                    'required': False,
                    'operations': ['set'],
                    'schema': {
                        'type': 'option',
                        'custom': 'com.atlassian.jira.plugin.system.customfieldtypes:select',
                    },
                    'allowedValues': [{'id': '20000', 'value': 'Engineering'}],
                },
            }
        },
        custom_fields={'customfield_12345': {'id': '20000', 'value': 'Engineering'}},
    )
    async with jira_app.run_test(size=(120, 40)) as pilot:
        await jira_app._ensure_work_item_details_mounted()
        fields = jira_app.fields_panel
        monkeypatch.setattr(WorkItemFields, 'work_item', property(lambda self: work_item))
        monkeypatch.setattr(fields, '_retrieve_applicable_status_codes', AsyncMock())
        monkeypatch.setattr(fields, '_retrieve_users_assignable_to_work_item', AsyncMock())
        # Populate explicitly so the assertions cover both static and dynamic paths.
        monkeypatch.setattr(
            fields, '_start_populate_dynamic_work_item_fields_worker', lambda *args: None
        )
        await fields._populate_work_item_fields(work_item)
        await fields._add_dynamic_fields_widgets(
            work_item, {'resolution': True, 'customfield_12345': True}
        )
        await pilot.pause()

        resolutions = list(fields.query('#resolution'))
        assert len(resolutions) == 1
        assert isinstance(resolutions[0], ReadOnlyInputField)
        assert resolutions[0].value == (resolution or '')
        assert resolutions[0].disabled
        assert fields.resolution_field_container.display is bool(resolution)
        assert not list(fields.dynamic_fields_widgets_container.query('#resolution'))
        category = fields.query_one('#customfield_12345', SelectionWidget)
        assert category.value == '20000'
        assert not category.value_has_changed

        # A refresh must not reintroduce the duplicate select.
        await fields._add_dynamic_fields_widgets(
            work_item, {'resolution': True, 'customfield_12345': True}
        )
        await pilot.pause()
        assert len(list(fields.query('#resolution'))) == 1
        assert not fields.query_one('#customfield_12345', SelectionWidget).value_has_changed
