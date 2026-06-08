from datetime import date


FLAGGED_FIELD_NAME = 'Flagged[Checkboxes]'
FLAGGED_FIELD_VALUE = 'Impediment'


def quote_jql_string(value: str) -> str:
    escaped = value.replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def text_search_jql(text: str | None) -> str:
    if not text:
        return ''
    return f'textfields ~ {quote_jql_string(text)}'


def work_item_flagged_jql(work_item_key: str) -> str:
    return (
        f'key = {quote_jql_string(work_item_key)} '
        f'AND {quote_jql_string(FLAGGED_FIELD_NAME)} = {FLAGGED_FIELD_VALUE}'
    )


def build_work_item_search_jql(
    jql_query: str | None = None,
    search_in_active_sprint: bool = False,
    project_key: str | None = None,
    updated_from: date | None = None,
    updated_until: date | None = None,
    created_from: date | None = None,
    created_until: date | None = None,
    status: int | None = None,
    assignee: str | None = None,
    work_item_type: int | None = None,
) -> str:
    fields: list[str] = []
    if project_key:
        fields.append(f'project = {quote_jql_string(project_key)}')
    if created_from:
        value = date.strftime(created_from, '%Y-%m-%d')
        fields.append(f'created >= {quote_jql_string(value)}')
    if created_until:
        value = date.strftime(created_until, '%Y-%m-%d')
        fields.append(f'created <= {quote_jql_string(value)}')
    if updated_from:
        value = date.strftime(updated_from, '%Y-%m-%d')
        fields.append(f'updated >= {quote_jql_string(value)}')
    if updated_until:
        value = date.strftime(updated_until, '%Y-%m-%d')
        fields.append(f'updated <= {quote_jql_string(value)}')
    if status:
        fields.append(f'status = {quote_jql_string(str(status))}')
    if assignee:
        fields.append(f'assignee = {quote_jql_string(assignee)}')
    if work_item_type:
        fields.append(f'type = {work_item_type}')
    if search_in_active_sprint:
        fields.append('sprint in openSprints()')

    jql = ' and '.join(fields)
    if jql_query:
        normalized_jql_query = jql_query.strip()
        if jql:
            if normalized_jql_query.lower().startswith('order by '):
                jql = f'{jql} {normalized_jql_query}'
            else:
                jql = f'{jql} and {normalized_jql_query}'
        else:
            jql = normalized_jql_query
    return jql
