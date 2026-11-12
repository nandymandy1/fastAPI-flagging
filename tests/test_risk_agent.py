from unittest.mock import Mock

import pytest

from app.schemas.risk import (
    RiskAnalysisResponseDto,
    RiskFindingDto,
    RiskLevel,
    RiskRuleCode,
    RiskSummaryDto,
)
from app.schemas.transaction import AnalyzeTransactionsDto
from app.services import risk_agent


@pytest.fixture
def payload() -> AnalyzeTransactionsDto:
    return AnalyzeTransactionsDto.model_validate(
        {
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
    )


@pytest.fixture
def analysis() -> RiskAnalysisResponseDto:
    return RiskAnalysisResponseDto(
        status="completed",
        summary=RiskSummaryDto(
            total_findings=1,
            total_transactions=1,
            flagged_transactions=1,
        ),
        findings=[
            RiskFindingDto(
                reason="Transaction amount exceeds the configured USD threshold",
                transaction_id="txn_001",
                risk_level=RiskLevel.HIGH,
                rule_code=RiskRuleCode.HIGH_AMOUNT,
            )
        ],
    )


@pytest.fixture
def mocked_dependencies(monkeypatch):
    bedrock_model = Mock()
    model_instance = Mock()
    bedrock_model.return_value = model_instance
    agent = Mock()
    monkeypatch.setattr(risk_agent, "BedrockModel", bedrock_model)
    monkeypatch.setattr(risk_agent, "Agent", agent)
    return bedrock_model, model_instance, agent


def test_factory_uses_configured_model_and_structured_assessment(
    payload, analysis, mocked_dependencies
):
    bedrock_model, model_instance, agent = mocked_dependencies

    risk_agent.create_risk_agent(
        payload, analysis, "ap-southeast-1", "configured-model"
    )

    bedrock_model.assert_called_once_with(
        region_name="ap-southeast-1", model_id="configured-model"
    )
    assert agent.call_args.kwargs["model"] is model_instance
    assert (
        agent.call_args.kwargs["structured_output_model"].__name__ == "AiAssessmentDto"
    )


def test_factory_registers_two_no_argument_snapshot_tools(
    payload, analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies

    risk_agent.create_risk_agent(payload, analysis, "us-east-1", "test-model")

    tools = {tool.tool_name: tool for tool in agent.call_args.kwargs["tools"]}
    assert set(tools) == {"get_verified_risk_findings", "get_validated_transactions"}
    assert all(
        tool.tool_spec["inputSchema"]["json"]["properties"] == {}
        for tool in tools.values()
    )
    assert tools["get_verified_risk_findings"]() == analysis.model_dump(mode="json")
    assert tools["get_validated_transactions"]() == payload.model_dump(mode="json")


def test_tools_keep_immutable_request_snapshots(payload, analysis, mocked_dependencies):
    _, _, agent = mocked_dependencies
    expected_transactions = payload.model_dump(mode="json")

    risk_agent.create_risk_agent(payload, analysis, "us-east-1", "test-model")
    payload.transactions[0].transaction_id = "changed"
    analysis.findings[0].transaction_id = "changed"

    tools = {tool.tool_name: tool for tool in agent.call_args.kwargs["tools"]}
    assert tools["get_validated_transactions"]() == expected_transactions
    assert (
        tools["get_verified_risk_findings"]()["findings"][0]["transaction_id"]
        == "txn_001"
    )


def test_agent_instances_do_not_share_transaction_snapshots(
    payload, analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies
    second_payload = payload.model_copy(
        update={
            "transactions": [
                payload.transactions[0].model_copy(update={"transaction_id": "txn_002"})
            ]
        }
    )

    risk_agent.create_risk_agent(payload, analysis, "us-east-1", "test-model")
    risk_agent.create_risk_agent(second_payload, analysis, "us-east-1", "test-model")

    first = agent.call_args_list[0].kwargs["tools"][1]()
    second = agent.call_args_list[1].kwargs["tools"][1]()
    assert first["transactions"][0]["transaction_id"] == "txn_001"
    assert second["transactions"][0]["transaction_id"] == "txn_002"


def test_system_prompt_limits_observations_to_advisory_context(
    payload, analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies

    risk_agent.create_risk_agent(payload, analysis, "us-east-1", "test-model")

    prompt = " ".join(agent.call_args.kwargs["system_prompt"].lower().split())
    for requirement in (
        "call get_validated_transactions and get_verified_risk_findings",
        "verified findings remain authoritative",
        "advisory patterns",
        "confirmed fraud",
        "currencies without conversion data",
        "untrusted data",
    ):
        assert requirement in prompt
