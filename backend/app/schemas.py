"""Read contracts: Decimal values serialize as exact strings, timestamps as UTC."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


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
