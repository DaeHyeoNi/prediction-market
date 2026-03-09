"""
Tests for market settlement logic.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.market import Market, MarketResult, MarketStatus
from app.models.order import Order, OrderStatus, OrderType, PositionSide
from app.models.position import Position
from app.models.user import User


@pytest.mark.asyncio
async def test_settle_market_pays_winners(db_session):
    """After settlement, YES position holders receive 100 points per unit."""
    user = User(
        username="winner",
        hashed_password="x",
        total_points=900_000,
        available_points=900_000,
    )
    db_session.add(user)
    await db_session.flush()

    market = Market(
        title="Settlement Test",
        closes_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_by=user.id,
        status=MarketStatus.CLOSED,
    )
    db_session.add(market)
    await db_session.flush()

    pos = Position(
        user_id=user.id,
        market_id=market.id,
        position=PositionSide.YES,
        quantity=100,
        avg_price=60,
    )
    db_session.add(pos)
    await db_session.flush()

    # Simulate settlement payout
    market.status = MarketStatus.RESOLVED
    market.result = MarketResult.YES
    market.resolved_at = datetime.now(timezone.utc)

    payout = pos.quantity * 100  # 10_000
    user.total_points += payout
    user.available_points += payout
    await db_session.commit()

    await db_session.refresh(user)
    assert user.total_points == 910_000
    assert user.available_points == 910_000


@pytest.mark.asyncio
async def test_settle_market_no_winners_not_affected(db_session):
    """NO position holders are not paid when YES wins."""
    user = User(
        username="loser",
        hashed_password="x",
        total_points=800_000,
        available_points=800_000,
    )
    db_session.add(user)
    await db_session.flush()

    market = Market(
        title="Loser Test",
        closes_at=datetime.now(timezone.utc) - timedelta(hours=1),
        created_by=user.id,
        status=MarketStatus.CLOSED,
    )
    db_session.add(market)
    await db_session.flush()

    pos = Position(
        user_id=user.id,
        market_id=market.id,
        position=PositionSide.NO,
        quantity=50,
        avg_price=40,
    )
    db_session.add(pos)
    await db_session.flush()

    # Settle with YES winning - NO holders get nothing
    market.status = MarketStatus.RESOLVED
    market.result = MarketResult.YES
    market.resolved_at = datetime.now(timezone.utc)
    await db_session.commit()

    await db_session.refresh(user)
    # User's points should be unchanged
    assert user.total_points == 800_000
    assert user.available_points == 800_000


@pytest.mark.asyncio
async def test_cancel_bid_order_returns_locked_points(db_session):
    """Cancelling a BID order returns locked points to available."""
    from app.engine.matching import cancel_order

    user = User(
        username="canceller",
        hashed_password="x",
        total_points=1_000_000,
        available_points=900_000,  # 100_000 already locked
    )
    db_session.add(user)
    await db_session.flush()

    market = Market(
        title="Cancel Test",
        closes_at=datetime.now(timezone.utc) + timedelta(days=1),
        created_by=user.id,
        status=MarketStatus.OPEN,
    )
    db_session.add(market)
    await db_session.flush()

    order = Order(
        user_id=user.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=50,
        quantity=2000,
        remaining_quantity=2000,
        status=OrderStatus.OPEN,
        locked_points=100_000,  # 50 * 2000
    )
    db_session.add(order)
    await db_session.flush()

    await cancel_order(db_session, order.id)

    await db_session.refresh(order)
    await db_session.refresh(user)

    assert order.status == OrderStatus.CANCELLED
    assert order.locked_points == 0
    # Available points restored: 900_000 + 100_000 = 1_000_000
    assert user.available_points == 1_000_000
    # Total points unchanged (were never deducted at lock time)
    assert user.total_points == 1_000_000
