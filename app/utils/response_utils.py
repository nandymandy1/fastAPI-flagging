from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def error_response(
    code: str,
    message: str,
    status_code: int,
    details: list[dict[str, str]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
            }
        },
    )


def validation_field(location: tuple[object, ...]) -> str:
    field = ""
    parts = location[1:] if location and location[0] == "body" else location

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
        details.append(
            {
                "field": validation_field(tuple(error["loc"])),
                "code": code,
                "message": message,
            }
        )

    return details
