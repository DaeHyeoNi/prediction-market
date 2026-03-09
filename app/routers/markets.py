from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.dependencies import get_current_user, get_db
from app.engine.queue_worker import worker_manager
from app.models.market import Market, MarketStatus
from app.models.trade import Trade
from app.models.user import User
from app.schemas.market import MarketCreate, MarketResponse

router = APIRouter(prefix="/markets", tags=["markets"])


@router.get("", response_model=list[MarketResponse])
async def list_markets(
    status: Optional[MarketStatus] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Market)
    if status:
        query = query.where(Market.status == status)
    query = query.offset(offset).limit(limit).order_by(Market.created_at.desc())
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=MarketResponse, status_code=201)
async def create_market(
    data: MarketCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    market = Market(**data.model_dump(), created_by=current_user.id)
    db.add(market)
    await db.commit()
    await db.refresh(market)
    # Start worker for the new market
    await worker_manager.start_market_worker(market.id)
    return market


@router.get("/{market_id}", response_model=MarketResponse)
async def get_market(market_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Market).where(Market.id == market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    return market


@router.get("/{market_id}/orderbook")
async def get_orderbook(market_id: int, db: AsyncSession = Depends(get_db)):
    from app.engine.orderbook import get_orderbook_snapshot
    return await get_orderbook_snapshot(db, market_id)


@router.get("/{market_id}/trades", response_model=list[dict])
async def get_trades(
    market_id: int,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Trade)
        .where(Trade.market_id == market_id)
        .order_by(Trade.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    trades = result.scalars().all()
    return [
        {
            "id": t.id,
            "market_id": t.market_id,
            "maker_order_id": t.maker_order_id,
            "taker_order_id": t.taker_order_id,
            "position": t.position,
            "price": t.price,
            "quantity": t.quantity,
            "created_at": t.created_at,
        }
        for t in trades
    ]
