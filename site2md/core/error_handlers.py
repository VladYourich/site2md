from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from site2md.core.logging import get_logger

logger = get_logger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = exc.errors()
        messages = []
        for err in detail:
            field = ".".join(str(loc) for loc in err["loc"])
            messages.append(f"{field}: {err['msg']}")
        return JSONResponse(
            status_code=422,
            content={
                "type": "validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": "; ".join(messages),
                "instance": str(request.url.path),
            },
            headers={"Content-Type": "application/problem+json"},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        msg = str(exc)
        if "SSRF" in msg.upper() or "blocked" in msg.lower():
            return JSONResponse(
                status_code=422,
                content={
                    "type": "invalid-url",
                    "title": "Validation Error",
                    "status": 422,
                    "detail": msg,
                    "instance": str(request.url.path),
                },
                headers={"Content-Type": "application/problem+json"},
            )
        return JSONResponse(
            status_code=422,
            content={
                "type": "validation-error",
                "title": "Validation Error",
                "status": 422,
                "detail": msg,
                "instance": str(request.url.path),
            },
            headers={"Content-Type": "application/problem+json"},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", extra={"error": str(exc), "path": str(request.url.path)})
        return JSONResponse(
            status_code=500,
            content={
                "type": "internal-error",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred",
                "instance": str(request.url.path),
            },
            headers={"Content-Type": "application/problem+json"},
        )
