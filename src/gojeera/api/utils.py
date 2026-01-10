from datetime import date


def build_work_item_search_jql(
    project_key: str | None = None,
    created_from: date | None = None,
    created_until: date | None = None,
    updated_from: date | None = None,
    updated_until: date | None = None,
    status: int | None = None,
    assignee: str | None = None,
    work_item_type: int | None = None,
    jql_query: str | None = None,
    search_in_active_sprint: bool = False,
) -> str:
    fields: list[str] = []
    if project_key:
        fields.append(f'project = "{project_key}"')
    if created_from:
        value = date.strftime(created_from, '%Y-%m-%d')
        fields.append(f'created >= "{value}"')
    if created_until:
        value = date.strftime(created_until, '%Y-%m-%d')
        fields.append(f'created <= "{value}"')
    if updated_from:
        value = date.strftime(updated_from, '%Y-%m-%d')
        fields.append(f'updated >= "{value}"')
    if updated_until:
        value = date.strftime(updated_until, '%Y-%m-%d')
        fields.append(f'updated <= "{value}"')
    if status:
        fields.append(f'status = "{status}"')
    if assignee:
        fields.append(f'assignee = "{assignee}"')
    if work_item_type:
        fields.append(f'type = {work_item_type}')
    if search_in_active_sprint:
        fields.append('sprint in openSprints()')

    jql: str = ''
    if fields:
        jql = ' and '.join(fields)
    if jql_query:
        if jql:
            jql = f'{jql} and {jql_query}'
        else:
            jql = jql_query
    return jql
