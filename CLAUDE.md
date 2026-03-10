# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Infrastructure
docker-compose up -d                                    # Start PostgreSQL 16 + Redis 7

# Database
uv run alembic upgrade head                             # Apply migrations
uv run alembic revision --autogenerate -m "description" # Create new migration

# API Server
uv run uvicorn app.main:app --reload                    # Dev server (queue workers auto-start via lifespan)

# Celery (separate terminal)
uv run celery -A app.tasks.celery_app worker -B --loglevel=info  # Worker + Beat scheduler

# Tests
uv run pytest tests/                                    # All tests (requires DB: prediction_market_test)
uv run pytest tests/test_matching.py -k "test_direct"   # Single test by name
uv run pytest tests/test_matching.py::test_partial_fill  # Single test by path
```

## Environment

Config is loaded from `.env` via `app/config.py` (pydantic-settings). Required vars:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/prediction_market
SYNC_DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/prediction_market
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=change-me-in-production
```

Tests use a hardcoded `prediction_market_test` database (see `tests/conftest.py`).

## Architecture

### Request → Queue → Worker pipeline

1. `POST /orders` validates market/user, locks margin (BID), creates Order in DB, returns **202 Accepted**
2. Order ID pushed to Redis `market_queue:{market_id}` as JSON: `{"type": "order"|"cancel", "order_id": int}`
3. Per-market asyncio worker (started in FastAPI lifespan) pops from queue and runs `match_order()` or `cancel_order()`
4. Cancellations also go through the queue to maintain serialization

### Concurrency model

Each market has exactly one queue consumer (`app/engine/queue_worker.py` → `MarketWorkerManager`). This serializes all order processing per market, so **Order rows need no DB locks**. Only `User` rows use `SELECT FOR UPDATE` to prevent double-spending across markets. Workers start on FastAPI lifespan startup for all `OPEN` markets; `start_market_worker()` is also called from `POST /markets`.

### Double orderbook

YES and NO sides share a single orderbook: `YES_PRICE + NO_PRICE = 100`. No mirror order rows are created. `_find_best_maker()` in `matching.py` queries for both direct and mirror candidates, then picks the best effective price for the taker.

Mirror trade price computation:
- YES BID(70) vs NO ASK(30): taker pays 70, maker receives 30 (70 + 30 = 100)
- The `ix_orders_book` composite index covers `(market_id, position, order_type, status, price, created_at)`

### Two DB session types

- **Async** (`asyncpg`) — API handlers and queue workers: `app/db/session.py`
- **Sync** (`psycopg2`) — Celery tasks only: `app/db/sync_session.py`

Never use the async session in Celery tasks or the sync session in async code.

### SQLAlchemy Enum columns

All `Enum` columns use `values_callable=_enum_values` (defined in `app/models/order.py`) to store string values (`"Bid"`, `"Ask"`, `"YES"`, etc.) instead of Python enum names. This is required for asyncpg compatibility. Follow this pattern for any new Enum columns.

### Celery tasks (`app/tasks/`)

- `close_expired_markets` — Celery Beat, runs every 60s; closes markets past `closes_at`, cancels open orders, returns locked points
- `settle_market(market_id, result)` — triggered by `POST /admin/markets/{id}/resolve`; marks market RESOLVED, pays out 100 pts/unit to winning positions in 500-record chunks; idempotent (safe to retry)

## Point Flow

- **BID creation**: `available_points -= price * qty` (locked); `total_points` unchanged
- **BID fill** at `trade_price ≤ bid_price`: `total_points -= trade_price * fill`; `locked_points -= bid_price * fill`; `available_points += (bid_price - trade_price) * fill` (excess refund)
- **ASK fill**: `total_points += trade_price * fill`; `available_points += trade_price * fill`
- **Cancel**: `available_points += locked_points`; `total_points` unchanged

## Key Constraints

- Order price: 1–99 (`ck_orders_price_range`)
- ASK orders require `position.quantity >= order.quantity` (no short-selling); validated in `POST /orders` before queuing
- Position uniqueness: one row per `(user_id, market_id, position_side)`
- Settlement payout: 100 points per winning unit

## Test Fixtures

`tests/conftest.py` provides two fixtures:
- `db_session` — creates all tables, yields async session, drops all tables after each test
- `client` — wraps `db_session` with `AsyncClient`, overrides `get_db` dependency
