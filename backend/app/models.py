"""Canonical games and spreads; schema changes are managed by Alembic."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Boolean, UniqueConstraint, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import JSONB


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


class Strategy(Timestamps, Base):
    __tablename__ = "strategies"
    __table_args__ = (
        CheckConstraint("type = 'random'", name="ck_strategies_type"),
        CheckConstraint("length(trim(name)) > 0", name="ck_strategies_name"),
        CheckConstraint("config IS NULL OR config = '{}'::jsonb", name="ck_strategies_config"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    config: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class User(Timestamps, Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))


class Run(Timestamps, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_runs_user_request"),
        CheckConstraint("starting_bankroll > 0 AND stake_per_bet > 0", name="ck_runs_money"),
        CheckConstraint("status IN ('open', 'completed')", name="ck_runs_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    strategy_id: Mapped[UUID] = mapped_column(ForeignKey("strategies.id", ondelete="RESTRICT"), index=True)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    request_payload: Mapped[dict] = mapped_column(JSONB)
    name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="open")
    starting_bankroll: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    stake_per_bet: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    final_bankroll: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    roi: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    games: Mapped[list["RunGame"]] = relationship(order_by="RunGame.position")
    bets: Mapped[list["Bet"]] = relationship()


class RunGame(Timestamps, Base):
    __tablename__ = "run_games"
    __table_args__ = (
        UniqueConstraint("run_id", "game_id", name="uq_run_games_game"),
        UniqueConstraint("run_id", "position", name="uq_run_games_position"),
        CheckConstraint("position >= 0", name="ck_run_games_position"),
        CheckConstraint("skip_reason IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable')", name="ck_run_games_skip"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), index=True)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    included_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    position: Mapped[int] = mapped_column(Integer)
    skip_reason: Mapped[str | None] = mapped_column(String(50))


class Bet(Timestamps, Base):
    __tablename__ = "bets"
    __table_args__ = (
        UniqueConstraint("run_id", "game_id", name="uq_bets_run_game"),
        CheckConstraint("stake > 0 AND price > 1", name="ck_bets_money"),
        CheckConstraint("status IN ('open', 'won', 'lost', 'pushed', 'void')", name="ck_bets_status"),
        CheckConstraint("result IN ('won', 'lost', 'pushed', 'void')", name="ck_bets_result"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("runs.id", ondelete="RESTRICT"), index=True)
    selection_id: Mapped[UUID] = mapped_column(ForeignKey("selections.id", ondelete="RESTRICT"), index=True)
    game_id: Mapped[UUID] = mapped_column(ForeignKey("games.id", ondelete="RESTRICT"), index=True)
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"), index=True)
    side: Mapped[str] = mapped_column(String(100))
    line: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    home_team: Mapped[str] = mapped_column(String(255))
    away_team: Mapped[str] = mapped_column(String(255))
    kickoff_at_placement: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    observation_id: Mapped[UUID | None] = mapped_column(Uuid)
    bookmaker: Mapped[str | None] = mapped_column(String(255))
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stake: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    status: Mapped[str] = mapped_column(String(50), default="open")
    result: Mapped[str | None] = mapped_column(String(50))
    profit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
