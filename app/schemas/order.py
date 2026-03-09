from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models.order import OrderStatus, OrderType, PositionSide


class OrderCreate(BaseModel):
    market_id: int
    position: PositionSide
    order_type: OrderType
    price: int
    quantity: int

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if not 1 <= v <= 99:
            raise ValueError("Price must be between 1 and 99")
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class OrderResponse(BaseModel):
    id: int
    user_id: int
    market_id: int
    position: PositionSide
    order_type: OrderType
    price: int
    quantity: int
    remaining_quantity: int
    status: OrderStatus
    locked_points: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
