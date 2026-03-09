"""
Matching Engine for Prediction Market

Double Orderbook: YES_PRICE + NO_PRICE = 100

Point Flow:
- BID created: available_points -= price * qty; total_points unchanged; locked_points = price * qty
- BID filled at trade_price (trade_price <= bid_price):
    - total_points -= trade_price * fill_qty   (points leave the buyer)
    - locked_points -= bid_price * fill_qty    (release the full locked amount)
    - available_points += (bid_price - trade_price) * fill_qty   (refund excess)
    - buyer receives position
- ASK filled at trade_price:
    - total_points += trade_price * fill_qty   (points arrive at seller)
    - available_points += trade_price * fill_qty
    - seller's position decreases

Mirror match rules:
    YES BID at B can match: YES ASK at p<=B (direct) OR NO ASK at p<=(100-B) (mirror)
    YES ASK at A can match: YES BID at p>=A (direct) OR NO BID at p>=(100-A) (mirror)
    NO BID at B can match:  NO ASK at p<=B (direct)  OR YES ASK at p<=(100-B) (mirror)
    NO ASK at A can match:  NO BID at p>=A (direct)  OR YES BID at p>=(100-A) (mirror)

Mirror trade example (YES BID=70 vs NO ASK=30):
    - Trade price from YES buyer perspective = 70 (locked at 70, no refund)
    - Trade price from NO seller perspective = 30 (they receive 30 per unit)
    - 70 + 30 = 100 (money conservation)

Direct trade example (YES BID=70 vs YES ASK=65):
    - Trade price = 65 (maker's ask price)
    - YES buyer: locked at 70, pays 65, refund 5 per unit
    - YES seller: receives 65 per unit
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus, OrderType, PositionSide
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User

ACTIVE_STATUSES = (OrderStatus.OPEN, OrderStatus.PARTIAL)


async def _find_best_maker(session: AsyncSession, taker: Order) -> Order | None:
    """Find the best maker order matching the taker. Returns None if no match."""
    opposite = PositionSide.NO if taker.position == PositionSide.YES else PositionSide.YES
    mirror_threshold = 100 - taker.price

    if taker.order_type == OrderType.BID:
        # Taker is buying: find the cheapest ask (direct or mirror)
        direct_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == taker.position,
                Order.order_type == OrderType.ASK,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price <= taker.price,
                Order.id != taker.id,
            )
            .order_by(Order.price.asc(), Order.created_at.asc())
            .limit(1)
        )
        mirror_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == opposite,
                Order.order_type == OrderType.ASK,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price <= mirror_threshold,
                Order.id != taker.id,
            )
            .order_by(Order.price.asc(), Order.created_at.asc())
            .limit(1)
        )
    else:
        # Taker is selling: find the highest bid (direct or mirror)
        direct_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == taker.position,
                Order.order_type == OrderType.BID,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price >= taker.price,
                Order.id != taker.id,
            )
            .order_by(Order.price.desc(), Order.created_at.asc())
            .limit(1)
        )
        mirror_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == opposite,
                Order.order_type == OrderType.BID,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price >= mirror_threshold,
                Order.id != taker.id,
            )
            .order_by(Order.price.desc(), Order.created_at.asc())
            .limit(1)
        )

    direct = (await session.execute(direct_q)).scalar_one_or_none()
    mirror = (await session.execute(mirror_q)).scalar_one_or_none()

    if direct is None:
        return mirror
    if mirror is None:
        return direct

    # Both available: pick the one giving taker the best effective price
    if taker.order_type == OrderType.BID:
        # Lower effective price is better for buyer
        # Direct: taker pays direct.price
        # Mirror: taker pays (100 - mirror.price) in YES-equivalent
        direct_eff = direct.price
        mirror_eff = 100 - mirror.price
        return direct if direct_eff <= mirror_eff else mirror
    else:
        # Higher effective price is better for seller
        # Direct: taker receives direct.price
        # Mirror: taker receives (100 - mirror.price) in YES-equivalent
        direct_eff = direct.price
        mirror_eff = 100 - mirror.price
        return direct if direct_eff >= mirror_eff else mirror


async def _upsert_position(
    session: AsyncSession,
    user_id: int,
    market_id: int,
    side: PositionSide,
    qty: int,
    price: int,
    is_buy: bool,
) -> None:
    """Create or update a user's position after a trade."""
    result = await session.execute(
        select(Position).where(
            Position.user_id == user_id,
            Position.market_id == market_id,
            Position.position == side,
        )
    )
    pos = result.scalar_one_or_none()

    if is_buy:
        if pos is None:
            session.add(Position(
                user_id=user_id,
                market_id=market_id,
                position=side,
                quantity=qty,
                avg_price=price,
            ))
        else:
            total = pos.quantity + qty
            pos.avg_price = (pos.avg_price * pos.quantity + price * qty) // total
            pos.quantity = total
    else:
        if pos is not None:
            pos.quantity -= qty
            # avg_price unchanged when selling


async def _get_user_locked(
    session: AsyncSession,
    user_id: int,
) -> User:
    """Fetch user row with SELECT FOR UPDATE."""
    result = await session.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    return result.scalar_one()


async def match_order(session: AsyncSession, order_id: int) -> None:
    """
    Main matching loop. Called sequentially by the per-market queue worker.

    Concurrency model:
    - Single worker per market: Order rows need no locks (serialized access).
    - User rows locked with SELECT FOR UPDATE to prevent double-spending.
    """
    res = await session.execute(select(Order).where(Order.id == order_id))
    taker = res.scalar_one_or_none()
    if taker is None or taker.status not in ACTIVE_STATUSES:
        return

    while taker.remaining_quantity > 0:
        maker = await _find_best_maker(session, taker)
        if maker is None:
            break

        is_mirror = taker.position != maker.position
        fill_qty = min(taker.remaining_quantity, maker.remaining_quantity)

        # Effective trade prices from each side's perspective:
        # Direct match: both sides trade at maker.price
        # Mirror match: taker pays/receives (100 - maker.price), maker pays/receives maker.price
        if is_mirror:
            # e.g. YES BID(70) vs NO ASK(30): taker_trade_price=70, maker_trade_price=30
            # e.g. YES ASK(30) vs NO BID(70): taker_trade_price=30, maker_trade_price=70
            taker_trade_price = 100 - maker.price
            maker_trade_price = maker.price
        else:
            taker_trade_price = maker.price
            maker_trade_price = maker.price

        # Record trade with the taker's effective price (from taker's position perspective)
        trade = Trade(
            market_id=taker.market_id,
            maker_order_id=maker.id,
            taker_order_id=taker.id,
            position=taker.position,
            price=taker_trade_price,
            quantity=fill_qty,
        )
        session.add(trade)

        # Identify buyer and seller
        if taker.order_type == OrderType.BID:
            buyer_order = taker
            buyer_bid_price = taker.price  # price buyer locked per unit
            buyer_trade_price = taker_trade_price  # actual cost per unit
            seller_order = maker
            seller_receive_price = maker_trade_price  # what seller receives per unit
        else:
            buyer_order = maker
            buyer_bid_price = maker.price  # price maker (BID) locked per unit
            buyer_trade_price = maker_trade_price  # actual cost per unit
            seller_order = taker
            seller_receive_price = taker_trade_price  # what taker (ASK) receives per unit

        # Lock user rows - handle same-user case
        buyer_user = await _get_user_locked(session, buyer_order.user_id)
        if seller_order.user_id != buyer_order.user_id:
            seller_user = await _get_user_locked(session, seller_order.user_id)
        else:
            seller_user = buyer_user

        # --- Apply point transfers ---

        # Buyer (BID order):
        # - Had locked bid_price * qty at order creation (total_points unchanged then)
        # - Now trade happens: total_points -= buyer_trade_price * fill_qty
        # - Release locked: locked_points -= buyer_bid_price * fill_qty
        # - Refund excess to available: available_points += (buyer_bid_price - buyer_trade_price) * fill_qty
        buyer_cost = buyer_trade_price * fill_qty
        buyer_locked_release = buyer_bid_price * fill_qty
        buyer_excess_refund = buyer_locked_release - buyer_cost  # >= 0 always

        buyer_user.total_points -= buyer_cost
        buyer_order.locked_points -= buyer_locked_release
        if buyer_excess_refund > 0:
            buyer_user.available_points += buyer_excess_refund

        # Seller (ASK order):
        # - Gets seller_receive_price * fill_qty added to both available and total
        seller_income = seller_receive_price * fill_qty
        seller_user.total_points += seller_income
        seller_user.available_points += seller_income

        # --- Update positions ---
        # Buyer gets position in buyer_order.position (their side)
        # Seller loses position in seller_order.position (their side)
        await _upsert_position(
            session,
            buyer_order.user_id,
            taker.market_id,
            buyer_order.position,
            fill_qty,
            buyer_trade_price,
            is_buy=True,
        )
        await _upsert_position(
            session,
            seller_order.user_id,
            taker.market_id,
            seller_order.position,
            fill_qty,
            seller_receive_price,
            is_buy=False,
        )

        # --- Update order statuses ---
        maker.remaining_quantity -= fill_qty
        maker.status = OrderStatus.FILLED if maker.remaining_quantity == 0 else OrderStatus.PARTIAL

        taker.remaining_quantity -= fill_qty
        taker.status = OrderStatus.FILLED if taker.remaining_quantity == 0 else OrderStatus.PARTIAL

        await session.flush()

    await session.commit()


async def cancel_order(session: AsyncSession, order_id: int) -> None:
    """
    Cancel an open/partial order and return locked points to available.
    Called by the queue worker when a cancel message is received.
    """
    res = await session.execute(select(Order).where(Order.id == order_id))
    order = res.scalar_one_or_none()
    if order is None or order.status not in ACTIVE_STATUSES:
        return

    if order.order_type == OrderType.BID and order.locked_points > 0:
        user_res = await session.execute(
            select(User).where(User.id == order.user_id).with_for_update()
        )
        user = user_res.scalar_one()
        # Return locked points to available (total_points unchanged - they were never deducted)
        user.available_points += order.locked_points
        order.locked_points = 0

    order.status = OrderStatus.CANCELLED
    await session.commit()
