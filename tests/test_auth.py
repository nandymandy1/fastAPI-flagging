from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config.config import Settings, get_settings
from app.dependencies import (
    get_idempotency_store,
    get_risk_analysis_service,
    require_api_key,
)
from app.main import app


def payload() -> dict:
    return {
        "transactions": [
            {
                "transaction_id": "auth_001",
                "customer_id": "customer_001",
                "amount": "100.00",
                "currency": "USD",
                "merchant": "Merchant",
                "timestamp": "2026-11-11T10:00:00Z",
            }
        ]
    }


def test_api_key_dependency_accepts_only_configured_key():
    test_app = FastAPI()
    test_app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, api_key="configured-secret"
    )

    @test_app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(test_app)
    assert (
        client.get("/protected", headers={"X-API-Key": "configured-secret"}).status_code
        == 200
    )
    rejected = client.get("/protected", headers={"X-API-Key": "wrong-secret"})
    assert rejected.status_code == 401
    assert "configured-secret" not in rejected.text


@pytest.mark.parametrize("api_key", [None, "   "])
def test_missing_configuration_fails_closed(api_key):
    test_app = FastAPI()
    test_app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, api_key=api_key
    )

    @test_app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected() -> dict[str, str]:
        return {"status": "ok"}

    assert (
        TestClient(test_app).get("/protected", headers={"X-API-Key": "any"}).status_code
        == 503
    )


@pytest.fixture
def risk_client():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, api_key="configured-secret"
    )
    store = Mock()
    store.get.return_value = None
    store.reserve.return_value = {"reservation_id": "reservation"}
    app.dependency_overrides[get_idempotency_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def test_risk_route_requires_authentication_before_analysis(risk_client):
    app.dependency_overrides[get_risk_analysis_service] = lambda: (_ for _ in ()).throw(
        AssertionError("analysis must not run")
    )

    response = risk_client.post(
        "/api/v1/risk/analyze",
        json=payload(),
        headers={"Idempotency-Key": "test-key"},
    )

    assert response.status_code == 401


def test_authenticated_risk_route_and_public_health(risk_client):
    response = risk_client.post(
        "/api/v1/risk/analyze",
        json=payload(),
        headers={"X-API-Key": "configured-secret", "Idempotency-Key": "test-key"},
    )

    assert response.status_code == 200
    assert risk_client.get("/api/v1/health").status_code == 200
