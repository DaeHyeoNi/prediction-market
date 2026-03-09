"""
Per-market Redis Queue worker.

Each market has its own asyncio task consuming from market_queue:{market_id}.
Single consumer per queue ensures serialized order processing (no race conditions
on Order rows). User rows still use SELECT FOR UPDATE for point integrity.
"""

import asyncio
import json
import logging

import redis.asyncio as aioredis

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.engine.matching import cancel_order, match_order

logger = logging.getLogger(__name__)


class MarketWorkerManager:
    def __init__(self):
        self._tasks: dict[int, asyncio.Task] = {}

    async def start(self):
        """Initialize the worker manager."""
        logger.info("MarketWorkerManager started")

    async def stop(self):
        """Gracefully stop all market workers."""
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("All market workers stopped")

    async def start_market_worker(self, market_id: int) -> None:
        """Start a worker for a specific market if not already running."""
        existing = self._tasks.get(market_id)
        if existing is not None and not existing.done():
            return

        task = asyncio.create_task(
            self._run_market_worker(market_id),
            name=f"market_worker_{market_id}",
        )
        self._tasks[market_id] = task
        logger.info(f"Started worker for market {market_id}")

    async def stop_market_worker(self, market_id: int) -> None:
        """Stop the worker for a specific market."""
        task = self._tasks.get(market_id)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        del self._tasks[market_id]
        logger.info(f"Stopped worker for market {market_id}")

    async def _run_market_worker(self, market_id: int) -> None:
        """
        Blocking loop: reads messages from Redis queue and processes them one by one.
        This guarantees serialized access to Order rows for the given market.
        """
        redis_client = aioredis.from_url(settings.REDIS_URL)
        queue_key = f"market_queue:{market_id}"
        logger.info(f"Worker for market {market_id} listening on {queue_key}")

        try:
            while True:
                try:
                    # Block for up to 5 seconds waiting for a message
                    result = await redis_client.blpop(queue_key, timeout=5)
                    if result is None:
                        # Timeout - loop back and wait again
                        continue

                    _, raw = result
                    msg = json.loads(raw)
                    msg_type = msg.get("type")
                    order_id = msg.get("order_id")

                    async with AsyncSessionLocal() as session:
                        try:
                            if msg_type == "order":
                                await match_order(session, order_id)
                            elif msg_type == "cancel":
                                await cancel_order(session, order_id)
                            else:
                                logger.warning(
                                    f"Unknown message type '{msg_type}' for market {market_id}"
                                )
                        except Exception as e:
                            logger.error(
                                f"Error processing {msg_type} order_id={order_id} "
                                f"for market {market_id}: {e}",
                                exc_info=True,
                            )
                            await session.rollback()

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(
                        f"Unexpected error in worker for market {market_id}: {e}",
                        exc_info=True,
                    )
                    await asyncio.sleep(1)
        finally:
            await redis_client.aclose()
            logger.info(f"Worker for market {market_id} stopped")


# Module-level singleton used by routers and lifespan
worker_manager = MarketWorkerManager()
