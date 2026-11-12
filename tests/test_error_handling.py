import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import (
    get_idempotency_store,
    get_risk_analysis_service,
    require_api_key,
)
from app.errors import AppError
from app.main import app


@pytest.fixture(autouse=True)
def overrides():
    store = Mock()
    store.get.return_value = None
    store.reserve.return_value = {"reservation_id": "test-reservation"}
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_idempotency_store] = lambda: store
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)


def valid_payload() -> dict:
    return {
        "transactions": [
            {
                "transaction_id": "txn_001",
                "customer_id": "cust_001",
                "amount": "100.00",
                "currency": "USD",
                "merchant": "Merchant",
                "timestamp": "2026-11-11T10:00:00Z",
            }
        ]
    }


def test_validation_errors_are_structured_and_redact_payload_data():
    payload = valid_payload()
    payload["transactions"].append({**payload["transactions"][0]})
    payload["transactions"][0]["transaction_id"] = "sensitive-id"
    payload["transactions"][1]["transaction_id"] = "sensitive-id"

    response = TestClient(app).post("/api/v1/risk/analyze", json=payload)
    error = response.json()["error"]

    assert response.status_code == 422
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == [
        {
            "field": "transactions",
            "code": "DUPLICATE_TRANSACTION_ID",
            "message": "Transaction IDs must be unique",
        }
    ]
    assert "sensitive-id" not in json.dumps(response.json())


@pytest.mark.parametrize(
    ("payload", "field", "code"),
    [
        ({}, "transactions", "MISSING"),
        (
            {"transactions": [{"amount": "not-a-number"}]},
            "transactions[0].amount",
            "DECIMAL_PARSING",
        ),
        (
            {"transactions": [{"currency": "JPY"}]},
            "transactions[0].currency",
            "UNSUPPORTED_CURRENCY",
        ),
    ],
)
def test_validation_details_use_readable_paths_and_codes(payload, field, code):
    response = TestClient(app).post("/api/v1/risk/analyze", json=payload)

    assert response.status_code == 422
    assert any(
        detail["field"] == field and detail["code"] == code
        for detail in response.json()["error"]["details"]
    )


def test_multiple_validation_errors_remain_separate():
    payload = valid_payload()
    payload["transactions"][0].update(amount="-1", currency="JPY")

    response = TestClient(app).post("/api/v1/risk/analyze", json=payload)

    assert {
        (detail["field"], detail["code"])
        for detail in response.json()["error"]["details"]
    } == {
        ("transactions[0].amount", "GREATER_THAN"),
        ("transactions[0].currency", "UNSUPPORTED_CURRENCY"),
    }


def test_application_and_internal_errors_use_safe_contracts():
    app.dependency_overrides[get_risk_analysis_service] = lambda: (_ for _ in ()).throw(
        AppError("UPSTREAM_UNAVAILABLE", "Risk service is unavailable", 503)
    )
    response = TestClient(app).post("/api/v1/risk/analyze", json=valid_payload())

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"

    app.dependency_overrides[get_risk_analysis_service] = lambda: (_ for _ in ()).throw(
        RuntimeError("database password leaked")
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/risk/analyze", json=valid_payload()
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "database password leaked" not in response.text


@pytest.mark.parametrize(
    ("method", "path", "status_code", "code"),
    [
        ("get", "/api/v1/missing", 404, "NOT_FOUND"),
        ("post", "/api/v1/health/", 405, "METHOD_NOT_ALLOWED"),
    ],
)
def test_http_errors_use_the_standard_contract(method, path, status_code, code):
    response = getattr(TestClient(app), method)(path)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_http_error_headers_are_preserved():
    response = TestClient(app).post("/api/v1/health/")
    assert response.headers["allow"] == "GET"

    app.dependency_overrides[get_risk_analysis_service] = lambda: (_ for _ in ()).throw(
        HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    )
    response = TestClient(app).post("/api/v1/risk/analyze", json=valid_payload())
    assert response.headers["www-authenticate"] == "Bearer"
