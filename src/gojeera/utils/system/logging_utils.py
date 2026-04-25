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
        error_messages = remote_payload.get('errorMessages', [])
        message = error_messages[0] if error_messages else str(exception)
        return ExceptionLogDetails(message=message, extra=details.to_log_extra())

    raw_extra: dict[str, Any] = getattr(exception, 'extra', {}) or {}
    error_messages = raw_extra.get('errorMessages', [])
    message = error_messages[0] if error_messages else str(exception)
    extra = {'error_context': raw_extra} if raw_extra else {}
    return ExceptionLogDetails(message=message, extra=extra)


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
