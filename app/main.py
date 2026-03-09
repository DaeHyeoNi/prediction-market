from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.future import select

from app.db.session import AsyncSessionLocal
from app.engine.queue_worker import worker_manager
from app.models.market import Market, MarketStatus
from app.routers import admin, markets, orders, positions, users
from app.tasks.beat_schedule import *  # noqa: F401, F403 - register beat schedule


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

    yield

    # Shutdown: stop all workers gracefully
    await worker_manager.stop()


app = FastAPI(title="Prediction Market API", version="0.1.0", lifespan=lifespan)

app.include_router(users.router)
app.include_router(markets.router)
app.include_router(orders.router)
app.include_router(positions.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
