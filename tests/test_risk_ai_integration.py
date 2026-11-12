from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.api import risk as risk_api
from app.config.config import Settings, get_settings
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
    overrides = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def set_settings(model_id: str | None) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        aws_region="test-region",
        bedrock_model_id=model_id,
    )


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
    agent = Mock(return_value=result)
    return Mock(return_value=agent), agent


def test_default_request_preserves_the_deterministic_response(client, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert "ai_summary" not in response.json()
    assert "ai_status" not in response.json()
    factory.assert_not_called()


def test_explicitly_disabled_ai_does_not_create_an_agent(client, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=false", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert "ai_summary" not in response.json()
    assert "ai_status" not in response.json()
    factory.assert_not_called()


def test_missing_model_configuration_returns_deterministic_results(client, monkeypatch):
    set_settings(None)
    factory = Mock()
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()
    factory.assert_not_called()


def test_blank_model_configuration_returns_deterministic_results(client, monkeypatch):
    set_settings("   ")
    factory = Mock()
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()
    factory.assert_not_called()


def test_successful_ai_generation_requires_verified_tool_execution(client, monkeypatch):
    set_settings("configured-model")
    factory, agent = mock_agent_result()
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "generated"
    assert response.json()["ai_summary"] == "Verified HIGH_AMOUNT finding."
    factory.assert_called_once_with(
        analysis=ANY,
        region_name="test-region",
        model_id="configured-model",
    )
    agent.assert_called_once()


def test_missing_tool_execution_returns_unavailable(client, monkeypatch):
    set_settings("configured-model")
    factory, _ = mock_agent_result(success_count=0)
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_failed_tool_execution_returns_unavailable(client, monkeypatch):
    set_settings("configured-model")
    factory, _ = mock_agent_result(error_count=1)
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_invalid_stop_reason_returns_unavailable(client, monkeypatch):
    set_settings("configured-model")
    factory, _ = mock_agent_result(stop_reason="max_tokens")
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_empty_ai_response_returns_unavailable(client, monkeypatch):
    set_settings("configured-model")
    factory, _ = mock_agent_result(text="   ")
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()


def test_agent_exception_returns_unavailable_without_details(client, monkeypatch):
    set_settings("configured-model")
    factory = Mock(side_effect=RuntimeError("AWS credentials are invalid"))
    monkeypatch.setattr(risk_api, "create_risk_agent", factory)

    response = client.post("/api/v1/risk/analyze?include_ai=true", json=PAYLOAD)

    assert response.status_code == 200
    assert_deterministic_response(response.json())
    assert response.json()["ai_status"] == "unavailable"
    assert "ai_summary" not in response.json()
    assert "AWS credentials are invalid" not in response.text
