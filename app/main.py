import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import health_router, risk_router
from app.config import get_settings
from app.errors import AppError

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    version="0.1.0",
    debug=settings.debug,
    title=settings.app_name,
)


def error_response(
    code: str,
    message: str,
    status_code: int,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


@app.exception_handler(AppError)
def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    details = (
        [
            {key: detail[key] for key in ("field", "code", "message")}
            for detail in exc.details
            if isinstance(detail, dict)
            and all(
                isinstance(detail.get(key), str) for key in ("field", "code", "message")
            )
        ]
        if isinstance(exc.details, list)
        else []
    )
    return error_response(exc.code, exc.message, exc.status_code, details)


def validation_field(location: tuple[object, ...]) -> str:
    parts = location[1:] if location and location[0] == "body" else location
    field = ""
    for part in parts:
        if isinstance(part, int):
            field += f"[{part}]"
        else:
            field += f".{part}" if field else str(part)
    return field or "request"


def validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details = []
    for error in exc.errors():
        error_type = str(error["type"])
        code = error_type.upper()
        message = str(error["msg"])
        if error_type.isupper() and code != "UNSUPPORTED_CURRENCY":
            message = "Invalid value"
        details.append(
            {
                "field": validation_field(tuple(error["loc"])),
                "code": code,
                "message": message,
            }
        )
    return details


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        "VALIDATION_ERROR",
        "Request validation failed",
        422,
        validation_details(exc),
    )


@app.exception_handler(StarletteHTTPException)
def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    try:
        status = HTTPStatus(exc.status_code)
        code = status.name
        message = status.phrase
    except ValueError:
        code = f"HTTP_{exc.status_code}"
        message = "HTTP error"
    return error_response(code, message, exc.status_code)


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error", exc_info=exc)
    return error_response("INTERNAL_SERVER_ERROR", "Internal server error", 500)


app.include_router(risk_router, prefix=settings.api_prefix)
app.include_router(health_router, prefix=settings.api_prefix)
