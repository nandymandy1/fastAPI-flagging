import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

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
    details: object | None = None,
) -> JSONResponse:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = jsonable_encoder(details)
    return JSONResponse(status_code=status_code, content={"error": error})


@app.exception_handler(AppError)
def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.code, exc.message, exc.status_code, exc.details)


@app.exception_handler(RequestValidationError)
def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(
        "VALIDATION_ERROR",
        "Request validation failed",
        422,
        exc.errors(),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled application error", exc_info=exc)
    return error_response("INTERNAL_SERVER_ERROR", "Internal server error", 500)


app.include_router(risk_router, prefix=settings.api_prefix)
app.include_router(health_router, prefix=settings.api_prefix)
