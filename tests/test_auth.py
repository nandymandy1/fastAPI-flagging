import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config.config import Settings, get_settings
from app.dependencies import (
    get_risk_agent_builder,
    get_risk_analysis_service,
    require_api_key,
)
from app.main import app


@pytest.fixture
def auth_app():
    test_app = FastAPI()

    @test_app.get("/protected", dependencies=[Depends(require_api_key)])
    def protected() -> dict[str, str]:
        return {"status": "ok"}

    return test_app


def client_with_key(auth_app: FastAPI, api_key: str | None) -> TestClient:
    auth_app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        api_key=api_key,
    )
    return TestClient(auth_app)


@pytest.fixture
def risk_client():
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides)


def configure_risk_api_key(api_key: str | None) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        api_key=api_key,
    )


def risk_payload() -> dict:
    return {
        "transactions": [
            {
                "transaction_id": "auth_test_001",
                "customer_id": "customer_001",
                "amount": "100.00",
                "currency": "USD",
                "merchant": "Test Merchant",
                "timestamp": "2026-11-11T10:00:00Z",
            }
        ]
    }


def test_valid_api_key_is_accepted(auth_app):
    client = client_with_key(auth_app, "test-secret")

    response = client.get("/protected", headers={"X-API-Key": "test-secret"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("headers", "api_key", "status_code"),
    [
        ({}, "test-secret", 401),
        ({"X-API-Key": "wrong-secret"}, "test-secret", 401),
        ({"X-API-Key": "test-secret"}, None, 503),
        ({"X-API-Key": "test-secret"}, "   ", 503),
    ],
)
def test_invalid_or_missing_api_key_is_rejected(
    auth_app, headers, api_key, status_code
):
    client = client_with_key(auth_app, api_key)

    response = client.get("/protected", headers=headers)

    assert response.status_code == status_code


def test_api_keys_are_not_exposed_in_errors(auth_app):
    configured_key = "configured-secret"
    supplied_key = "supplied-secret"
    client = client_with_key(auth_app, configured_key)

    response = client.get("/protected", headers={"X-API-Key": supplied_key})

    assert response.status_code == 401
    assert configured_key not in response.text
    assert supplied_key not in response.text


def test_valid_api_key_protects_the_risk_route(risk_client):
    configure_risk_api_key("configured-secret")

    response = risk_client.post(
        "/api/v1/risk/analyze",
        json=risk_payload(),
        headers={"X-API-Key": "configured-secret"},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("api_key", "headers", "status_code", "code"),
    [
        ("configured-secret", {}, 401, "UNAUTHORIZED"),
        (
            "configured-secret",
            {"X-API-Key": "wrong-secret"},
            401,
            "UNAUTHORIZED",
        ),
        (None, {"X-API-Key": "configured-secret"}, 503, "SERVICE_UNAVAILABLE"),
        ("   ", {"X-API-Key": "configured-secret"}, 503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_risk_route_rejects_invalid_authentication(
    risk_client, api_key, headers, status_code, code
):
    configure_risk_api_key(api_key)

    response = risk_client.post(
        "/api/v1/risk/analyze", json=risk_payload(), headers=headers
    )

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_rejected_authentication_does_not_execute_risk_or_ai(risk_client):
    def fail_risk_analysis():
        raise AssertionError("Risk analysis should not execute")

    def fail_agent_builder():
        raise AssertionError("AI agent should not be created")

    configure_risk_api_key("configured-secret")
    app.dependency_overrides[get_risk_analysis_service] = fail_risk_analysis
    app.dependency_overrides[get_risk_agent_builder] = fail_agent_builder

    response = risk_client.post("/api/v1/risk/analyze", json=risk_payload())

    assert response.status_code == 401


def test_health_endpoint_remains_public(risk_client):
    response = risk_client.get("/api/v1/health")

    assert response.status_code == 200


def test_risk_authentication_errors_do_not_expose_keys(risk_client):
    configured_key = "configured-secret"
    supplied_key = "supplied-secret"
    configure_risk_api_key(configured_key)

    response = risk_client.post(
        "/api/v1/risk/analyze",
        json=risk_payload(),
        headers={"X-API-Key": supplied_key},
    )

    assert response.status_code == 401
    assert configured_key not in response.text
    assert supplied_key not in response.text
