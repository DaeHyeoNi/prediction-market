import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PositionSide(str, enum.Enum):
    YES = "YES"
    NO = "NO"


class OrderType(str, enum.Enum):
    BID = "Bid"
    ASK = "Ask"


class OrderStatus(str, enum.Enum):
    PENDING = "Pending"
    OPEN = "Open"
    PARTIAL = "Partial"
    FILLED = "Filled"
    CANCELLED = "Cancelled"


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("price >= 1 AND price <= 99", name="ck_orders_price_range"),
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint("remaining_quantity >= 0", name="ck_orders_remaining_non_negative"),
        CheckConstraint("locked_points >= 0", name="ck_orders_locked_points_non_negative"),
        Index(
            "ix_orders_book",
            "market_id",
            "position",
            "order_type",
            "status",
            "price",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("markets.id"), nullable=False)
    position: Mapped[PositionSide] = mapped_column(Enum(PositionSide, values_callable=_enum_values), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType, values_callable=_enum_values), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    remaining_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, values_callable=_enum_values), default=OrderStatus.PENDING, nullable=False
    )
    locked_points: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="orders")
    market: Mapped["Market"] = relationship(back_populates="orders")
    maker_trades: Mapped[list["Trade"]] = relationship(
        foreign_keys="Trade.maker_order_id", back_populates="maker_order"
    )
    taker_trades: Mapped[list["Trade"]] = relationship(
        foreign_keys="Trade.taker_order_id", back_populates="taker_order"
    )
