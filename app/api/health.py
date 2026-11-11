from fastapi import APIRouter

from app.config import get_settings

settings = get_settings()

router = APIRouter(prefix="/health", tags=["App Health"])


@router.get("/")
async def health():
    return {"status": "ok", "service": settings.app_name}
