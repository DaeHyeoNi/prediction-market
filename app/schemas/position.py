from pydantic import BaseModel

from app.models.order import PositionSide


class PositionResponse(BaseModel):
    id: int
    user_id: int
    market_id: int
    position: PositionSide
    quantity: int
    avg_price: int

    class Config:
        from_attributes = True
