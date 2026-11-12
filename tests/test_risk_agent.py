import asyncio
import json
from unittest.mock import Mock

import pytest

from app.schemas.risk import (
    RiskAnalysisResponseDto,
    RiskFindingDto,
    RiskLevel,
    RiskRuleCode,
    RiskSummaryDto,
)
from app.services import risk_agent


@pytest.fixture
def analysis():
    return RiskAnalysisResponseDto(
        status="completed",
        summary=RiskSummaryDto(
            total_findings=1,
            total_transactions=2,
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


def test_factory_constructs_agent_with_bedrock_model(analysis, mocked_dependencies):
    _, model_instance, agent = mocked_dependencies

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")

    agent.assert_called_once()
    assert agent.call_args.kwargs["model"] is model_instance


def test_factory_forwards_model_configuration(analysis, mocked_dependencies):
    bedrock_model, _, _ = mocked_dependencies

    risk_agent.create_risk_agent(analysis, "ap-southeast-1", "configured-model")

    bedrock_model.assert_called_once_with(
        region_name="ap-southeast-1", model_id="configured-model"
    )


def test_factory_registers_only_the_no_argument_findings_tool(
    analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")

    tools = agent.call_args.kwargs["tools"]
    assert len(tools) == 1
    assert tools[0].tool_name == "get_verified_risk_findings"
    assert tools[0].tool_spec["inputSchema"]["json"]["properties"] == {}


def test_findings_tool_returns_the_verified_serialized_analysis(
    analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies
    expected = analysis.model_dump(mode="json")

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")
    findings_tool = agent.call_args.kwargs["tools"][0]
    event = asyncio.run(
        anext(
            findings_tool.stream(
                {"toolUseId": "test", "name": findings_tool.tool_name, "input": {}},
                {},
            )
        )
    )

    result = json.loads(event["tool_result"]["content"][0]["text"])
    assert result == expected


def test_findings_tool_keeps_a_snapshot_after_analysis_changes(
    analysis, mocked_dependencies
):
    _, _, agent = mocked_dependencies
    expected = analysis.model_dump(mode="json")

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")
    analysis.findings[0].transaction_id = "changed"
    analysis.summary.total_findings = 99

    assert agent.call_args.kwargs["tools"][0]() == expected


def test_agents_keep_findings_isolated(mocked_dependencies):
    _, _, agent = mocked_dependencies
    first = RiskAnalysisResponseDto(
        status="completed",
        summary=RiskSummaryDto(
            total_findings=1, total_transactions=1, flagged_transactions=1
        ),
        findings=[
            RiskFindingDto(
                reason="first",
                transaction_id="txn_first",
                risk_level=RiskLevel.HIGH,
                rule_code=RiskRuleCode.HIGH_AMOUNT,
            )
        ],
    )
    second = first.model_copy(update={"findings": [first.findings[0].model_copy()]})
    second.findings[0].transaction_id = "txn_second"

    risk_agent.create_risk_agent(first, "us-east-1", "test-model")
    risk_agent.create_risk_agent(second, "us-east-1", "test-model")

    first_tool = agent.call_args_list[0].kwargs["tools"][0]
    second_tool = agent.call_args_list[1].kwargs["tools"][0]
    assert first_tool()["findings"][0]["transaction_id"] == "txn_first"
    assert second_tool()["findings"][0]["transaction_id"] == "txn_second"


def test_system_prompt_has_required_safety_constraints(analysis, mocked_dependencies):
    _, _, agent = mocked_dependencies

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")

    prompt = " ".join(agent.call_args.kwargs["system_prompt"].lower().split())
    for requirement in (
        "verified findings",
        "call get_verified_risk_findings",
        "never invent",
        "transaction ids",
        "classify transactions independently",
        "webhook notification was sent",
        "untrusted data",
    ):
        assert requirement in prompt


def test_factory_and_tool_do_not_invoke_bedrock(analysis, mocked_dependencies):
    _, model_instance, agent = mocked_dependencies

    risk_agent.create_risk_agent(analysis, "us-east-1", "test-model")
    agent.call_args.kwargs["tools"][0]()

    model_instance.invoke.assert_not_called()
    model_instance.client.converse.assert_not_called()
