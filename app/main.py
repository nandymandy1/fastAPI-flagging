import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import agentcore_router, health_router, risk_router
from .config import get_settings
from .errors import AppError
from .utils import error_response, validation_details

settings = get_settings()
logger = logging.getLogger(__name__)

app = FastAPI(
    version="0.1.0",
    debug=False,
    title=settings.app_name,
)


@app.get("/ping")
async def agentcore_ping() -> dict[str, str]:
    return {"status": "Healthy"}


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
    return error_response(code, message, exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error", exc_info=exc)
    return error_response("INTERNAL_SERVER_ERROR", "Internal server error", 500)


app.include_router(risk_router, prefix=settings.api_prefix)
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(agentcore_router)
