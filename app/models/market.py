import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MarketStatus(str, enum.Enum):
    OPEN = "Open"
    CLOSED = "Closed"
    RESOLVED = "Resolved"


class MarketResult(str, enum.Enum):
    YES = "YES"
    NO = "NO"


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[MarketStatus] = mapped_column(
        Enum(MarketStatus), default=MarketStatus.OPEN, nullable=False
    )
    result: Mapped[MarketResult | None] = mapped_column(Enum(MarketResult), nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    orders: Mapped[list["Order"]] = relationship(back_populates="market")
    positions: Mapped[list["Position"]] = relationship(back_populates="market")
    trades: Mapped[list["Trade"]] = relationship(back_populates="market")
