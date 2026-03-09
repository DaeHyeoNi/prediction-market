"""
Tests for the matching engine.
Covers direct matches, mirror matches, and partial fills.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.engine.matching import match_order
from app.models.market import Market, MarketStatus
from app.models.order import Order, OrderStatus, OrderType, PositionSide
from app.models.position import Position
from app.models.user import User


@pytest_asyncio.fixture
async def setup_users(db_session):
    user1 = User(
        username="alice",
        hashed_password="x",
        total_points=1_000_000,
        available_points=1_000_000,
    )
    user2 = User(
        username="bob",
        hashed_password="x",
        total_points=1_000_000,
        available_points=1_000_000,
    )
    db_session.add_all([user1, user2])
    await db_session.flush()
    return user1, user2


@pytest_asyncio.fixture
async def setup_market(db_session, setup_users):
    user1, _ = setup_users
    market = Market(
        title="Test Market",
        closes_at=datetime.now(timezone.utc) + timedelta(days=1),
        created_by=user1.id,
        status=MarketStatus.OPEN,
    )
    db_session.add(market)
    await db_session.flush()
    return market


@pytest.mark.asyncio
async def test_direct_yes_bid_ask_match(db_session, setup_users, setup_market):
    """YES BID at 65 matches YES ASK at 60. Trade at 60 (maker's price)."""
    user1, user2 = setup_users
    market = setup_market

    # user2 holds YES position to sell
    pos = Position(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        quantity=10,
        avg_price=50,
    )
    db_session.add(pos)

    # user2 creates YES ASK at 60
    ask = Order(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.ASK,
        price=60,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    db_session.add(ask)
    await db_session.flush()

    # user1 creates YES BID at 65, locking 65*10=650 points
    initial_total = user1.total_points
    initial_avail = user1.available_points
    user1.available_points -= 65 * 10  # lock at creation

    bid = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=65,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=65 * 10,
    )
    db_session.add(bid)
    await db_session.flush()

    await match_order(db_session, bid.id)

    await db_session.refresh(bid)
    await db_session.refresh(ask)
    await db_session.refresh(user1)
    await db_session.refresh(user2)

    # Orders fully filled
    assert bid.status == OrderStatus.FILLED
    assert ask.status == OrderStatus.FILLED

    # Buyer (user1): locked 650, trade at 60 each
    # total_points -= 60*10 = 600  → 1_000_000 - 600 = 999_400
    # available_points: started at 1_000_000 - 650 = 999_350
    #   + refund (65-60)*10 = 50  → 999_400
    assert user1.total_points == initial_total - 60 * 10
    assert user1.available_points == (initial_avail - 65 * 10) + (65 - 60) * 10

    # Seller (user2): receives 60*10=600 added to total and available
    assert user2.total_points == 1_000_000 + 60 * 10
    assert user2.available_points == 1_000_000 + 60 * 10

    # Buyer position created
    pos_result = await db_session.execute(
        select(Position).where(
            Position.user_id == user1.id,
            Position.market_id == market.id,
            Position.position == PositionSide.YES,
        )
    )
    buyer_pos = pos_result.scalar_one_or_none()
    assert buyer_pos is not None
    assert buyer_pos.quantity == 10


@pytest.mark.asyncio
async def test_mirror_match_yes_bid_no_ask(db_session, setup_users, setup_market):
    """YES BID at 70 matches NO ASK at 30 (mirror: 100-70=30)."""
    user1, user2 = setup_users
    market = setup_market

    # user2 holds NO position to sell
    no_pos = Position(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.NO,
        quantity=10,
        avg_price=25,
    )
    db_session.add(no_pos)

    # user2 creates NO ASK at 30
    no_ask = Order(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.NO,
        order_type=OrderType.ASK,
        price=30,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    db_session.add(no_ask)
    await db_session.flush()

    # user1 creates YES BID at 70, locking 70*10=700
    user1.available_points -= 70 * 10
    yes_bid = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=70,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=70 * 10,
    )
    db_session.add(yes_bid)
    await db_session.flush()

    await match_order(db_session, yes_bid.id)

    await db_session.refresh(yes_bid)
    await db_session.refresh(no_ask)
    await db_session.refresh(user1)
    await db_session.refresh(user2)

    assert yes_bid.status == OrderStatus.FILLED
    assert no_ask.status == OrderStatus.FILLED

    # Mirror: taker_trade_price = 100 - 30 = 70, maker_trade_price = 30
    # Buyer (YES BID, user1): locked at 70, trade at 70 → no refund
    # total_points -= 70*10 = 700
    assert user1.total_points == 1_000_000 - 70 * 10
    # available_points: 1_000_000 - 700 (locked) + 0 (no excess) = 999_300
    assert user1.available_points == 1_000_000 - 70 * 10

    # Seller (NO ASK, user2): receives 30*10=300
    assert user2.total_points == 1_000_000 + 30 * 10
    assert user2.available_points == 1_000_000 + 30 * 10

    # user1 gets YES position
    pos_result = await db_session.execute(
        select(Position).where(
            Position.user_id == user1.id,
            Position.market_id == market.id,
            Position.position == PositionSide.YES,
        )
    )
    buyer_pos = pos_result.scalar_one_or_none()
    assert buyer_pos is not None
    assert buyer_pos.quantity == 10

    # user2's NO position decreases
    await db_session.refresh(no_pos)
    assert no_pos.quantity == 0


@pytest.mark.asyncio
async def test_partial_fill(db_session, setup_users, setup_market):
    """BID for 10 units, only 5 available → partial fill."""
    user1, user2 = setup_users
    market = setup_market

    pos = Position(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        quantity=5,
        avg_price=40,
    )
    ask = Order(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.ASK,
        price=50,
        quantity=5,
        remaining_quantity=5,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    db_session.add_all([pos, ask])
    await db_session.flush()

    user1.available_points -= 50 * 10
    bid = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=50,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=50 * 10,
    )
    db_session.add(bid)
    await db_session.flush()

    await match_order(db_session, bid.id)

    await db_session.refresh(bid)
    await db_session.refresh(ask)

    assert ask.status == OrderStatus.FILLED
    assert bid.status == OrderStatus.PARTIAL
    assert bid.remaining_quantity == 5


@pytest.mark.asyncio
async def test_no_self_match(db_session, setup_users, setup_market):
    """A user's own order should not match against their own order."""
    user1, _ = setup_users
    market = setup_market

    pos = Position(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        quantity=10,
        avg_price=50,
    )
    ask = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.ASK,
        price=50,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    db_session.add_all([pos, ask])
    await db_session.flush()

    user1.available_points -= 60 * 10
    bid = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=60,
        quantity=10,
        remaining_quantity=10,
        status=OrderStatus.OPEN,
        locked_points=60 * 10,
    )
    db_session.add(bid)
    await db_session.flush()

    await match_order(db_session, bid.id)

    await db_session.refresh(bid)
    await db_session.refresh(ask)

    # Should NOT self-match
    assert bid.status == OrderStatus.OPEN
    assert ask.status == OrderStatus.OPEN


@pytest.mark.asyncio
async def test_price_time_priority(db_session, setup_users, setup_market):
    """Better-priced ask is matched before a worse-priced ask placed earlier."""
    user1, user2 = setup_users
    market = setup_market

    # user2 has two YES ASK orders: first at 60, then at 55 (better for buyer)
    pos = Position(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        quantity=20,
        avg_price=40,
    )
    db_session.add(pos)

    ask_60 = Order(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.ASK,
        price=60,
        quantity=5,
        remaining_quantity=5,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    ask_55 = Order(
        user_id=user2.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.ASK,
        price=55,
        quantity=5,
        remaining_quantity=5,
        status=OrderStatus.OPEN,
        locked_points=0,
    )
    db_session.add_all([ask_60, ask_55])
    await db_session.flush()

    user1.available_points -= 65 * 5
    bid = Order(
        user_id=user1.id,
        market_id=market.id,
        position=PositionSide.YES,
        order_type=OrderType.BID,
        price=65,
        quantity=5,
        remaining_quantity=5,
        status=OrderStatus.OPEN,
        locked_points=65 * 5,
    )
    db_session.add(bid)
    await db_session.flush()

    await match_order(db_session, bid.id)

    await db_session.refresh(bid)
    await db_session.refresh(ask_55)
    await db_session.refresh(ask_60)

    # ask_55 should be matched (better price for buyer)
    assert bid.status == OrderStatus.FILLED
    assert ask_55.status == OrderStatus.FILLED
    assert ask_60.status == OrderStatus.OPEN
