from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.dependencies import get_current_user, get_db
from app.models.market import MarketStatus
from app.models.position import Position
from app.models.user import User
from app.schemas.position import PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


def _to_response(pos: Position) -> PositionResponse:
    return PositionResponse(
        id=pos.id,
        user_id=pos.user_id,
        market_id=pos.market_id,
        market_title=pos.market.title,
        market_status=pos.market.status,
        market_result=pos.market.result,
        position=pos.position,
        quantity=pos.quantity,
        avg_price=pos.avg_price,
    )


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    market_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="active | resolved | all (default: active)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    내 포지션 목록.
    - status=active (기본): 보유 중인 포지션 (quantity > 0)
    - status=resolved: 청산된 마켓의 포지션 (손익 포함)
    - status=all: 전체
    """
    query = (
        select(Position)
        .options(joinedload(Position.market))
        .where(Position.user_id == current_user.id)
    )

    if market_id is not None:
        query = query.where(Position.market_id == market_id)

    if status == "resolved":
        from sqlalchemy import join
        from app.models.market import Market
        query = query.join(Position.market).where(Market.status == MarketStatus.RESOLVED)
    elif status == "all":
        pass
    else:
        # active: quantity > 0
        query = query.where(Position.quantity > 0)

    result = await db.execute(query)
    positions = result.scalars().all()
    return [_to_response(p) for p in positions]
