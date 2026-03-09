from sqlalchemy import BigInteger, Enum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.order import PositionSide


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("user_id", "market_id", "position", name="uq_positions_user_market_pos"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=False)
    market_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("markets.id"), nullable=False)
    position: Mapped[PositionSide] = mapped_column(Enum(PositionSide), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_price: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="positions")
    market: Mapped["Market"] = relationship(back_populates="positions")
