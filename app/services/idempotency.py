from time import time
from uuid import uuid4

from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError


class IdempotencyStoreError(RuntimeError):
    pass


class IdempotencyStore:
    def __init__(self, table):
        self.table = table

    def reserve(self, key: str, request_hash: str) -> dict | None:
        now = int(time())
        reservation = {
            "pk": key,
            "request_hash": request_hash,
            "status": "PROCESSING",
            "reservation_id": str(uuid4()),
            "event_id": str(uuid4()),
            "expires_at": now + 600,
        }
        try:
            self.table.put_item(
                Item=reservation,
                ConditionExpression=Attr("pk").not_exists()
                | Attr("expires_at").lte(now),
            )
        except ClientError as exc:
            if _is_conditional_failure(exc):
                if self.get(key):
                    return None
                raise IdempotencyStoreError("Idempotency reservation conflict") from exc
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        return reservation

    def get(self, key: str) -> dict | None:
        try:
            item = self.table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency storage request failed") from exc
        return item if item and item.get("expires_at", 0) > int(time()) else None

    def complete(self, key: str, reservation_id: str, response: dict) -> None:
        now = int(time())
        try:
            self.table.update_item(
                Key={"pk": key},
                UpdateExpression="SET #status = :completed, response = :response, expires_at = :expires",
                ConditionExpression=(
                    Attr("reservation_id").eq(reservation_id)
                    & Attr("status").eq("PROCESSING")
                    & Attr("expires_at").gt(now)
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":completed": "COMPLETED",
                    ":response": response,
                    ":expires": now + 86400,
                },
            )
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency completion failed") from exc

    def release(self, key: str, reservation_id: str) -> None:
        try:
            self.table.delete_item(
                Key={"pk": key},
                ConditionExpression=(
                    Attr("reservation_id").eq(reservation_id)
                    & Attr("status").eq("PROCESSING")
                ),
            )
        except Exception as exc:
            raise IdempotencyStoreError("Idempotency release failed") from exc


def _is_conditional_failure(exc: ClientError) -> bool:
    return (
        exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"
    )
