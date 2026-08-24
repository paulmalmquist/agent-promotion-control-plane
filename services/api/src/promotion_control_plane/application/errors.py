from typing import Any


class ApplicationError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.extensions = extensions or {}


def not_found(resource: str) -> ApplicationError:
    return ApplicationError(
        404, "RESOURCE_NOT_FOUND", "Resource not found", f"{resource} does not exist."
    )


def bad_request(code: str, detail: str, **extensions: Any) -> ApplicationError:
    return ApplicationError(400, code, "Request is invalid", detail, extensions)


def conflict(code: str, detail: str, **extensions: Any) -> ApplicationError:
    return ApplicationError(409, code, "Request conflicts with current state", detail, extensions)


def unprocessable(code: str, detail: str, **extensions: Any) -> ApplicationError:
    return ApplicationError(422, code, "Request cannot be completed", detail, extensions)
