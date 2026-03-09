import json
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.market import Market, MarketStatus
from app.models.order import Order, OrderStatus, OrderType, PositionSide
from app.models.position import Position
from app.models.user import User
from app.schemas.order import OrderCreate, OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_order(
    data: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate market
    result = await db.execute(select(Market).where(Market.id == data.market_id))
    market = result.scalar_one_or_none()
    if not market:
        raise HTTPException(status_code=404, detail="Market not found")
    if market.status != MarketStatus.OPEN:
        raise HTTPException(status_code=400, detail="Market is not open")
    if market.closes_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Market has closed")

    # For ASK orders, validate position ownership
    if data.order_type == OrderType.ASK:
        pos_result = await db.execute(
            select(Position).where(
                Position.user_id == current_user.id,
                Position.market_id == data.market_id,
                Position.position == data.position,
            )
        )
        position = pos_result.scalar_one_or_none()
        if not position or position.quantity < data.quantity:
            raise HTTPException(status_code=400, detail="Insufficient position for ASK order")

    # Lock margin for BID orders and create order atomically
    async with db.begin_nested():
        # Re-fetch user with lock
        user_result = await db.execute(
            select(User).where(User.id == current_user.id).with_for_update()
        )
        user = user_result.scalar_one()

        locked_points = 0
        if data.order_type == OrderType.BID:
            required = data.price * data.quantity
            if user.available_points < required:
                raise HTTPException(status_code=400, detail="Insufficient available points")
            user.available_points -= required
            locked_points = required

        order = Order(
            user_id=current_user.id,
            market_id=data.market_id,
            position=data.position,
            order_type=data.order_type,
            price=data.price,
            quantity=data.quantity,
            remaining_quantity=data.quantity,
            status=OrderStatus.OPEN,
            locked_points=locked_points,
        )
        db.add(order)
        await db.flush()

    await db.commit()
    await db.refresh(order)

    # Push to market queue
    redis_client = aioredis.from_url(settings.REDIS_URL)
    try:
        await redis_client.rpush(
            f"market_queue:{data.market_id}",
            json.dumps({"type": "order", "order_id": order.id}),
        )
    finally:
        await redis_client.aclose()

    return order


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .limit(100)
    )
    return result.scalars().all()


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.user_id == current_user.id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in (OrderStatus.OPEN, OrderStatus.PARTIAL):
        raise HTTPException(status_code=400, detail="Order cannot be cancelled")

    # Push cancel message to market queue
    redis_client = aioredis.from_url(settings.REDIS_URL)
    try:
        await redis_client.rpush(
            f"market_queue:{order.market_id}",
            json.dumps({"type": "cancel", "order_id": order_id}),
        )
    finally:
        await redis_client.aclose()
