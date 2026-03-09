"""
Celery tasks for market lifecycle management.

Uses synchronous SQLAlchemy (psycopg2) since Celery workers are synchronous.
"""

import logging
from datetime import datetime, timezone

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.market_tasks.close_expired_markets")
def close_expired_markets():
    """
    Periodic task: close markets past their closes_at time and cancel
    all remaining open/partial orders, returning locked points to users.
    """
    from sqlalchemy import select

    from app.db.sync_session import SyncSessionLocal
    from app.models.market import Market, MarketStatus
    from app.models.order import Order, OrderStatus, OrderType
    from app.models.user import User

    with SyncSessionLocal() as session:
        now = datetime.now(timezone.utc)
        result = session.execute(
            select(Market).where(
                Market.closes_at <= now,
                Market.status == MarketStatus.OPEN,
            )
        )
        expired_markets = result.scalars().all()

        for market in expired_markets:
            market.status = MarketStatus.CLOSED

            # Cancel all open/partial orders
            orders_result = session.execute(
                select(Order).where(
                    Order.market_id == market.id,
                    Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
                )
            )
            orders = orders_result.scalars().all()

            for order in orders:
                if order.order_type == OrderType.BID and order.locked_points > 0:
                    user = session.get(User, order.user_id)
                    if user:
                        # Return locked points to available
                        # (total_points unchanged - was never deducted at lock time)
                        user.available_points += order.locked_points
                        order.locked_points = 0
                order.status = OrderStatus.CANCELLED

            session.commit()
            logger.info(
                f"Closed market {market.id}, cancelled {len(orders)} orders"
            )


@celery_app.task(
    name="app.tasks.market_tasks.settle_market",
    bind=True,
    max_retries=3,
)
def settle_market(self, market_id: int, result: str):
    """
    Settle a market: pay out 100 points per unit to winning position holders.
    Processes winners in chunks of 500 for large markets.
    Idempotent: safe to retry if it fails partway through.
    """
    from sqlalchemy import select

    from app.db.sync_session import SyncSessionLocal
    from app.models.market import Market, MarketResult, MarketStatus
    from app.models.order import Order, OrderStatus, OrderType, PositionSide
    from app.models.position import Position
    from app.models.user import User

    try:
        # Step 1: Mark market as resolved (idempotent check)
        with SyncSessionLocal() as session:
            market = session.get(Market, market_id)
            if market is None:
                logger.error(f"Market {market_id} not found for settlement")
                return

            if market.status == MarketStatus.RESOLVED:
                logger.info(f"Market {market_id} already resolved, skipping")
                return

            winning_side = MarketResult(result)
            market.status = MarketStatus.RESOLVED
            market.result = winning_side
            market.resolved_at = datetime.now(timezone.utc)

            # Cancel any remaining open orders
            orders_result = session.execute(
                select(Order).where(
                    Order.market_id == market_id,
                    Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
                )
            )
            remaining_orders = orders_result.scalars().all()
            for order in remaining_orders:
                if order.order_type == OrderType.BID and order.locked_points > 0:
                    user = session.get(User, order.user_id)
                    if user:
                        user.available_points += order.locked_points
                        order.locked_points = 0
                order.status = OrderStatus.CANCELLED

            session.commit()

        # Step 2: Pay out winners in chunks
        winning_position = PositionSide(winning_side.value)
        chunk_size = 500
        offset = 0

        while True:
            with SyncSessionLocal() as session:
                positions_result = session.execute(
                    select(Position).where(
                        Position.market_id == market_id,
                        Position.position == winning_position,
                        Position.quantity > 0,
                    )
                    .offset(offset)
                    .limit(chunk_size)
                )
                positions = positions_result.scalars().all()

                if not positions:
                    break

                for pos in positions:
                    payout = pos.quantity * 100
                    user = session.execute(
                        select(User).where(User.id == pos.user_id).with_for_update()
                    ).scalar_one_or_none()
                    if user:
                        user.total_points += payout
                        user.available_points += payout

                session.commit()
                offset += chunk_size
                logger.info(
                    f"Settled market {market_id}: processed chunk ending at offset {offset}"
                )

        logger.info(f"Market {market_id} fully settled with result={result}")

    except Exception as exc:
        logger.error(f"Error settling market {market_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)
