from typing import Optional

from pydantic import BaseModel, computed_field

from app.models.market import MarketResult, MarketStatus
from app.models.order import PositionSide


class PositionResponse(BaseModel):
    id: int
    user_id: int
    market_id: int
    market_title: str
    market_status: MarketStatus
    market_result: Optional[MarketResult]
    position: PositionSide
    quantity: int
    avg_price: int

    @computed_field
    @property
    def total_cost(self) -> int:
        """Total points spent to acquire this position."""
        return self.avg_price * self.quantity

    @computed_field
    @property
    def payout(self) -> Optional[int]:
        """Payout received at settlement. None if market not resolved."""
        if self.market_status != MarketStatus.RESOLVED:
            return None
        if self.market_result and self.market_result.value == self.position.value:
            return self.quantity * 100
        return 0

    @computed_field
    @property
    def profit(self) -> Optional[int]:
        """Net profit/loss. None if market not resolved."""
        if self.payout is None:
            return None
        return self.payout - self.total_cost

    class Config:
        from_attributes = True


class MarketMyResult(BaseModel):
    market_id: int
    market_title: str
    market_status: MarketStatus
    market_result: Optional[MarketResult]
    positions: list[PositionResponse]
    total_payout: Optional[int]
    total_cost: int
    total_profit: Optional[int]

    class Config:
        from_attributes = True
