from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.order import PositionSide, _enum_values


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    market_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("markets.id"), nullable=False)
    maker_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False)
    taker_order_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("orders.id"), nullable=False)
    position: Mapped[PositionSide] = mapped_column(Enum(PositionSide, values_callable=_enum_values), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    market: Mapped["Market"] = relationship(back_populates="trades")
    maker_order: Mapped["Order"] = relationship(
        foreign_keys=[maker_order_id], back_populates="maker_trades"
    )
    taker_order: Mapped["Order"] = relationship(
        foreign_keys=[taker_order_id], back_populates="taker_trades"
    )
