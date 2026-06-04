import logging
from unittest.mock import AsyncMock

from gojeera.internal.jira.api import JiraAPI


def build_api_with_mocked_client(responses: list[dict]) -> tuple[JiraAPI, AsyncMock]:
    api = JiraAPI.__new__(JiraAPI)
    api.logger = logging.getLogger('gojeera.test')
    api._client = AsyncMock()
    api._client.make_request = AsyncMock(side_effect=responses)
    return api, api._client.make_request
