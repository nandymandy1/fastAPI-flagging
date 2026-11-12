from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.config.config import Settings, get_settings
from app.dependencies import (
    get_idempotency_store,
    get_risk_agent_builder,
    require_api_key,
)
from app.main import app

PAYLOAD = {
    "transactions": [
        {
            "transaction_id": "txn_ai_001",
            "customer_id": "cust_ai_001",
            "amount": "25000.00",
            "currency": "USD",
            "merchant": "Test Merchant",
            "timestamp": "2026-11-11T10:00:00Z",
        }
    ]
}


@pytest.fixture(autouse=True)
def restore_dependency_overrides():
    store = Mock()
    store.get.return_value = None
    store.reserve.return_value = {"reservation_id": "test-reservation"}
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[get_idempotency_store] = lambda: store
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides)


@pytest.fixture
def client():
    with TestClient(app, headers={"Idempotency-Key": "test-key"}) as test_client:
        yield test_client


def set_settings(model_id: str | None) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        aws_region="test-region",
        bedrock_model_id=model_id,
    )


def set_agent_builder(builder: Mock | None) -> None:
    app.dependency_overrides[get_risk_agent_builder] = lambda: builder


def assert_deterministic_response(data: dict) -> None:
    assert data["summary"] == {
        "total_findings": 1,
        "total_transactions": 1,
        "flagged_transactions": 1,
    }
    assert data["findings"][0]["transaction_id"] == "txn_ai_001"
    assert data["findings"][0]["rule_code"] == "HIGH_AMOUNT"


def mock_agent_result(
    text: str = "Verified HIGH_AMOUNT finding.",
    stop_reason: str = "end_turn",
    success_count: int = 1,
    error_count: int = 0,
) -> tuple[Mock, Mock]:
    result = MagicMock()
    result.stop_reason = stop_reason
    result.metrics.tool_metrics = {
        "get_verified_risk_findings": SimpleNamespace(
            success_count=success_count,
            error_count=error_count,
        )
    }
    result.__str__.return_value = text
    agent = Mock()
    agent.invoke_async = AsyncMock(return_value=result)
    return Mock(return_value=agent), agent


def test_default_request_preserves_the_deterministic_response(client):
    builder = Mock()
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert "ai_summary" not in response.json()
    assert "ai_status" not in response.json()
    builder.assert_not_called()


def test_explicitly_disabled_ai_does_not_create_an_agent(client):
    builder = Mock()
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=false", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert "ai_summary" not in response.json()
    assert "ai_status" not in response.json()
    builder.assert_not_called()


def test_missing_model_configuration_returns_deterministic_results(client):
    set_settings(None)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_blank_model_configuration_returns_deterministic_results(client):
    set_settings("   ")

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_successful_ai_generation_requires_verified_tool_execution(client):
    set_settings("configured-model")
    builder, agent = mock_agent_result()
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "generated"
    assert response.json()["ai_summary"] == "Verified HIGH_AMOUNT finding."
    builder.assert_called_once()
    agent.invoke_async.assert_awaited_once()


def test_missing_tool_execution_returns_unavailable(client):
    set_settings("configured-model")
    builder, _ = mock_agent_result(success_count=0)
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_failed_tool_execution_returns_unavailable(client):
    set_settings("configured-model")
    builder, _ = mock_agent_result(error_count=1)
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_invalid_stop_reason_returns_unavailable(client):
    set_settings("configured-model")
    builder, _ = mock_agent_result(stop_reason="max_tokens")
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_empty_ai_response_returns_unavailable(client):
    set_settings("configured-model")
    builder, _ = mock_agent_result(text="   ")
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_agent_exception_returns_unavailable_without_details(client):
    set_settings("configured-model")
    builder = Mock(side_effect=RuntimeError("AWS credentials are invalid"))
    set_agent_builder(builder)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()
    assert "AWS credentials are invalid" not in response.text
