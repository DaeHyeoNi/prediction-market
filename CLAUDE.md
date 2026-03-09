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
uv run pytest tests/                                    # All tests (requires test DB: prediction_market_test)
uv run pytest tests/test_matching.py -k "test_direct"   # Single test by name
uv run pytest tests/test_matching.py::test_partial_fill  # Single test by path
```

## Architecture

**Request → Queue → Worker** pipeline:
1. `POST /orders` validates market/user, locks margin (BID), creates Order in DB, returns **202 Accepted**
2. Order ID pushed to Redis `market_queue:{market_id}`
3. Per-market asyncio worker (started in FastAPI lifespan) pops from queue and runs `match_order()`
4. Cancellations also go through the queue to maintain serialization

**Concurrency model**: Each market has exactly one queue consumer — no DB locks on Order rows needed. Only User rows use `SELECT FOR UPDATE` for point integrity across markets.

**Double orderbook**: YES and NO sides share a single orderbook via `YES_PRICE + NO_PRICE = 100`. No mirror order rows are created; matching queries use arithmetic conditions to find cross-side matches (e.g., YES BID at 70 matches NO ASK at ≤30).

**Two DB session types**: Async (`asyncpg`) for API + queue workers in `app/db/session.py`, sync (`psycopg2`) for Celery tasks in `app/db/sync_session.py`.

**Point flow** (defined in `app/engine/matching.py` docstring):
- BID creation: `available_points -= price * qty`, `total_points` unchanged
- BID fill: `total_points -= trade_price * fill`, refund excess `(bid_price - trade_price) * fill` to `available_points`
- ASK fill: both `total_points` and `available_points` increase by `trade_price * fill`
- Cancel: return `locked_points` to `available_points`

## Key Constraints

- Order price: 1–99 (CheckConstraint `ck_orders_price_range`)
- ASK orders require sufficient position quantity (short-selling prevented)
- Position uniqueness: one row per (user, market, position_side)
- Settlement is idempotent and processes winners in 500-record chunks
