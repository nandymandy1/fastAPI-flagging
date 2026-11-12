import asyncio
import re
from contextlib import suppress
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config.config import Settings, get_settings
from app.dependencies import (
    RiskAgentBuilder,
    get_idempotency_store,
    get_risk_agent_builder,
    get_risk_analysis_service,
    require_api_key,
)
from app.schemas import (
    AiAssessmentDto,
    AnalyzeTransactionsDto,
    RiskAnalysisResponseDto,
)
from app.services import IdempotencyStore, RiskAnalysisService
from app.utils import build_request_hash, load_stored_response

router = APIRouter(prefix="/risk", tags=["Risk Monitor"])
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


@router.post(
    "/analyze",
    response_model=RiskAnalysisResponseDto,
    response_model_exclude_none=True,
    dependencies=[Depends(require_api_key)],
)
async def analyze_transactions(
    payload: AnalyzeTransactionsDto,
    service: Annotated[RiskAnalysisService, Depends(get_risk_analysis_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    agent_builder: Annotated[RiskAgentBuilder | None, Depends(get_risk_agent_builder)],
    idempotency_store: Annotated[
        IdempotencyStore | None, Depends(get_idempotency_store)
    ],
    include_ai: bool | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RiskAnalysisResponseDto:
    if not idempotency_key or not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    if idempotency_store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    ai_requested = include_ai is not False
    request_hash = build_request_hash(payload, ai_requested)

    try:
        existing = await asyncio.to_thread(idempotency_store.get, idempotency_key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    if existing:
        return load_stored_response(existing, request_hash)

    try:
        reservation = await asyncio.to_thread(
            idempotency_store.reserve,
            idempotency_key,
            request_hash,
        )

        if reservation is None:
            existing = await asyncio.to_thread(idempotency_store.get, idempotency_key)
            if existing:
                return load_stored_response(existing, request_hash)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    try:
        analysis = RiskAnalysisResponseDto.model_validate(service.analyze(payload))
        if ai_requested and (agent_builder is not None or include_ai is True):
            await _add_ai_assessment(analysis, payload, settings, agent_builder)

    except Exception:
        with suppress(Exception):
            await asyncio.to_thread(
                idempotency_store.release,
                idempotency_key,
                reservation["reservation_id"],
            )
        raise

    response = analysis.model_dump(mode="json", exclude_none=True)

    try:
        await asyncio.to_thread(
            idempotency_store.complete,
            idempotency_key,
            reservation["reservation_id"],
            response,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc

    return analysis


async def _add_ai_assessment(
    analysis: RiskAnalysisResponseDto,
    payload: AnalyzeTransactionsDto,
    settings: Settings,
    agent_builder: RiskAgentBuilder | None,
) -> None:
    if agent_builder is None:
        analysis.ai_status = "unavailable"
        return

    try:
        async with asyncio.timeout(settings.bedrock_timeout_seconds):
            result = await agent_builder(payload, analysis).invoke_async(
                "Call both tools, then provide an advisory contextual assessment."
            )
        findings_metrics = result.metrics.tool_metrics.get("get_verified_risk_findings")
        transactions_metrics = result.metrics.tool_metrics.get(
            "get_validated_transactions"
        )
        assessment = result.structured_output
        valid_transaction_ids = {
            transaction.transaction_id for transaction in payload.transactions
        }
        if (
            result.stop_reason == "end_turn"
            and findings_metrics
            and findings_metrics.success_count > 0
            and findings_metrics.error_count == 0
            and transactions_metrics
            and transactions_metrics.success_count > 0
            and transactions_metrics.error_count == 0
            and isinstance(assessment, AiAssessmentDto)
            and all(
                set(observation.transaction_ids) <= valid_transaction_ids
                for observation in assessment.ai_observations
            )
        ):
            analysis.ai_summary = assessment.ai_summary
            analysis.ai_observations = assessment.ai_observations
            analysis.ai_status = "generated"
            return

    except Exception:  # noqa: BLE001
        analysis.ai_status = "unavailable"
        return

    analysis.ai_status = "unavailable"
