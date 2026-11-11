import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_risk_analysis_service
from app.errors import AppError
from app.main import app


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def test_validation_errors_use_the_standard_response_shape():
    client = TestClient(app)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["message"] == "Request validation failed"
    assert response.json()["error"]["details"]


def test_app_errors_use_the_standard_response_shape():
    def raise_app_error():
        raise AppError("UPSTREAM_UNAVAILABLE", "Risk service is unavailable", 503)

    app.dependency_overrides[get_risk_analysis_service] = raise_app_error
    client = TestClient(app)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "UPSTREAM_UNAVAILABLE",
            "message": "Risk service is unavailable",
        }
    }


def test_unexpected_errors_do_not_expose_internal_details():
    def raise_unexpected_error():
        raise RuntimeError("database password leaked")

    app.dependency_overrides[get_risk_analysis_service] = raise_unexpected_error
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/risk/analyze", json={"transactions": []})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Internal server error",
        }
    }


def test_risk_service_can_be_overridden():
    class StubRiskAnalysisService:
        def analyze(self, payload):
            assert len(payload.transactions) == 1
            return {
                "status": "completed",
                "summary": {
                    "total_findings": 0,
                    "total_transactions": 1,
                    "flagged_transactions": 0,
                },
                "findings": [],
            }

    app.dependency_overrides[get_risk_analysis_service] = StubRiskAnalysisService
    client = TestClient(app)

    response = client.post(
        "/api/v1/risk/analyze",
        json={
            "transactions": [
                {
                    "transaction_id": "txn_001",
                    "customer_id": "cust_101",
                    "amount": "150.00",
                    "currency": "USD",
                    "merchant": "Amazon",
                    "timestamp": "2026-11-11T10:00:00Z",
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["total_transactions"] == 1
