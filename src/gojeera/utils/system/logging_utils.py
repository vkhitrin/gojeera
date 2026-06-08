from __future__ import annotations

import logging
from typing import Any

from gojeera.internal.models.exceptions import APIErrorDetails


class ExceptionLogDetails(dict[str, Any]):
    def __init__(self, message: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(message=message, extra=extra or {})

    @property
    def message(self) -> str:
        return str(self['message'])

    @property
    def extra(self) -> dict[str, Any]:
        return self['extra']


def extract_exception_details(exception: Exception) -> ExceptionLogDetails:
    details = getattr(exception, 'details', None)
    if isinstance(details, APIErrorDetails):
        remote_payload = details.remote_payload or {}
        return ExceptionLogDetails(
            message=_extract_error_message(remote_payload, exception),
            extra=details.to_log_extra(),
        )

    raw_extra: dict[str, Any] = getattr(exception, 'extra', {}) or {}
    extra = {'error_context': raw_extra} if raw_extra else {}
    return ExceptionLogDetails(
        message=_extract_error_message(raw_extra, exception),
        extra=extra,
    )


def _extract_error_message(payload: dict[str, Any], exception: Exception) -> str:
    error_messages = payload.get('errorMessages', [])
    field_errors = payload.get('errors', {})
    if error_messages:
        return str(error_messages[0])
    if isinstance(field_errors, dict) and field_errors:
        return '; '.join(f'{field}: {error}' for field, error in field_errors.items())
    return str(exception)


def build_log_extra(
    base: dict[str, Any] | None = None, details: ExceptionLogDetails | None = None
) -> dict[str, Any]:
    reserved_keys = set(logging.makeLogRecord({}).__dict__)
    reserved_keys.update({'message', 'asctime'})

    extra = {key: value for key, value in dict(base or {}).items() if key not in reserved_keys}
    if details is not None:
        extra.update(
            {key: value for key, value in details.extra.items() if key not in reserved_keys}
        )
    return extra
