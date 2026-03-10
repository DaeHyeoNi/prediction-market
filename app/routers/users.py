from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import contains_eager

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.market import Market, MarketStatus
from app.models.order import PositionSide
from app.models.position import Position
from app.models.trade import Trade
from app.models.user import User
from app.schemas.user import Token, UserMeResponse, UserRegister, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        total_points=1_000_000,
        available_points=1_000_000,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.id)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserMeResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 진행 중인 마켓의 포지션만 (OPEN)
    pos_result = await db.execute(
        select(Position)
        .join(Position.market)
        .options(contains_eager(Position.market))
        .where(
            Position.user_id == current_user.id,
            Position.quantity > 0,
            Market.status == MarketStatus.OPEN,
        )
    )
    positions = pos_result.scalars().all()

    portfolio_value = 0
    if positions:
        market_ids = list({p.market_id for p in positions})

        # 마켓별 최근 체결가 조회 (단일 쿼리)
        ranked = (
            select(
                Trade.market_id,
                Trade.position,
                Trade.price,
                func.row_number().over(
                    partition_by=Trade.market_id,
                    order_by=Trade.created_at.desc(),
                ).label("rn"),
            )
            .where(Trade.market_id.in_(market_ids))
            .subquery()
        )
        last_trades = (await db.execute(
            select(ranked.c.market_id, ranked.c.position, ranked.c.price)
            .where(ranked.c.rn == 1)
        )).all()

        # YES 기준 가격으로 통일
        last_yes_price: dict[int, int] = {}
        for row in last_trades:
            if row.position == PositionSide.YES:
                last_yes_price[row.market_id] = row.price
            else:
                last_yes_price[row.market_id] = 100 - row.price

        for pos in positions:
            yes_price = last_yes_price.get(pos.market_id, pos.avg_price)
            if pos.position == PositionSide.YES:
                portfolio_value += yes_price * pos.quantity
            else:
                portfolio_value += (100 - yes_price) * pos.quantity

    locked_points = current_user.total_points - current_user.available_points

    return UserMeResponse(
        id=current_user.id,
        username=current_user.username,
        total_points=current_user.total_points,
        available_points=current_user.available_points,
        locked_points=locked_points,
        portfolio_value=portfolio_value,
        total_wealth=current_user.total_points + portfolio_value,
    )
