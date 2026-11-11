from fastapi import FastAPI

app = FastAPI(
    title="Risk Monitor Agent",
    version="0.1.0",
    description="Transaction risk monitoring API",
)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "risk-monitor"
    }
