from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class APIErrorDetails:
    context: dict[str, Any] = field(default_factory=dict)
    remote_payload: dict[str, Any] | None = None

    def to_log_extra(self) -> dict[str, Any]:
        extra = dict(self.context)
        if self.remote_payload:
            extra['error_context'] = self.remote_payload
        return extra


class APIException(Exception):
    """General API Exception, whenever a specific reason can't be determined."""

    details: APIErrorDetails = APIErrorDetails()
    extra: dict[str, Any] = {}

    def __init__(self, *args, **kwargs):
        context = kwargs.pop('context', None)
        remote_payload = kwargs.pop('remote_payload', None)
        legacy_extra = kwargs.pop('extra', None)
        if context is None and remote_payload is None and isinstance(legacy_extra, dict):
            context = {}
            remote_payload = legacy_extra
        self.details = APIErrorDetails(
            context=context or {},
            remote_payload=remote_payload if isinstance(remote_payload, dict) else None,
        )
        self.extra = self.details.to_log_extra()
        super().__init__(*args)


class ServiceUnavailableException(APIException):
    pass


class ServiceInvalidRequestException(APIException):
    pass


class ServiceInvalidResponseException(APIException):
    pass


class UpdateWorkItemException(APIException):
    pass


class ValidationError(APIException):
    pass


class ResourceNotFoundException(APIException):
    pass


class AuthorizationException(APIException):
    pass


class PermissionException(APIException):
    pass


class FileUploadException(APIException):
    pass
