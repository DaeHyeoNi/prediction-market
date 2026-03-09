from fastapi import APIRouter, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.position import Position
from app.models.user import User
from app.schemas.position import PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionResponse])
async def list_positions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Position).where(
            Position.user_id == current_user.id,
            Position.quantity > 0,
        )
    )
    return result.scalars().all()
