from unittest.mock import AsyncMock

import pytest

from gojeera.internal.jira.controller import APIController
from gojeera.internal.store.cache import CACHE_TTL_GLOBAL_SETTINGS, CACHE_TTL_SERVER_INFO


@pytest.mark.asyncio
async def test_startup_metadata_uses_cache_but_identity_does_not(
    application_cache,
    monkeypatch,
    mock_configuration,
    mock_jira_configuration,
    mock_jira_myself,
    mock_jira_server_info,
) -> None:
    import gojeera.internal.store.cache as cache_module

    current_time = 1000.0
    monkeypatch.setattr(cache_module.time, 'time', lambda: current_time)
    controller = APIController(configuration=mock_configuration)
    controller.cache = application_cache
    server_info_request = AsyncMock(return_value=mock_jira_server_info)
    global_settings_request = AsyncMock(return_value=mock_jira_configuration)
    identity_request = AsyncMock(return_value=mock_jira_myself)
    controller.client.server_info = server_info_request
    controller.client.global_settings = global_settings_request
    controller.client.myself = identity_request

    try:
        first_server_info = await controller.server_info()
        first_global_settings = await controller.global_settings()
        second_server_info = await controller.server_info()
        second_global_settings = await controller.global_settings()

        current_time += CACHE_TTL_GLOBAL_SETTINGS + 1
        await controller.global_settings()

        current_time = 1000.0 + CACHE_TTL_SERVER_INFO + 1
        await controller.server_info()

        await controller.myself()
        await controller.myself()
    finally:
        await controller.close()

    assert first_server_info.success
    assert first_global_settings.success
    assert second_server_info.result == first_server_info.result
    assert second_global_settings.result == first_global_settings.result
    assert server_info_request.await_count == 2
    assert global_settings_request.await_count == 2
    assert identity_request.await_count == 2
