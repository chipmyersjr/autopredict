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
