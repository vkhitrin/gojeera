from enum import Enum

WORK_ITEM_SEARCH_DEFAULT_MAX_RESULTS = 50
"""The default maximum number of results to return in issue searches."""

ATTACHMENT_MAXIMUM_FILE_SIZE_IN_BYTES = 10485760
"""The maximum size of files that can be attached to work items. This is a restriction imposed by this tool and not by
Jira."""

LOGGER_NAME = 'gojeera'
"""Application logger name identifier."""

LOG_FILE_FILE_NAME = 'gojeera.log'
"""Default log file name."""

API_PATH_PREFIX = '/rest/api/3/'
"""Jira REST API v3 path prefix."""

RECORDS_PER_PAGE_SEARCH_PROJECTS = 100
"""The maximum number of items to return per page when searching for projects. The number should be between 1 and
100."""

MAXIMUM_PAGE_NUMBER_SEARCH_PROJECTS = 10
"""Maximum number of pages to retrieve when fetching projects."""

RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_PROJECTS = 1000
"""Maximum items per page for users assignable to projects."""

RECORDS_PER_PAGE_SEARCH_USERS_ASSIGNABLE_TO_WORK_ITEMS = 1000
"""Maximum items per page for users assignable to work items."""

CSS_PATH = 'gojeera.tcss'
"""Path to Textual CSS file."""

TITLE = 'gojeera'
"""Application title."""

DEFAULT_THEME = 'textual-dark'
"""Default UI theme."""

CACHE_TTL_PROJECTS = 3600
"""Cache TTL for projects."""

CACHE_TTL_USERS = 1800
"""Cache TTL for users."""

CACHE_TTL_TYPES = 3600
"""Cache TTL for issue types."""

CACHE_TTL_STATUSES = 3600
"""Cache TTL for statuses."""

CACHE_TTL_PROJECT_USERS = 1800
"""Cache TTL for project users."""

CACHE_TTL_PROJECT_TYPES = 3600
"""Cache TTL for project types."""

CACHE_TTL_PROJECT_STATUSES = 3600
"""Cache TTL for project statuses."""

CACHE_TTL_REMOTE_FILTERS = 3600
"""Cache TTL for remote JQL filters from Jira server."""

SKIP_FIELDS = [
    'project',
    'issuetype',
    'reporter',
    'summary',
    'description',
    'parent',
]
"""List of field IDs to skip when creating work items (handled separately)."""

PROCESS_OPTIONAL_FIELDS = ['duedate', 'priority']
"""Optional fields to include when enable_creating_additional_fields is False."""


class CustomFieldType(Enum):
    """Known Jira custom field types that map to specific widgets."""

    USER_PICKER = 'com.atlassian.jira.plugin.system.customfieldtypes:userpicker'
    FLOAT = 'com.atlassian.jira.plugin.system.customfieldtypes:float'
    SELECT = 'com.atlassian.jira.plugin.system.customfieldtypes:select'
    DATE_PICKER = 'com.atlassian.jira.plugin.system.customfieldtypes:datepicker'
    DATETIME = 'com.atlassian.jira.plugin.system.customfieldtypes:datetime'
    TEXT_FIELD = 'com.atlassian.jira.plugin.system.customfieldtypes:textfield'
    TEXTAREA = 'com.atlassian.jira.plugin.system.customfieldtypes:textarea'
    LABELS = 'com.atlassian.jira.plugin.system.customfieldtypes:labels'
    URL = 'com.atlassian.jira.plugin.system.customfieldtypes:url'
    MULTI_CHECKBOXES = 'com.atlassian.jira.plugin.system.customfieldtypes:multicheckboxes'
    MULTI_SELECT = 'com.atlassian.jira.plugin.system.customfieldtypes:multiselect'
    SD_REQUEST_LANGUAGE = (
        'com.atlassian.servicedesk.servicedesk-lingo-integration-plugin:sd-request-language'
    )


class SupportedAttachmentVisualizationMimeTypes(Enum):
    """MIME types supported for attachment visualization."""

    IMAGE_WEBP = 'image/webp'
    IMAGE_PNG = 'image/png'
    IMAGE_JPEG = 'image/jpeg'
    IMAGE_JPG = 'image/jpg'
    IMAGE_GIF = 'image/gif'
    IMAGE_BMP = 'image/bmp'
    IMAGE_AVIF = 'image/avif'
    IMAGE_TIFF = 'image/tiff'
    APPLICATION_JSON = 'application/json'
    APPLICATION_XML = 'application/xml'
    TEXT_CSV = 'text/csv'
    TEXT_PLAIN = 'text/plain'
    TEXT_MARKDOWN = 'text/markdown'


class WorkItemManualUpdateFieldKeys(Enum):
    """Fields excluded from dynamic updates because they're in the static form or updated separately."""

    LABELS = 'labels'
    COMMENT = 'comment'
    DESCRIPTION = 'description'
    DUE_DATE = 'duedate'
    WORK_ITEM_LINKS = 'issuelinks'
    ATTACHMENT = 'attachment'
    ASSIGNEE = 'assignee'
    PARENT = 'parent'
    SUMMARY = 'summary'
    PRIORITY = 'priority'
    TIME_TRACKING = 'timetracking'
    COMPONENTS = 'components'
    VERSIONS = 'versions'
    FIX_VERSIONS = 'fixVersions'
    STORY_POINTS = 'story points'


class WorkItemUnsupportedUpdateFieldKeys(Enum):
    """Fields the app does not currently support updating."""

    REPORTER = 'reporter'
    PROJECT = 'project'
    WORK_ITEM_TYPE = 'issuetype'
    SPRINT = 'sprint'
    TEAM = 'team'
    ENVIRONMENT = 'environment'
