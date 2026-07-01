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

GRAPHQL_PROJECT_BY_KEY_QUERY = """
query GojeeraProjectByKey($cloudId: ID!, $projectKey: String!) {
  jira_projectByIdOrKey(cloudId: $cloudId, idOrKey: $projectKey) {
    id
    key
  }
}
"""

GRAPHQL_PAGE_INFO_FIELDS = """
pageInfo {
  hasNextPage
  endCursor
}
"""
GRAPHQL_PROVIDER_FIELDS = """
provider {
  providerId
  name
}
"""
GRAPHQL_PROJECT_REPOSITORIES_QUERY = """
query GojeeraProjectRepositories($projectAri: ID!, $first: Int!, $after: String) {
  graphStore @optIn(to: ["GraphStore", "GraphStoreProjectAssociatedRepo"]) {
    projectAssociatedRepo(id: $projectAri, first: $first, after: $after) {
      edges {
        id
        node {
          __typename
          ... on DevOpsRepository {
            id
            providerId
            name
            devOpsUrl: url
            externalId
          }
          ... on ExternalRepository {
            id
            name
            displayName
            externalUrl: url
            repositoryId
            thirdPartyId
            __PROVIDER_FIELDS__
          }
        }
      }
      __PAGE_INFO_FIELDS__
    }
  }
}
""".replace('__PROVIDER_FIELDS__', GRAPHQL_PROVIDER_FIELDS).replace(
    '__PAGE_INFO_FIELDS__', GRAPHQL_PAGE_INFO_FIELDS
)
GRAPHQL_BRANCH_PAIR_FIELDS = """
sourceBranch {
  name
}
destinationBranch {
  name
}
"""
GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS = """
  id
  externalRepositoryId: repositoryId
  title
  externalStatus: status
  url
  pullRequestId
  thirdPartyId
  lastUpdate
  __BRANCH_PAIR_FIELDS__
  __PROVIDER_FIELDS__
""".replace('__BRANCH_PAIR_FIELDS__', GRAPHQL_BRANCH_PAIR_FIELDS).replace(
    '__PROVIDER_FIELDS__', GRAPHQL_PROVIDER_FIELDS
)
GRAPHQL_PULL_REQUEST_DETAILS_FRAGMENT = """
__typename
... on DevOpsPullRequestDetails {
  id
  devOpsRepositoryId: repositoryId
  repositoryInternalId
  repositoryName
  repositoryUrl
  title
  devOpsStatus: status
  url
  pullRequestInternalId
  providerId
  providerName
  lastUpdated
  __BRANCH_PAIR_FIELDS__
  author {
    name
  }
}
... on ExternalPullRequest {
  __EXTERNAL_PULL_REQUEST_FIELDS__
}
""".replace('__BRANCH_PAIR_FIELDS__', GRAPHQL_BRANCH_PAIR_FIELDS).replace(
    '__EXTERNAL_PULL_REQUEST_FIELDS__', GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS
)

GRAPHQL_PROJECT_SPACE_PULL_REQUESTS_QUERY = """
query GojeeraProjectSpacePullRequests($projectAri: ID!, $first: Int!, $after: String) {
  graphStoreV2 @optIn(to: ["GraphStoreV2", "GraphStoreV2ProjectAssociatedPr"]) {
    jiraSpaceLinksExternalPullRequest(
      id: $projectAri,
      first: $first,
      after: $after,
      sort: { lastModified: { direction: DESC, priority: 1 } }
    ) {
      edges {
        id
        createdAt
        lastUpdated
        node {
          __typename
          ... on ExternalPullRequest {
            __EXTERNAL_PULL_REQUEST_FIELDS__
          }
        }
      }
      __PAGE_INFO_FIELDS__
    }
  }
}
""".replace('__EXTERNAL_PULL_REQUEST_FIELDS__', GRAPHQL_EXTERNAL_PULL_REQUEST_FIELDS).replace(
    '__PAGE_INFO_FIELDS__',
    GRAPHQL_PAGE_INFO_FIELDS,
)

GRAPHQL_WORK_ITEM_PULL_REQUESTS_QUERY = """
query GojeeraWorkItemPullRequests($issueAri: ID!, $first: Int!, $after: String) {
  graphStoreV2_jiraWorkItemLinksExternalPullRequest(
    id: $issueAri,
    first: $first,
    after: $after,
    sort: { lastModified: { direction: DESC, priority: 1 } }
  ) @optIn(to: "GraphStoreV2IssueAssociatedPr") {
    edges {
      id
      createdAt
      lastUpdated
      node {
        __PULL_REQUEST_DETAILS__
      }
    }
    __PAGE_INFO_FIELDS__
  }
}
""".replace('__PULL_REQUEST_DETAILS__', GRAPHQL_PULL_REQUEST_DETAILS_FRAGMENT).replace(
    '__PAGE_INFO_FIELDS__', GRAPHQL_PAGE_INFO_FIELDS
)
