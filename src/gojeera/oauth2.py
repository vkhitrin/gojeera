from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
import secrets
from threading import Thread
from urllib.parse import parse_qs, urlencode, urlparse
import webbrowser

import httpx

from gojeera.auth_profiles import (
    ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    ATLASSIAN_OAUTH2_REDIRECT_URI,
    ATLASSIAN_OAUTH2_TOKEN_URL,
)

ATLASSIAN_OAUTH2_AUDIENCE = 'api.atlassian.com'
ATLASSIAN_ACCESSIBLE_RESOURCES_URL = 'https://api.atlassian.com/oauth/token/accessible-resources'


@dataclass
class OAuth2TokenResponse:
    access_token: str
    refresh_token: str | None = None
    token_type: str | None = None
    expires_in: int | None = None
    scope: str | None = None


@dataclass
class AtlassianAccessibleResource:
    id: str
    name: str
    url: str
    scopes: list[str] | None = None
    avatar_url: str | None = None


@dataclass
class OAuth2AuthorizationResult:
    state: str
    code: str


EXTENDED_OAUTH2_SCOPES = [
    'read:jira-user',
    'read:jira-work',
    'write:jira-work',
    'manage:jira-data-provider',
    'read:servicedesk-request',
    'read:servicemanagement-insight-objects',
    'offline_access',
    'read:me',
    'read:account',
]


def build_atlassian_authorization_url(
    *,
    client_id: str,
    scopes: list[str],
    state: str,
    redirect_uri: str = ATLASSIAN_OAUTH2_REDIRECT_URI,
    authorization_url: str = ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    audience: str = ATLASSIAN_OAUTH2_AUDIENCE,
    prompt: str = 'consent',
) -> str:
    query = urlencode(
        {
            'audience': audience,
            'client_id': client_id,
            'scope': ' '.join(scopes),
            'redirect_uri': redirect_uri,
            'state': state,
            'response_type': 'code',
            'prompt': prompt,
        }
    )
    return f'{authorization_url}?{query}'


def exchange_atlassian_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str = ATLASSIAN_OAUTH2_REDIRECT_URI,
    token_url: str = ATLASSIAN_OAUTH2_TOKEN_URL,
    timeout: float = 10.0,
) -> OAuth2TokenResponse:
    return _post_token_request(
        token_url=token_url,
        payload={
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri,
        },
        timeout=timeout,
    )


def refresh_atlassian_oauth2_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    token_url: str = ATLASSIAN_OAUTH2_TOKEN_URL,
    timeout: float = 10.0,
) -> OAuth2TokenResponse:
    return _post_token_request(
        token_url=token_url,
        payload={
            'grant_type': 'refresh_token',
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
        },
        timeout=timeout,
    )


def get_atlassian_accessible_resources(
    *,
    access_token: str,
    accessible_resources_url: str = ATLASSIAN_ACCESSIBLE_RESOURCES_URL,
    timeout: float = 10.0,
) -> list[AtlassianAccessibleResource]:
    response = httpx.get(
        accessible_resources_url,
        headers={
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}',
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError('Atlassian accessible resources response must be a list.')

    resources: list[AtlassianAccessibleResource] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        resources.append(
            AtlassianAccessibleResource(
                id=str(item.get('id') or ''),
                name=str(item.get('name') or ''),
                url=str(item.get('url') or ''),
                scopes=item.get('scopes') if isinstance(item.get('scopes'), list) else None,
                avatar_url=str(item.get('avatarUrl')) if item.get('avatarUrl') else None,
            )
        )
    return resources


def run_atlassian_oauth2_authorization_flow(
    *,
    client_id: str,
    scopes: list[str],
    client_secret: str,
    redirect_uri: str = ATLASSIAN_OAUTH2_REDIRECT_URI,
    authorization_url: str = ATLASSIAN_OAUTH2_AUTHORIZATION_URL,
    token_url: str = ATLASSIAN_OAUTH2_TOKEN_URL,
    timeout: float = 180.0,
) -> OAuth2TokenResponse:
    state = secrets.token_urlsafe(24)
    auth_url = build_atlassian_authorization_url(
        client_id=client_id,
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
        authorization_url=authorization_url,
    )
    callback = wait_for_atlassian_oauth2_callback(
        authorization_url=auth_url,
        expected_state=state,
        redirect_uri=redirect_uri,
        timeout=timeout,
    )
    return exchange_atlassian_authorization_code(
        client_id=client_id,
        client_secret=client_secret,
        code=callback.code,
        redirect_uri=redirect_uri,
        token_url=token_url,
    )


def wait_for_atlassian_oauth2_callback(
    *,
    authorization_url: str,
    expected_state: str,
    redirect_uri: str = ATLASSIAN_OAUTH2_REDIRECT_URI,
    timeout: float = 180.0,
) -> OAuth2AuthorizationResult:
    parsed_redirect_uri = urlparse(redirect_uri)
    hostname = parsed_redirect_uri.hostname or '127.0.0.1'
    port = parsed_redirect_uri.port
    path = parsed_redirect_uri.path or '/'
    if port is None:
        raise ValueError('OAuth2 redirect URI must include an explicit port.')

    result_queue: Queue[tuple[str, str]] = Queue()
    error_queue: Queue[str] = Queue()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed_request = urlparse(self.path)
            if parsed_request.path != path:
                self.send_response(404)
                self.end_headers()
                return

            query = parse_qs(parsed_request.query)
            error = query.get('error', [None])[0]
            code = query.get('code', [None])[0]
            state = query.get('state', [None])[0]

            if error:
                error_queue.put(str(error))
                self._write_response('Authentication failed. You can close this window.')
                return

            if not code or not state:
                error_queue.put('OAuth2 callback did not include both code and state.')
                self._write_response('Authentication failed. You can close this window.')
                return

            result_queue.put((str(code), str(state)))
            self._write_response('Authentication completed. You can close this window.')

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _write_response(self, body: str) -> None:
            response = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer((hostname, port), CallbackHandler)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        webbrowser.open(authorization_url, new=1, autoraise=True)

        while True:
            try:
                code, returned_state = result_queue.get(timeout=timeout)
                break
            except Empty:
                if not error_queue.empty():
                    break
                raise TimeoutError('Timed out waiting for the Atlassian OAuth2 callback.') from None

        if not error_queue.empty():
            raise RuntimeError(error_queue.get())
        if returned_state != expected_state:
            raise RuntimeError('OAuth2 state mismatch in callback.')
        return OAuth2AuthorizationResult(state=returned_state, code=code)
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)


def _post_token_request(
    *, token_url: str, payload: dict[str, str], timeout: float
) -> OAuth2TokenResponse:
    response = httpx.post(
        token_url,
        headers={
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        },
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    response_payload = response.json()
    if not isinstance(response_payload, dict):
        raise ValueError('Atlassian token response must be a JSON object.')

    return OAuth2TokenResponse(
        access_token=str(response_payload.get('access_token') or ''),
        refresh_token=(
            str(response_payload.get('refresh_token'))
            if response_payload.get('refresh_token')
            else None
        ),
        token_type=(
            str(response_payload.get('token_type')) if response_payload.get('token_type') else None
        ),
        expires_in=(
            response_payload.get('expires_in')
            if isinstance(response_payload.get('expires_in'), int)
            else None
        ),
        scope=str(response_payload.get('scope')) if response_payload.get('scope') else None,
    )
