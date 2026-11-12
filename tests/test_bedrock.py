from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from app.services.bedrock import BedrockError, BedrockService


def test_invoke_returns_response_text():
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "ok"}]}}
    }

    result = BedrockService("us-east-1", "test-model", client=client).invoke("hello")

    assert result == "ok"


def test_invoke_sends_expected_converse_request():
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": "ok"}]}}
    }

    service = BedrockService("us-east-1", "test-model", client=client)

    service.invoke("hello")

    client.converse.assert_called_once_with(
        modelId="test-model",
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0},
    )


def test_invoke_joins_multiple_text_blocks_in_order():
    client = Mock()
    client.converse.return_value = {
        "output": {
            "message": {
                "content": [{"text": "first "}, {"text": "second"}],
            }
        }
    }

    result = BedrockService("us-east-1", "test-model", client=client).invoke("hello")

    assert result == "first second"


def test_invoke_rejects_empty_response_content():
    client = Mock()
    client.converse.return_value = {"output": {"message": {"content": []}}}

    with pytest.raises(BedrockError, match="no text"):
        BedrockService("us-east-1", "test-model", client=client).invoke("hello")


def test_invoke_rejects_malformed_response():
    client = Mock()
    client.converse.return_value = {}

    with pytest.raises(BedrockError, match="no text"):
        BedrockService("us-east-1", "test-model", client=client).invoke("hello")


def test_invoke_sanitizes_client_errors():
    client = Mock()
    detail = "AWS account details must not be exposed"
    client.converse.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": detail}},
        "Converse",
    )

    with pytest.raises(BedrockError) as error:
        BedrockService("us-east-1", "test-model", client=client).invoke("hello")

    assert str(error.value) == "Bedrock request failed"
    assert detail not in str(error.value)


def test_invoke_converts_botocore_errors():
    client = Mock()
    client.converse.side_effect = EndpointConnectionError(
        endpoint_url="https://bedrock-runtime.example"
    )

    with pytest.raises(BedrockError, match="Bedrock request failed"):
        BedrockService("us-east-1", "test-model", client=client).invoke("hello")


@pytest.mark.parametrize("model_id", ["", "   "])
def test_rejects_blank_model_id(model_id):
    with pytest.raises(ValueError, match="model ID"):
        BedrockService("us-east-1", model_id, client=Mock())


@pytest.mark.parametrize("timeout_seconds", [0, -1])
def test_rejects_non_positive_timeout(timeout_seconds):
    with pytest.raises(ValueError, match="timeout"):
        BedrockService(
            "us-east-1", "test-model", timeout_seconds=timeout_seconds, client=Mock()
        )


def test_uses_injected_client_without_creating_boto3_client():
    client = Mock()

    with patch("app.services.bedrock.boto3.client") as create_client:
        service = BedrockService("us-east-1", "test-model", client=client)

    assert service.client is client
    create_client.assert_not_called()
