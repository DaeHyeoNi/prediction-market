from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.dependencies import get_current_user, get_db
from app.models.market import Market, MarketStatus
from app.models.user import User
from app.schemas.market import MarketResolve
from app.tasks.celery_app import celery_app

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/markets/{market_id}/resolve")
async def resolve_market(
    market_id: int,
    data: MarketResolve,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status == MarketStatus.RESOLVED:
        raise HTTPException(status_code=400, detail="Market already resolved")

    celery_app.send_task(
        "app.tasks.market_tasks.settle_market",
        args=[market_id, data.result.value],
    )
    return {"message": "Settlement initiated", "market_id": market_id}
