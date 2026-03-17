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

Match rules (3-case model):
    YES BID at B:  YES ASK at p<=B (direct)  OR  NO BID at p>=(100-B) (contract creation)
    YES ASK at A:  YES BID at p>=A (direct)  OR  NO ASK at p<=(100-A) (contract destruction)
    NO BID at B:   NO ASK at p<=B (direct)   OR  YES BID at p>=(100-B) (contract creation)
    NO ASK at A:   NO BID at p>=A (direct)   OR  YES ASK at p<=(100-A) (contract destruction)

Contract creation (BID vs BID, opposite sides):
    YES BID(B_yes) + NO BID(B_no) where B_yes + B_no >= 100 → new contract
    - YES buyer pays: 100 - B_no  (excess refunded if B_yes > 100-B_no)
    - NO buyer pays:  B_no        (maker always pays their bid price)
    - Both receive their respective positions

Contract destruction (ASK vs ASK, opposite sides):
    YES ASK(A_yes) + NO ASK(A_no) where A_yes + A_no <= 100 → destroy contract
    - YES seller receives: 100 - A_no
    - NO seller receives:  A_no
    - Both lose their respective positions; pool releases 100 pts total

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
        # Direct: same position ASK, price <= taker.price (cheapest ask first)
        direct_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == taker.position,
                Order.order_type == OrderType.ASK,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price <= taker.price,
                Order.id != taker.id,
                Order.user_id != taker.user_id,
            )
            .order_by(Order.price.asc(), Order.created_at.asc())
            .limit(1)
        )
        # Contract creation: opposite BID at price >= (100 - taker.price)
        # Higher maker price = lower effective cost for taker (100 - maker.price)
        contract_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == opposite,
                Order.order_type == OrderType.BID,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price >= mirror_threshold,
                Order.id != taker.id,
                Order.user_id != taker.user_id,
            )
            .order_by(Order.price.desc(), Order.created_at.asc())
            .limit(1)
        )
    else:
        # Direct: same position BID, price >= taker.price (highest bid first)
        direct_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == taker.position,
                Order.order_type == OrderType.BID,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price >= taker.price,
                Order.id != taker.id,
                Order.user_id != taker.user_id,
            )
            .order_by(Order.price.desc(), Order.created_at.asc())
            .limit(1)
        )
        # Contract destruction: opposite ASK at price <= (100 - taker.price)
        # Lower maker price = higher effective income for taker (100 - maker.price)
        contract_q = (
            select(Order)
            .where(
                Order.market_id == taker.market_id,
                Order.position == opposite,
                Order.order_type == OrderType.ASK,
                Order.status.in_(ACTIVE_STATUSES),
                Order.price <= mirror_threshold,
                Order.id != taker.id,
                Order.user_id != taker.user_id,
            )
            .order_by(Order.price.asc(), Order.created_at.asc())
            .limit(1)
        )

    direct = (await session.execute(direct_q)).scalar_one_or_none()
    contract = (await session.execute(contract_q)).scalar_one_or_none()

    # Collect candidates with their effective prices and pick the best
    if taker.order_type == OrderType.BID:
        # Lower effective price is better for buyer
        candidates = []
        if direct is not None:
            candidates.append((direct.price, direct.created_at, direct))
        if contract is not None:
            candidates.append((100 - contract.price, contract.created_at, contract))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]
    else:
        # Higher effective price is better for seller
        candidates = []
        if direct is not None:
            candidates.append((direct.price, direct.created_at, direct))
        if contract is not None:
            candidates.append((100 - contract.price, contract.created_at, contract))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (-x[0], x[1]))
        return candidates[0][2]


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

        is_contract_creation = taker.order_type == OrderType.BID and maker.order_type == OrderType.BID
        is_contract_destruction = (
            taker.order_type == OrderType.ASK
            and maker.order_type == OrderType.ASK
            and taker.position != maker.position
        )
        fill_qty = min(taker.remaining_quantity, maker.remaining_quantity)

        # Effective trade prices from each side's perspective:
        # Direct match: both sides trade at maker.price
        # Contract creation/destruction: taker pays/receives (100 - maker.price), maker pays/receives maker.price
        if is_contract_creation or is_contract_destruction:
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

        if is_contract_creation:
            # Contract creation: both sides are BID (buyers), both gain new positions
            # Taker: pays taker_trade_price, locked taker.price → excess refund
            # Maker: pays maker_trade_price (= maker.price), no excess
            taker_user = await _get_user_locked(session, taker.user_id)
            if maker.user_id != taker.user_id:
                maker_user = await _get_user_locked(session, maker.user_id)
            else:
                maker_user = taker_user

            taker_cost = taker_trade_price * fill_qty
            taker_locked_release = taker.price * fill_qty
            taker_excess_refund = taker_locked_release - taker_cost

            taker_user.total_points -= taker_cost
            taker.locked_points -= taker_locked_release
            if taker_excess_refund > 0:
                taker_user.available_points += taker_excess_refund

            maker_cost = maker_trade_price * fill_qty
            maker_locked_release = maker.price * fill_qty
            maker_excess_refund = maker_locked_release - maker_cost

            maker_user.total_points -= maker_cost
            maker.locked_points -= maker_locked_release
            if maker_excess_refund > 0:
                maker_user.available_points += maker_excess_refund

            # Both gain their respective positions
            await _upsert_position(session, taker.user_id, taker.market_id, taker.position, fill_qty, taker_trade_price, is_buy=True)
            await _upsert_position(session, maker.user_id, maker.market_id, maker.position, fill_qty, maker_trade_price, is_buy=True)

        elif is_contract_destruction:
            # Contract destruction: both sides are ASK (sellers), both gain points and lose positions
            # Taker receives (100 - maker.price), maker receives maker.price; total = 100 (pool release)
            taker_user = await _get_user_locked(session, taker.user_id)
            if maker.user_id != taker.user_id:
                maker_user = await _get_user_locked(session, maker.user_id)
            else:
                maker_user = taker_user

            taker_income = taker_trade_price * fill_qty
            maker_income = maker_trade_price * fill_qty

            taker_user.total_points += taker_income
            taker_user.available_points += taker_income

            maker_user.total_points += maker_income
            maker_user.available_points += maker_income

            # Both lose their respective positions
            await _upsert_position(session, taker.user_id, taker.market_id, taker.position, fill_qty, taker_trade_price, is_buy=False)
            await _upsert_position(session, maker.user_id, maker.market_id, maker.position, fill_qty, maker_trade_price, is_buy=False)

        else:
            # Standard BID vs ASK trade: one buyer, one seller
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
