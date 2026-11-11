from fastapi import FastAPI
from app.config import get_settings
from app.api import health_router, risk_router

settings = get_settings()

app = FastAPI(
    version="0.1.0",
    debug=settings.debug,
    title=settings.app_name,
)

app.include_router(
    risk_router,
    prefix=settings.api_prefix,
)

app.include_router(
    health_router,
    prefix=settings.api_prefix,
)
