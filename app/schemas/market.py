from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.market import MarketResult, MarketStatus


class MarketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    closes_at: datetime


class MarketResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    closes_at: datetime
    status: MarketStatus
    result: Optional[MarketResult]
    created_by: int
    created_at: datetime
    resolved_at: Optional[datetime]
    last_trade_price: Optional[int] = None

    class Config:
        from_attributes = True


class MarketResolve(BaseModel):
    result: MarketResult
