from fastapi import APIRouter
from app.schemas.transaction import AnalyzeTransactionsDto


router = APIRouter(
    prefix="/risk",
    tags=["Risk Monitor"],
)


@router.post("/analyze")
async def analyze_transactions(
    payload: AnalyzeTransactionsDto,
):
    return {
        "status": "accepted",
        "total_transactions": len(payload.transactions),
        "transaction_ids": [
            transaction.transaction_id for transaction in payload.transactions
        ],
    }
