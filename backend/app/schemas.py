"""Read contracts: Decimal values serialize as exact strings, timestamps as UTC."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer
from pydantic import Field, field_validator


class TimestampResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", check_fields=False)
    def serialize_timestamp(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class SelectionResponse(TimestampResponse):
    id: UUID
    market_id: UUID
    side: str
    line: Decimal | None
    price: Decimal
    is_active: bool
    notes: str | None


class MarketResponse(TimestampResponse):
    id: UUID
    game_id: UUID
    type: str
    status: str
    description: str | None
    selections: list[SelectionResponse]


class GameResponse(TimestampResponse):
    id: UUID
    season: int
    week: int
    home_team: str
    away_team: str
    start_time: datetime
    status: str
    home_score: int | None
    away_score: int | None
    venue: str | None
    notes: str | None
    markets: list[MarketResponse]

    @field_serializer("start_time")
    def serialize_start_time(self, value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()


class StrategyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=255)
    type: Literal["random"] = "random"
    description: str | None = None
    is_active: bool = True
    config: dict | None = None

    @field_validator("config")
    @classmethod
    def validate_config(cls, value):
        if value:
            raise ValueError("Random Strategy accepts only null or empty configuration")
        return value


class StrategyResponse(TimestampResponse):
    id: UUID
    name: str
    type: Literal["random"]
    description: str | None
    is_active: bool
    config: dict | None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game_ids: list[UUID] = Field(min_length=1)

    @field_validator("game_ids")
    @classmethod
    def unique_games(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("game_ids must be distinct")
        return value


class QuoteProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)
    observation_id: UUID
    bookmaker: str
    source_timestamp: datetime | None
    fetched_at: datetime


class BetDecision(BaseModel):
    model_config = ConfigDict(frozen=True)
    game_id: UUID
    market_id: UUID
    selection_id: UUID
    side: str
    line: Decimal
    price: Decimal
    quote_provenance: QuoteProvenance | None = None


class SkippedGame(BaseModel):
    game_id: UUID
    reason: Literal["game_not_scheduled", "kickoff_reached", "spread_unavailable"]


class DecisionResponse(BaseModel):
    strategy_id: UUID
    generated_at: datetime
    requested_game_ids: list[UUID]
    decisions: list[BetDecision]
    skipped_games: list[SkippedGame]


class RunCreate(DecisionRequest):
    strategy_id: UUID
    starting_bankroll: str
    stake_per_bet: str
    name: str | None = Field(default=None, max_length=255)
    notes: str | None = None

    @field_validator("starting_bankroll", "stake_per_bet")
    @classmethod
    def money(cls, value):
        import re
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
            raise ValueError("Use a positive exact decimal string with at most two decimal places")
        amount = Decimal(value)
        if not 0 < amount <= Decimal("9999999999.99"):
            raise ValueError("Amount exceeds Numeric(12,2) limits")
        return format(amount, ".2f")

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if value is not None:
            value = value.strip()
            if not value:
                raise ValueError("Name must not be blank")
        return value


class RunResponse(TimestampResponse):
    id: UUID
    user_id: UUID
    strategy_id: UUID
    name: str | None
    notes: str | None
    status: str
    starting_bankroll: Decimal
    stake_per_bet: Decimal
    start_time: datetime
    end_time: datetime | None
    final_bankroll: Decimal | None
    total_profit: Decimal | None
    roi: Decimal | None
    game_ids: list[UUID]
    bet_count: int
    committed_stake: Decimal
    available_bankroll: Decimal
    skipped_games: list[SkippedGame]

    @field_serializer("start_time", "end_time")
    def utc_times(self, value):
        return value.astimezone(timezone.utc).isoformat() if value is not None else None


class BetResponse(TimestampResponse):
    id: UUID
    run_id: UUID
    selection_id: UUID
    game_id: UUID
    market_id: UUID
    side: str
    line: Decimal
    home_team: str
    away_team: str
    kickoff_at_placement: datetime
    stake: Decimal
    price: Decimal
    status: str
    result: str | None
    profit: Decimal | None
    placed_at: datetime
    settled_at: datetime | None
    quote_provenance: QuoteProvenance | None

    @field_serializer("kickoff_at_placement", "placed_at", "settled_at")
    def utc_times(self, value):
        return value.astimezone(timezone.utc).isoformat() if value is not None else None


class RunCreationResponse(BaseModel):
    run: RunResponse
    bets: list[BetResponse]
    skipped_games: list[SkippedGame]
