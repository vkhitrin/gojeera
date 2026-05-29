from __future__ import annotations

import pytest

from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.models.jira import WorkItemType
from gojeera.utils import work_item_templates
from gojeera.utils.work_item_templates import (
    WorkItemTemplatePayloadError,
    prepare_work_item_template_payload,
)


class FakeTemplateAPI:
    def __init__(self) -> None:
        self.type_calls: list[str] = []
        self.metadata_calls: list[tuple[str, str]] = []

    async def get_work_item_types_for_project(
        self, project_id_or_key: str
    ) -> APIControllerResponse:
        self.type_calls.append(project_id_or_key)
        return APIControllerResponse(
            result=[
                WorkItemType(id='10001', name='Task'),
                WorkItemType(id='10002', name='Bug'),
            ]
        )

    async def get_work_item_create_metadata(
        self,
        project_id_or_key: str,
        work_item_type_id: str,
    ) -> APIControllerResponse:
        self.metadata_calls.append((project_id_or_key, work_item_type_id))
        return APIControllerResponse(
            result={
                'fields': [
                    {'fieldId': 'summary', 'key': 'summary'},
                    {'fieldId': 'description', 'key': 'description'},
                    {'fieldId': 'reporter', 'key': 'reporter'},
                    {
                        'fieldId': 'priority',
                        'key': 'priority',
                        'allowedValues': [
                            {'id': '1', 'name': 'Highest'},
                            {'id': '3', 'name': 'Medium'},
                        ],
                    },
                    {'fieldId': 'customfield_10010', 'key': 'customfield_10010'},
                    {'fieldId': 'components', 'key': 'components'},
                ]
            }
        )


@pytest.mark.asyncio
async def test_prepare_work_item_template_payload_resolves_base_and_dynamic_fields() -> None:
    api = FakeTemplateAPI()

    prepared = await prepare_work_item_template_payload(
        api,
        {
            'template_name': 'Bug report',
            'project': {'key': 'ENG'},
            'issuetype': {'id': '10002', 'name': 'Bug'},
            'summary': 'Broken thing',
            'description': 'Steps to reproduce',
            'assignee': {'accountId': 'assignee-1'},
            'reporter': 'reporter-1',
            'priority': {'name': 'Highest'},
            'customfield_10010': 'customer-visible',
            'components': ['123'],
        },
    )

    assert prepared.base_data == {
        'project_key': 'ENG',
        'work_item_type_id': '10002',
        'summary': 'Broken thing',
        'description': 'Steps to reproduce',
        'assignee_account_id': 'assignee-1',
        'reporter_account_id': 'reporter-1',
        'priority': '1',
    }
    assert prepared.dynamic_fields == {
        'customfield_10010': 'customer-visible',
        'components': ['123'],
    }
    assert prepared.available_fields == {
        'summary',
        'description',
        'reporter',
        'priority',
        'customfield_10010',
        'components',
    }
    assert api.type_calls == []
    assert api.metadata_calls == [('ENG', '10002')]


@pytest.mark.asyncio
async def test_prepare_work_item_template_payload_resolves_issue_type_name(monkeypatch) -> None:
    class EmptyCache:
        def get_project_work_item_types(self, _project_key: str):
            return None

        def set_project_work_item_types(self, _project_key: str, _types):
            return None

    monkeypatch.setattr(work_item_templates, 'get_cache', lambda: EmptyCache())
    api = FakeTemplateAPI()

    prepared = await prepare_work_item_template_payload(
        api,
        {
            'project': 'ENG',
            'issuetype': 'Bug',
            'summary': 'Named type',
        },
    )

    assert prepared.base_data['work_item_type_id'] == '10002'
    assert api.type_calls == ['ENG']
    assert api.metadata_calls == [('ENG', '10002')]


@pytest.mark.asyncio
async def test_prepare_work_item_template_payload_requires_project_and_issue_type() -> None:
    with pytest.raises(WorkItemTemplatePayloadError, match='project and issuetype'):
        await prepare_work_item_template_payload(FakeTemplateAPI(), {'summary': 'Missing fields'})


@pytest.mark.asyncio
async def test_prepare_work_item_template_payload_fetches_metadata_per_call() -> None:
    api = FakeTemplateAPI()
    template = {'project': 'ENG', 'issuetype': {'id': '10002'}, 'summary': 'Fresh metadata'}

    await prepare_work_item_template_payload(api, template)
    await prepare_work_item_template_payload(api, template)

    assert api.metadata_calls == [('ENG', '10002'), ('ENG', '10002')]
