import json
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.future import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.engine.queue_worker import worker_manager
from app.models.market import Market, MarketStatus
from app.models.order import Order, OrderStatus
from app.routers import admin, markets, orders, positions, users
from app.tasks.beat_schedule import *  # noqa: F401, F403 - register beat schedule

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize the worker manager and restart workers for all open markets
    await worker_manager.start()

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Market).where(Market.status == MarketStatus.OPEN)
        )
        open_markets = result.scalars().all()
        for market in open_markets:
            await worker_manager.start_market_worker(market.id)

        # Re-queue any Open/Partial orders that survived a Redis restart
        pending_result = await session.execute(
            select(Order).where(
                Order.market_id.in_([m.id for m in open_markets]),
                Order.status.in_([OrderStatus.OPEN, OrderStatus.PARTIAL]),
            ).order_by(Order.created_at.asc())
        )
        pending_orders = pending_result.scalars().all()

        print(f"[startup] open_markets={[m.id for m in open_markets]}, pending_orders={len(pending_orders)}")
        if pending_orders:
            redis_client = aioredis.from_url(settings.REDIS_URL)
            try:
                for order in pending_orders:
                    await redis_client.rpush(
                        f"market_queue:{order.market_id}",
                        json.dumps({"type": "order", "order_id": order.id}),
                    )
                print(f"[startup] Re-queued {len(pending_orders)} pending orders")
            finally:
                await redis_client.aclose()

    yield

    # Shutdown: stop all workers gracefully
    await worker_manager.stop()


app = FastAPI(title="Prediction Market API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(markets.router)
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
