from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
import yaml

from gojeera.commands.providers.work_item_command_provider import WorkItemCommandProvider
from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.jira.factories import WorkItemFactory
from gojeera.internal.models.jira import WorkItemType
from gojeera.utils import work_item_templates
from gojeera.utils.work_item_templates import (
    WorkItemTemplatePayloadError,
    WORK_ITEM_TEMPLATE_COPY_SKIP_FIELDS,
    WORK_ITEM_TEMPLATE_COPY_SKIP_VALUE_KEYS,
    dump_work_item_template,
    prepare_work_item_template_payload,
)

FIXTURES_DIR = Path(__file__).parent / 'fixtures'


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


def test_dump_work_item_template_copies_creatable_work_item_fields() -> None:
    work_item_data = json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
    work_item_data['fields']['description']['content'].append(
        {
            'type': 'paragraph',
            'content': [
                {
                    'type': 'text',
                    'text': (
                        'Site: [\u200bHttps://fifththird.us1.plainid.io/app ]'
                        '(Https://fifththird.us1.plainid.io/app)  '
                    ),
                }
            ],
        }
    )
    work_item_data['fields']['customfield_99999'] = 'metadata unavailable'
    work_item = WorkItemFactory.create_work_item(work_item_data)

    dumped_template = dump_work_item_template(work_item)
    template = yaml.safe_load(dumped_template)

    assert template['template_name'] == 'ENG-3 Template'
    assert template['project'] == {
        'key': 'ENG',
        'name': 'Engineering Project',
    }
    assert template['issuetype'] == {
        'id': '10001',
        'name': 'Story',
    }
    assert template['summary'] == 'Review approval workflow for motion cue releases'
    assert 'description: |\n' in dumped_template
    assert 'Update documentation for merge approval process' in template['description']
    assert 'Site: [Https://fifththird.us1.plainid.io/app ]' in dumped_template
    assert '\u200b' not in dumped_template
    assert '\\n' not in dumped_template
    assert '# Story Points\ncustomfield_10016:' in dumped_template
    assert '# Organizations\ncustomfield_10727:' in dumped_template
    assert 'customfield_99999: metadata unavailable' in dumped_template
    assert template['assignee']['accountId'] == ('555000:22222222-2222-2222-2222-222222222222')
    assert template['priority'] == {'id': '3', 'name': 'Medium'}
    assert template['labels'] == ['creature-rig', 'motion-cues']
    assert template['components'] == [
        {'id': '10002', 'name': 'Frontend'},
        {'id': '10003', 'name': 'API'},
    ]
    assert 'key' not in template
    assert 'status' not in template
    assert 'attachment' not in template
    for field_id in WORK_ITEM_TEMPLATE_COPY_SKIP_FIELDS:
        assert field_id not in template
    assert_template_value_keys_stripped(template)


def test_work_item_command_provider_includes_copy_as_template_action() -> None:
    command_actions = [
        action
        for _label, action, _help_text, _screen in WorkItemCommandProvider._iter_commands(
            cast(WorkItemCommandProvider, FakeWorkItemCommandProvider())
        )
    ]

    assert 'copy_loaded_work_item_as_template' in command_actions


def test_work_item_command_provider_hides_new_comment_when_commenting_is_not_allowed() -> None:
    command_actions = [
        action
        for _label, action, _help_text, _screen in WorkItemCommandProvider._iter_commands(
            cast(
                WorkItemCommandProvider,
                FakeWorkItemCommandProvider(can_add_comment=False),
            )
        )
    ]

    assert 'new_comment' not in command_actions


class FakeWorkItemCommandProvider:
    def __init__(self, can_add_comment: bool = True):
        self._can_add_comment = can_add_comment

    def _get_main_screen(self):
        return FakeWorkItemScreen(can_add_comment=self._can_add_comment)

    def _get_loaded_work_item_key(self):
        return 'ENG-3'


class FakeWorkItemScreen:
    def __init__(self, can_add_comment: bool = True):
        self.information_panel = type(
            'FakeInformationPanel',
            (),
            {
                'work_item': WorkItemFactory.create_work_item(
                    json.loads((FIXTURES_DIR / 'jira_work_items' / 'ENG-3.json').read_text())
                )
            },
        )()
        self.work_item_comments_widget = type(
            'FakeWorkItemCommentsWidget',
            (),
            {'can_add_comment': can_add_comment},
        )()


def assert_template_value_keys_stripped(value) -> None:
    if isinstance(value, dict):
        assert not WORK_ITEM_TEMPLATE_COPY_SKIP_VALUE_KEYS.intersection(value)
        for child_value in value.values():
            assert_template_value_keys_stripped(child_value)
    elif isinstance(value, list):
        for child_value in value:
            assert_template_value_keys_stripped(child_value)
