import json
from hashlib import sha256

from fastapi import HTTPException, status

from app.schemas import AnalyzeTransactionsDto, RiskAnalysisResponseDto


def build_request_hash(payload: AnalyzeTransactionsDto, include_ai: bool) -> str:
    request = {
        "analysis_version": "1",
        "include_ai": include_ai,
        "transactions": payload.model_dump(mode="json")["transactions"],
    }
    canonical_request = json.dumps(request, separators=(",", ":"), sort_keys=True)
    return sha256(canonical_request.encode()).hexdigest()


def load_stored_response(
    record: dict,
    request_hash: str,
) -> RiskAnalysisResponseDto:
    if record.get("request_hash") != request_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    if record.get("status") == "PROCESSING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    if record.get("status") != "COMPLETED" or not isinstance(
        record.get("response"), dict
    ):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return RiskAnalysisResponseDto.model_validate(record["response"])
