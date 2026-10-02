"""Canonical games and spreads; schema changes are managed by Alembic."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Game(Timestamps, Base):
    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint("status IN ('scheduled', 'in_progress', 'completed', 'canceled')", name="ck_games_status"),
        CheckConstraint("home_score >= 0", name="ck_games_home_score"),
        CheckConstraint("away_score >= 0", name="ck_games_away_score"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    home_team: Mapped[str] = mapped_column(String(255))
    away_team: Mapped[str] = mapped_column(String(255))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(50))
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    markets: Mapped[list["Market"]] = relationship(back_populates="game", order_by="Market.id")


class Market(Timestamps, Base):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint("type = 'spread'", name="ck_markets_type"),
        CheckConstraint("status IN ('active', 'closed', 'settled')", name="ck_markets_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    game: Mapped[Game] = relationship(back_populates="markets")
    selections: Mapped[list["Selection"]] = relationship(back_populates="market", order_by="Selection.id")


class Selection(Timestamps, Base):
    __tablename__ = "selections"
    __table_args__ = (CheckConstraint("price > 1", name="ck_selections_price"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id"), index=True)
    side: Mapped[str] = mapped_column(String(100))
    line: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    market: Mapped[Market] = relationship(back_populates="selections")
