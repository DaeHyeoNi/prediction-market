from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus, OrderType, PositionSide


async def get_orderbook_snapshot(db: AsyncSession, market_id: int) -> dict:
    """
    Returns the orderbook with both direct and mirror orders combined.
    YES price P corresponds to NO price (100 - P).
    """
    active_statuses = (OrderStatus.OPEN, OrderStatus.PARTIAL)

    # YES BIDs (buyers of YES)
    yes_bids_result = await db.execute(
        select(Order.price, Order.remaining_quantity)
        .where(
            Order.market_id == market_id,
            Order.position == PositionSide.YES,
            Order.order_type == OrderType.BID,
            Order.status.in_(active_statuses),
        )
        .order_by(Order.price.desc(), Order.created_at.asc())
    )
    yes_bids_raw = yes_bids_result.all()

    # YES ASKs (sellers of YES)
    yes_asks_result = await db.execute(
        select(Order.price, Order.remaining_quantity)
        .where(
            Order.market_id == market_id,
            Order.position == PositionSide.YES,
            Order.order_type == OrderType.ASK,
            Order.status.in_(active_statuses),
        )
        .order_by(Order.price.asc(), Order.created_at.asc())
    )
    yes_asks_raw = yes_asks_result.all()

    # NO BIDs shown as YES ASKs at price (100 - no_bid_price)
    no_bids_result = await db.execute(
        select(Order.price, Order.remaining_quantity)
        .where(
            Order.market_id == market_id,
            Order.position == PositionSide.NO,
            Order.order_type == OrderType.BID,
            Order.status.in_(active_statuses),
        )
        .order_by(Order.price.desc(), Order.created_at.asc())
    )
    no_bids_raw = no_bids_result.all()

    # NO ASKs shown as YES BIDs at price (100 - no_ask_price)
    no_asks_result = await db.execute(
        select(Order.price, Order.remaining_quantity)
        .where(
            Order.market_id == market_id,
            Order.position == PositionSide.NO,
            Order.order_type == OrderType.ASK,
            Order.status.in_(active_statuses),
        )
        .order_by(Order.price.asc(), Order.created_at.asc())
    )
    no_asks_raw = no_asks_result.all()

    # Aggregate YES BIDs (direct YES BIDs + mirror of NO ASKs)
    yes_bid_levels: dict[int, int] = {}
    for price, qty in yes_bids_raw:
        yes_bid_levels[price] = yes_bid_levels.get(price, 0) + qty
    for price, qty in no_asks_raw:
        mirror_price = 100 - price
        yes_bid_levels[mirror_price] = yes_bid_levels.get(mirror_price, 0) + qty

    # Aggregate YES ASKs (direct YES ASKs + mirror of NO BIDs)
    yes_ask_levels: dict[int, int] = {}
    for price, qty in yes_asks_raw:
        yes_ask_levels[price] = yes_ask_levels.get(price, 0) + qty
    for price, qty in no_bids_raw:
        mirror_price = 100 - price
        yes_ask_levels[mirror_price] = yes_ask_levels.get(mirror_price, 0) + qty

    return {
        "market_id": market_id,
        "yes_bids": [
            {"price": p, "quantity": q}
            for p, q in sorted(yes_bid_levels.items(), reverse=True)
        ],
        "yes_asks": [
            {"price": p, "quantity": q}
            for p, q in sorted(yes_ask_levels.items())
        ],
    }
