"""Stable, value-free HTTP error responses."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mandateguard.api.schemas import ErrorDetail, ErrorResponse


class ApiError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        fields: tuple[str, ...] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = ErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            fields=fields,
        )
        self.headers = headers


def _response(error: ApiError) -> JSONResponse:
    body = ErrorResponse(error=error.detail)
    return JSONResponse(
        status_code=error.status_code,
        content=body.model_dump(mode="json", exclude_none=True),
        headers=error.headers,
    )


def _safe_locations(error: RequestValidationError) -> tuple[str, ...]:
    locations = {
        ".".join(
            part if isinstance(part, str) else "index" if type(part) is int else "unsupported"
            for part in item["loc"][:16]
        )
        or "root"
        for item in error.errors()
    }
    return tuple(sorted(locations))


def install_error_handlers(application: FastAPI) -> None:
    async def api_error_handler(request: Request, exception: Exception) -> JSONResponse:
        del request
        if not isinstance(exception, ApiError):
            raise exception
        error = exception
        return _response(error)

    async def validation_error_handler(request: Request, exception: Exception) -> JSONResponse:
        del request
        if not isinstance(exception, RequestValidationError):
            raise exception
        error = exception
        is_json_error = any(item["type"] == "json_invalid" for item in error.errors())
        api_error = (
            ApiError(400, "invalid_json", "Request body must be valid JSON.")
            if is_json_error
            else ApiError(
                422,
                "invalid_request",
                "Request does not match the required transport contract.",
                fields=_safe_locations(error),
            )
        )
        return _response(api_error)

    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
