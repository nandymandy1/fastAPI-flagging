import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class BedrockError(Exception):
    pass


class BedrockService:
    def __init__(
        self,
        region_name: str,
        model_id: str,
        timeout_seconds: int = 60,
        client=None,
    ):
        if not model_id or not model_id.strip():
            raise ValueError("A Bedrock model ID is required")
        if timeout_seconds <= 0:
            raise ValueError("Bedrock timeout must be positive")

        self.model_id = model_id
        self.client = client or boto3.client(
            "bedrock-runtime",
            region_name=region_name,
            config=Config(connect_timeout=10, read_timeout=timeout_seconds),
        )

    def invoke(self, prompt: str) -> str:
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 512, "temperature": 0},
            )
        except (BotoCoreError, ClientError) as exc:
            raise BedrockError("Bedrock request failed") from exc

        output = response.get("output") if isinstance(response, dict) else None
        message = output.get("message") if isinstance(output, dict) else None
        content = message.get("content") if isinstance(message, dict) else []
        content = content if isinstance(content, list) else []
        text = "".join(
            block["text"]
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text:
            raise BedrockError("Bedrock response contained no text")
        return text
