import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """A controlled failure that may be safely reported to API clients."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class LLMConfigurationError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("llm_configuration_error", message, status_code=503)


class LLMTimeoutError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "llm_timeout",
            "The operator notes could not be interpreted before the provider timeout.",
            status_code=504,
        )


class LLMProviderError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "llm_provider_error",
            "The operator-note interpretation provider is temporarily unavailable.",
            status_code=502,
        )


class LLMInvalidOutputError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "llm_invalid_output",
            "The operator-note interpretation provider returned an invalid response.",
            status_code=502,
        )


class OptimizationError_(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("optimization_error", message, status_code=422)


class ReplayViolationError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("replay_violation", message, status_code=422)


def _error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(
                "request_validation_error",
                "The request body is invalid.",
                details,
            ),
        )

    @app.exception_handler(ApplicationError)
    async def application_error_handler(_request: Request, exc: ApplicationError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("http_error", message),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_body(
                "internal_error",
                "The request could not be completed due to an internal error.",
            ),
        )
