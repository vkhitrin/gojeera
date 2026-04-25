# ruff: noqa: E402
from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
from typing import TYPE_CHECKING, Any, Callable, NoReturn, cast

# https://darren.codes/posts/python-startup-time/
sys.modules['httpx._main'] = cast(Any, None)
import httpx

from gojeera.internal.models.exceptions import (
    AuthorizationException,
    PermissionException,
    ResourceNotFoundException,
    ServiceInvalidRequestException,
    ServiceInvalidResponseException,
    ServiceUnavailableException,
)
from gojeera.utils.system.logging_utils import build_log_extra

if TYPE_CHECKING:
    from gojeera.internal.store.config import ApplicationConfiguration


@dataclass
class SSLCertificateSettings:
    cert: str | tuple[str, str] | tuple[str, str, str] | None = None
    verify_ssl: str | bool = True


@dataclass(frozen=True)
class AsyncRequestUrls:
    request_url: str | None = None
    context_url: str | None = None
    log_url: str | None = None


def _setup_ssl_certificates(configuration: ApplicationConfiguration) -> SSLCertificateSettings:
    cert: str | tuple[str, str] | tuple[str, str, str] | None = None
    verify_ssl: str | bool = True

    if ssl_certificate_configuration := configuration.ssl:
        verify_ssl = ssl_certificate_configuration.verify_ssl
        httpx_certificate_configuration: list[str] = []
        if certificate_path := ssl_certificate_configuration.certificate_file:
            httpx_certificate_configuration.append(certificate_path)
        if key_file := ssl_certificate_configuration.key_file:
            httpx_certificate_configuration.append(key_file)
        if password := ssl_certificate_configuration.password:
            httpx_certificate_configuration.append(password.get_secret_value())

        if verify_ssl and ssl_certificate_configuration.ca_bundle:
            verify_ssl = ssl_certificate_configuration.ca_bundle

        cert = cast(
            str | tuple[str, str] | tuple[str, str, str], tuple(httpx_certificate_configuration)
        )

    return SSLCertificateSettings(cert=cert, verify_ssl=verify_ssl)


class BaseHTTPClient:
    client: httpx.AsyncClient | httpx.Client

    def __init__(
        self,
        base_url: str,
        api_email: str | None,
        api_token: str | None,
        configuration: ApplicationConfiguration,
        instance_base_url: str | None = None,
        bearer_token: str | None = None,
        token_refresh_callback: Callable[[], str | None] | None = None,
    ) -> None:
        self.base_url: str = base_url.rstrip('/')
        self.instance_base_url: str | None = (
            instance_base_url.rstrip('/') if instance_base_url else None
        )
        self.authentication = (
            httpx.BasicAuth(api_email, api_token.strip())
            if api_email is not None and api_token is not None
            else None
        )
        self.default_headers: dict[str, str] = {}
        if bearer_token is not None:
            self.default_headers['Authorization'] = f'Bearer {bearer_token.strip()}'
        self.logger = logging.getLogger('gojeera')
        self.token_refresh_callback = token_refresh_callback
        self.client = self._create_client(configuration)

    @staticmethod
    def _build_client_kwargs(configuration: ApplicationConfiguration) -> dict[str, Any]:
        ssl_certificate_settings: SSLCertificateSettings = _setup_ssl_certificates(configuration)
        timeout = httpx.Timeout(60.0, connect=10.0, read=60.0, write=30.0)
        return {
            'verify': ssl_certificate_settings.verify_ssl,
            'cert': ssl_certificate_settings.cert,
            'timeout': timeout,
        }

    def _create_client(
        self, configuration: ApplicationConfiguration
    ) -> httpx.AsyncClient | httpx.Client:
        del configuration
        raise NotImplementedError

    def get_resource_url(self, resource: str) -> str:
        return f'{self.base_url}/{resource}'

    def set_headers(self, headers: dict | None = None) -> dict[str, str]:
        del headers
        raise NotImplementedError

    def set_bearer_token(self, bearer_token: str | None) -> None:
        if bearer_token is None:
            self.default_headers.pop('Authorization', None)
        else:
            self.default_headers['Authorization'] = f'Bearer {bearer_token.strip()}'

    def _handle_transport_exception(self, error: Exception, url: str) -> None:
        msg = f'{error.__class__.__name__}: {error}.'
        self.logger.error(msg, extra=build_log_extra({'url': url}))
        raise ServiceUnavailableException(msg, context={'url': url}) from error

    def _can_retry_after_refresh(self, response: httpx.Response, retry_after_refresh: bool) -> bool:
        return (
            response.status_code == 401
            and retry_after_refresh
            and self.authentication is None
            and 'Authorization' in self.default_headers
            and self.token_refresh_callback is not None
        )

    def _refresh_bearer_token(self, log_url: str) -> bool:
        if self.token_refresh_callback is None:
            return False
        try:
            refreshed_token = self.token_refresh_callback()
        except Exception as refresh_error:
            self.logger.warning(
                'OAuth2 token refresh failed',
                extra=build_log_extra({'url': log_url, 'error': str(refresh_error)}),
            )
            return False

        if not refreshed_token:
            return False

        self.set_bearer_token(refreshed_token)
        return True

    def _extract_error_message(
        self, error: httpx.HTTPStatusError, error_details: dict | None
    ) -> tuple[str, dict[str, Any]]:
        extra: dict[str, Any] = {
            'url': str(error.request.url),
            'status_code': error.response.status_code,
        }
        message = str(error)
        if error_details is not None and isinstance(error_details, dict):
            if error_details.get('errorMessages', []):
                message = error_details.get('errorMessages', [])[0]
            extra.update(**error_details)
        return message, extra

    def _log_http_status_error(
        self,
        response: httpx.Response,
        message: str,
        extra: dict[str, Any],
        error_details: dict | None,
    ) -> None:
        log_method = self.logger.error
        if (
            response.status_code == 400
            and isinstance(error_details, dict)
            and 'does not support sprints'
            in str(error_details.get('errorMessages', [''])[0]).lower()
        ):
            log_method = self.logger.warning

        log_method(message, extra=build_log_extra(extra))

    def _raise_service_http_error(
        self,
        response: httpx.Response,
        message: str,
        error_details: dict | None,
        original_error: httpx.HTTPStatusError,
        context_url: str,
    ) -> NoReturn:
        context = {'url': context_url, 'status_code': response.status_code}
        if response.status_code == 404:
            raise ResourceNotFoundException(
                message,
                context=context,
                remote_payload=error_details,
            ) from original_error
        if response.status_code == 401:
            raise AuthorizationException(
                message,
                context=context,
                remote_payload=error_details,
            ) from original_error
        if response.status_code == 403:
            raise PermissionException(
                message,
                context=context,
                remote_payload=error_details,
            ) from original_error
        raise ServiceInvalidRequestException(
            message,
            context=context,
            remote_payload=error_details,
        ) from original_error

    def _handle_http_status_error(
        self,
        response: httpx.Response,
        error: httpx.HTTPStatusError,
        *,
        context_url: str,
        log_url: str,
        retry_after_refresh: bool,
    ) -> bool:
        if self._can_retry_after_refresh(
            response, retry_after_refresh
        ) and self._refresh_bearer_token(log_url):
            return True

        error_details = self._parse_error_response(response)
        message, extra = self._extract_error_message(error, error_details)
        extra['url'] = context_url
        self._log_http_status_error(response, message, extra, error_details)
        self._raise_service_http_error(response, message, error_details, error, context_url)

    def _parse_success_response(
        self,
        response: httpx.Response,
        *,
        context_url: str,
        log_url: str,
    ) -> Any:
        if response.status_code == 204:
            return self._empty_response(response)

        try:
            return self._parse_response(response)
        except Exception as error:
            if response.status_code == 201:
                return self._empty_response(response)
            log_msg = f'{error.__class__.__name__}: {error}.'
            self.logger.error(
                log_msg,
                extra=build_log_extra({'url': log_url, 'status_code': response.status_code}),
            )
            raise ServiceInvalidResponseException(
                log_msg, context={'url': context_url, 'status_code': response.status_code}
            ) from error

    def _handle_request_response(
        self,
        response: httpx.Response,
        *,
        request_url: str,
        retry_after_refresh: bool,
    ) -> tuple[bool, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            should_retry = self._handle_http_status_error(
                response,
                error,
                context_url=request_url,
                log_url=request_url,
                retry_after_refresh=retry_after_refresh,
            )
            return should_retry, None

        return (
            False,
            self._parse_success_response(
                response,
                context_url=request_url,
                log_url=request_url,
            ),
        )

    def _merge_headers(
        self, default_headers: dict[str, str], headers: dict | None = None
    ) -> dict[str, str]:
        merged_headers = dict(default_headers)
        merged_headers.update(self.default_headers)
        if headers:
            merged_headers.update(headers)
        return merged_headers

    @staticmethod
    def _create_async_client(configuration: ApplicationConfiguration) -> httpx.AsyncClient:
        return httpx.AsyncClient(**BaseHTTPClient._build_client_kwargs(configuration))

    @staticmethod
    def _create_sync_client(configuration: ApplicationConfiguration) -> httpx.Client:
        return httpx.Client(**BaseHTTPClient._build_client_kwargs(configuration))

    async def _make_async_request(
        self,
        method: Callable,
        request_url: str,
        request_headers: dict[str, str],
        timeout: int,
        **kwargs,
    ) -> httpx.Response:
        request_kwargs = self._build_request_kwargs(request_headers, timeout, **kwargs)
        return await method(
            cast(httpx.AsyncClient, self.client),
            request_url,
            **request_kwargs,
        )

    def _build_request_kwargs(
        self, request_headers: dict[str, str], timeout: int, **kwargs
    ) -> dict[str, Any]:
        return {
            'headers': request_headers,
            'timeout': timeout,
            'auth': self.authentication,
            **kwargs,
        }

    def _next_request_loop_state(
        self,
        response: httpx.Response,
        *,
        request_url: str,
        retry_after_refresh: bool,
    ) -> tuple[bool, Any | None]:
        should_retry, result = self._handle_request_response(
            response,
            request_url=request_url,
            retry_after_refresh=retry_after_refresh,
        )
        if should_retry:
            return True, None
        return False, result

    async def _run_async_request_loop(
        self,
        method: Callable,
        request_url: str,
        headers: dict | None = None,
        timeout: int = 55,
        *,
        context_url: str | None = None,
        log_url: str | None = None,
        **kwargs,
    ) -> Any | None:
        retry_after_refresh = True
        context_url = context_url or request_url
        log_url = log_url or request_url
        while True:
            request_headers = self.set_headers(headers)

            try:
                response = await self._make_async_request(
                    method,
                    request_url,
                    request_headers,
                    timeout,
                    **kwargs,
                )
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as error:
                self._handle_transport_exception(error, log_url)

            retry_after_refresh, should_continue, result = self._handle_request_loop_response(
                response,
                request_url=context_url,
                retry_after_refresh=retry_after_refresh,
            )
            if should_continue:
                continue

            return result

    def _handle_request_loop_response(
        self,
        response: httpx.Response,
        *,
        request_url: str,
        retry_after_refresh: bool,
    ) -> tuple[bool, bool, Any | None]:
        should_retry, result = self._next_request_loop_state(
            response,
            request_url=request_url,
            retry_after_refresh=retry_after_refresh,
        )
        if should_retry:
            return False, True, result
        return retry_after_refresh, False, result

    def _run_sync_request_loop(
        self,
        method: Callable,
        request_url: str,
        headers: dict | None = None,
        timeout: int = 55,
        **kwargs,
    ) -> Any | None:
        retry_after_refresh = True
        while True:
            request_headers = self.set_headers(headers)

            try:
                response = method(
                    request_url,
                    **self._build_request_kwargs(request_headers, timeout, **kwargs),
                )
            except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError) as error:
                self._handle_transport_exception(error, request_url)

            retry_after_refresh, should_continue, result = self._handle_request_loop_response(
                response,
                request_url=request_url,
                retry_after_refresh=retry_after_refresh,
            )
            if should_continue:
                continue

            return result

    @staticmethod
    def _parse_error_response(response: httpx.Response) -> dict | None:
        del response
        raise NotImplementedError

    def _empty_response(self, response: httpx.Response) -> Any:
        del response
        raise NotImplementedError

    def _parse_response(self, response: httpx.Response) -> Any:
        del response
        raise NotImplementedError


class AsyncHTTPClient(BaseHTTPClient):
    """An async HTTP client for the Jira RETS API.

    This is useful for operations in endpoints that do not return JSON data, e.g. for downloading file attachments.
    """

    client: httpx.AsyncClient

    def _create_client(self, configuration: ApplicationConfiguration) -> httpx.AsyncClient:
        return self._create_async_client(configuration)

    def set_headers(self, headers: dict | None = None) -> dict[str, str]:
        return self._merge_headers(
            {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'},
            headers,
        )

    async def close_async_client(self):
        await self.client.aclose()

    def _async_request_urls(self, url: str) -> AsyncRequestUrls:
        del url
        return AsyncRequestUrls()

    async def _make_async_resource_request(
        self,
        method: Callable,
        url: str,
        headers: dict | None = None,
        timeout: int = 55,
        *,
        request_url: str | None = None,
        context_url: str | None = None,
        log_url: str | None = None,
        **kwargs,
    ) -> Any | None:
        request_url = request_url or self.get_resource_url(url)
        return await self._run_async_request_loop(
            method,
            request_url,
            headers,
            timeout,
            context_url=context_url or request_url,
            log_url=log_url or request_url,
            **kwargs,
        )

    async def make_request(
        self,
        method: Callable,
        url: str,
        headers: dict | None = None,
        timeout: int = 55,
        **kwargs,
    ) -> Any | None:
        request_urls = self._async_request_urls(url)
        return await self._make_async_resource_request(
            method,
            url,
            headers,
            timeout,
            request_url=request_urls.request_url,
            context_url=request_urls.context_url,
            log_url=request_urls.log_url,
            **kwargs,
        )

    @staticmethod
    def _parse_error_response(response: httpx.Response) -> dict | None:
        del response
        return None

    def _empty_response(self, response: httpx.Response) -> Any:
        del response
        return ''

    def _parse_response(self, response: httpx.Response) -> Any:
        return response.content


class JSONResponseMixin:
    @staticmethod
    def _parse_error_response(response: httpx.Response) -> dict | None:
        try:
            return response.json()
        except Exception:
            return None

    def _empty_response(self, response: httpx.Response) -> Any:
        del response
        return {}

    def _parse_response(self, response: httpx.Response) -> Any:
        return response.json()


class JiraClient(JSONResponseMixin, BaseHTTPClient):
    """A sync JSON client for the Jira REST API.

    This is useful for endpoints that support JSON but do not support async operations, e.g. uploading file attachments.
    """

    client: httpx.Client

    def _create_client(self, configuration: ApplicationConfiguration) -> httpx.Client:
        return self._create_sync_client(configuration)

    def set_headers(self, headers: dict | None = None) -> dict[str, str]:
        return self._merge_headers({'Accept': 'application/json'}, headers)

    def make_request(
        self,
        method: Callable,
        url: str,
        headers: dict | None = None,
        timeout: int = 55,
        **kwargs,
    ) -> dict | list | None:
        return cast(
            dict | list | None,
            self._run_sync_request_loop(
                method,
                self.get_resource_url(url),
                headers,
                timeout,
                **kwargs,
            ),
        )


class AsyncJiraClient(JSONResponseMixin, AsyncHTTPClient):
    """Async JSON client for the Jira REST API."""

    def set_headers(self, headers: dict | None = None) -> dict:
        return self._merge_headers(
            {'Content-Type': 'application/json', 'Accept': 'application/json'},
            headers,
        )

    def _async_request_urls(self, url: str) -> AsyncRequestUrls:
        full_url = self.get_resource_url(url)
        return AsyncRequestUrls(
            request_url=full_url,
            context_url=url,
            log_url=full_url,
        )

    async def get_label_suggestions(self, query: str = '') -> Any | None:
        """Get label suggestions from Jira.

        Args:
            query: Search query to filter label suggestions

        Returns:
            Dictionary with 'suggestions' key containing list of label strings,
            or None if request fails.
        """

        full_url = self.get_resource_url('jql/autocompletedata/suggestions')
        params = {
            'fieldName': 'labels',
            'fieldValue': query if query else '',
        }
        self.logger.info(
            'label_suggest request_start url=%s query=%r auth_mode=%s',
            full_url,
            query,
            'oauth2'
            if self.authentication is None and 'Authorization' in self.default_headers
            else 'basic',
        )

        try:
            response = await self.make_request(
                method=httpx.AsyncClient.get,
                url='jql/autocompletedata/suggestions',
                params=params,
            )
        except Exception as e:
            self.logger.exception(
                'label_suggest unexpected_error url=%s query=%r error=%s',
                full_url,
                query,
                e,
            )
            self.logger.error(f'Failed to get label suggestions: {e}')
            return None

        if not isinstance(response, dict):
            self.logger.warning(
                'label_suggest invalid_response url=%s query=%r type=%s',
                full_url,
                query,
                type(response).__name__,
            )
            return None

        results = response.get('results', [])
        suggestions = list(
            dict.fromkeys(
                item.get('value', '').strip() if isinstance(item, dict) else str(item).strip()
                for item in results
                if (
                    (isinstance(item, dict) and item.get('value'))
                    or (not isinstance(item, dict) and str(item).strip())
                )
            )
        )
        self.logger.info(
            'label_suggest parsed url=%s query=%r count=%s suggestions=%r',
            full_url,
            query,
            len(suggestions),
            suggestions,
        )
        return {'suggestions': suggestions}
