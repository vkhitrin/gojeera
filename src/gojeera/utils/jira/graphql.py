from importlib import resources

GRAPHQL_PROJECT_REPOSITORY_PAGE_SIZE = 1000
GRAPHQL_PROJECT_PULL_REQUEST_PAGE_SIZE = 100
GRAPHQL_PROJECT_PULL_REQUEST_MAX_PAGES = 5
GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR = (
    'Atlassian does not allow GraphStore.projectAssociatedRepo to be called by '
    'third-party OAuth clients. Use an API-token profile to fetch project repositories.'
)
GRAPHQL_PROJECT_PULL_REQUESTS_OAUTH_ERROR = (
    'Atlassian does not allow GraphStore.projectAssociatedPr to be called by '
    'third-party OAuth clients. Use an API-token profile to fetch project pull requests.'
)
GRAPHQL_WORK_ITEM_PULL_REQUESTS_OAUTH_ERROR = (
    'Atlassian does not allow GraphStore issue pull request relationships to be called by '
    'third-party OAuth clients. Use an API-token profile to fetch work item pull requests.'
)

GRAPHQL_QUERY_PACKAGE = 'gojeera.utils.jira.graphql_queries'


def load_graphql_document(name: str) -> str:
    return resources.files(GRAPHQL_QUERY_PACKAGE).joinpath(name).read_text().strip()


GRAPHQL_PAGE_INFO_FIELDS = load_graphql_document('page_info.fragment.graphql')
GRAPHQL_PROVIDER_FIELDS = load_graphql_document('provider.fragment.graphql')
GRAPHQL_BRANCH_PAIR_FIELDS = load_graphql_document('branch_pair.fragment.graphql')
GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS = (
    load_graphql_document('external_pull_request.fragment.graphql')
    .replace('__BRANCH_PAIR_FIELDS__', GRAPHQL_BRANCH_PAIR_FIELDS)
    .replace('__PROVIDER_FIELDS__', GRAPHQL_PROVIDER_FIELDS)
)
GRAPHQL_PULL_REQUEST_DETAILS_FRAGMENT = (
    load_graphql_document('pull_request_details.fragment.graphql')
    .replace('__BRANCH_PAIR_FIELDS__', GRAPHQL_BRANCH_PAIR_FIELDS)
    .replace('__EXTERNAL_PULL_REQUEST_FIELDS__', GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS)
)
GRAPHQL_PROJECT_BY_KEY_QUERY = load_graphql_document('project_by_key.graphql')
GRAPHQL_PROJECT_REPOSITORIES_QUERY = (
    load_graphql_document('project_repositories.graphql')
    .replace('__PROVIDER_FIELDS__', GRAPHQL_PROVIDER_FIELDS)
    .replace('__PAGE_INFO_FIELDS__', GRAPHQL_PAGE_INFO_FIELDS)
)
GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY = (
    load_graphql_document('project_space_pull_requests.graphql')
    .replace('__EXTERNAL_PULL_REQUEST_FIELDS__', GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS)
    .replace('__PAGE_INFO_FIELDS__', GRAPHQL_PAGE_INFO_FIELDS)
)
GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY = (
    load_graphql_document('work_item_pull_requests.graphql')
    .replace('__PULL_REQUEST_DETAILS__', GRAPHQL_PULL_REQUEST_DETAILS_FRAGMENT)
    .replace('__PAGE_INFO_FIELDS__', GRAPHQL_PAGE_INFO_FIELDS)
)

GRAPHQL_QUERIES = {
    'project_by_key': GRAPHQL_PROJECT_BY_KEY_QUERY,
    'project_repositories': GRAPHQL_PROJECT_REPOSITORIES_QUERY,
    'project_space_pull_requests': GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY,
    'work_item_pull_requests': GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY,
}

__all__ = [
    'GRAPHQL_BRANCH_PAIR_FIELDS',
    'GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS',
    'GRAPHQL_PAGE_INFO_FIELDS',
    'GRAPHQL_PROJECT_BY_KEY_QUERY',
    'GRAPHQL_PROJECT_PULL_REQUEST_MAX_PAGES',
    'GRAPHQL_PROJECT_PULL_REQUEST_PAGE_SIZE',
    'GRAPHQL_PROJECT_PULL_REQUESTS_OAUTH_ERROR',
    'GRAPHQL_PROJECT_REPOSITORIES_OAUTH_ERROR',
    'GRAPHQL_PROJECT_REPOSITORIES_QUERY',
    'GRAPHQL_PROJECT_REPOSITORY_PAGE_SIZE',
    'GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY',
    'GRAPHQL_PROVIDER_FIELDS',
    'GRAPHQL_PULL_REQUEST_DETAILS_FRAGMENT',
    'GRAPHQL_QUERIES',
    'GRAPHQL_QUERY_PACKAGE',
    'GRAPHQL_WORK_ITEM_PULL_REQUESTS_OAUTH_ERROR',
    'GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY',
    'load_graphql_document',
]
