from fastapi.testclient import TestClient
from app.main import app
from app.config.config import get_settings

client = TestClient(app)


def test_health():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": get_settings().app_name,
    }
