from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import yaml

from gojeera.internal.jira.controller import APIControllerResponse
from gojeera.internal.store.cache import get_cache, run_cache_io
from gojeera.internal.store.files import get_templates_directory, list_yaml_files, load_yaml_mapping
from gojeera.utils.markdown.adf_helpers import convert_adf_to_markdown

TEMPLATE_NAME_FIELD = 'template_name'

WorkItemTemplate = dict[str, Any]


class WorkItemTemplateError(Exception):
    """Raised when a work item template file is invalid."""


def list_work_item_template_files(templates_directory: Path | None = None) -> list[Path]:
    """Return all YAML work item template files from the templates directory."""
    directory = (
        templates_directory if templates_directory is not None else get_templates_directory()
    )
    return list_yaml_files(directory)


def has_valid_work_item_templates(templates_directory: Path | None = None) -> bool:
    """Return whether at least one work item template file can be loaded."""
    for template_file in list_work_item_template_files(templates_directory):
        try:
            load_work_item_template(template_file)
        except (OSError, WorkItemTemplateError):
            continue
        return True
    return False


def load_work_item_template(path: Path) -> WorkItemTemplate:
    """Load a work item template YAML file.

    Template files contain a ``template_name`` display field plus mappings of
    Jira field IDs or canonical field names to values accepted by Jira's create
    work item API payload.
    """
    try:
        return load_yaml_mapping(path, default_empty={})
    except yaml.YAMLError as error:
        raise WorkItemTemplateError(f'Work item template contains invalid YAML: {path}') from error
    except TypeError as error:
        raise WorkItemTemplateError(f'Work item template must be a mapping: {path}') from error


class WorkItemTemplatePayloadError(RuntimeError):
    """Raised when a template cannot be converted to a create payload."""


class WorkItemTemplateAPI(Protocol):
    async def get_work_item_types_for_project(
        self, project_id_or_key: str
    ) -> APIControllerResponse: ...

    async def get_work_item_create_metadata(
        self,
        project_id_or_key: str,
        work_item_type_id: str,
    ) -> APIControllerResponse: ...


@dataclass(frozen=True)
class PreparedWorkItemTemplatePayload:
    base_data: dict[str, object | None]
    dynamic_fields: dict[str, object]
    available_fields: set[str]


def template_project_key(template: WorkItemTemplate) -> str | None:
    project = template.get('project')
    if isinstance(project, dict):
        project_data = project
        key = project_data.get('key')
        return str(key) if key else None
    return str(project) if project else None


def template_issue_type_name(template: WorkItemTemplate) -> str | None:
    issue_type = template.get('issuetype')
    if isinstance(issue_type, dict):
        issue_type_data = issue_type
        name = issue_type_data.get('name')
        return str(name) if name else None
    return str(issue_type) if issue_type else None


def template_issue_type_id(template: WorkItemTemplate) -> str | None:
    issue_type = template.get('issuetype')
    if isinstance(issue_type, dict):
        issue_type_data = issue_type
        issue_type_id = issue_type_data.get('id')
        return str(issue_type_id) if issue_type_id else None
    return None


def _template_account_id(value: object) -> str | None:
    if isinstance(value, dict):
        value_data = cast(dict[str, object], value)
        account_id = value_data.get('accountId')
        return str(account_id) if account_id else None
    return str(value) if value else None


def _resolve_allowed_value(value: object, allowed_values: list[dict]) -> object:
    if not isinstance(value, dict):
        return value
    value_data = cast(dict[str, object], value)
    if value_data.get('id'):
        return value_data.get('id')
    display_value = value_data.get('name') or value_data.get('value')
    if display_value is None:
        return value
    for allowed_value in allowed_values:
        if display_value in (allowed_value.get('name'), allowed_value.get('value')):
            return allowed_value.get('id') or value
    return value


async def _resolve_work_item_type_id(
    api: WorkItemTemplateAPI,
    project_key: str,
    issue_type_name: str,
) -> str:
    cache = get_cache()
    work_item_types = await run_cache_io(lambda: cache.get_project_work_item_types(project_key))
    if work_item_types is None:
        response = await api.get_work_item_types_for_project(project_key)
        if not response.success or not response.result:
            raise WorkItemTemplatePayloadError(f'Failed to fetch work item types: {response.error}')
        work_item_types = response.result
        await run_cache_io(lambda: cache.set_project_work_item_types(project_key, work_item_types))

    for issue_type in work_item_types:
        if issue_type.name == issue_type_name:
            return str(issue_type.id)

    raise WorkItemTemplatePayloadError(f'Unable to find work item type: {issue_type_name}')


async def prepare_work_item_template_payload(
    api: WorkItemTemplateAPI,
    template: WorkItemTemplate,
) -> PreparedWorkItemTemplatePayload:
    project_key = template_project_key(template)
    issue_type_name = template_issue_type_name(template)
    issue_type_id = template_issue_type_id(template)
    if not project_key or not (issue_type_id or issue_type_name):
        raise WorkItemTemplatePayloadError(
            'Template must define project and issuetype to create a work item.'
        )

    if not issue_type_id:
        issue_type_id = await _resolve_work_item_type_id(
            api, project_key, cast(str, issue_type_name)
        )
    metadata_response = await api.get_work_item_create_metadata(project_key, issue_type_id)
    if not metadata_response.success or not metadata_response.result:
        raise WorkItemTemplatePayloadError(
            f'Failed to fetch create metadata: {metadata_response.error}'
        )

    metadata_fields = metadata_response.result.get('fields', [])
    metadata_by_id = {
        field.get('fieldId'): field for field in metadata_fields if field.get('fieldId')
    }
    metadata_by_key = {field.get('key'): field for field in metadata_fields if field.get('key')}
    available_fields = {field.get('key') for field in metadata_fields if field.get('key')}

    description = template.get('description')
    if isinstance(description, dict):
        description = convert_adf_to_markdown(description, base_url=None)

    base_data: dict[str, object | None] = {
        'project_key': project_key,
        'work_item_type_id': issue_type_id,
        'summary': template.get('summary'),
        'description': description,
        'assignee_account_id': _template_account_id(template.get('assignee')),
        'reporter_account_id': _template_account_id(template.get('reporter')),
    }

    dynamic_fields: dict[str, object] = {}
    skipped_fields = {
        TEMPLATE_NAME_FIELD,
        'project',
        'issuetype',
        'summary',
        'description',
        'assignee',
        'reporter',
    }
    for field_id, field_value in template.items():
        if field_id in skipped_fields:
            continue
        field_metadata = metadata_by_id.get(field_id) or metadata_by_key.get(field_id)
        if field_id == 'priority':
            allowed_values = field_metadata.get('allowedValues', []) if field_metadata else []
            base_data['priority'] = _resolve_allowed_value(field_value, allowed_values)
            continue
        dynamic_fields[field_id] = field_value

    return PreparedWorkItemTemplatePayload(
        base_data=base_data,
        dynamic_fields=dynamic_fields,
        available_fields=available_fields,
    )
