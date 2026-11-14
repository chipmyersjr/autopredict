"""On-demand provider primitives; no calls, caches, or jobs run on import.

Admission and durable call reservations belong to the refresh service. It must
reserve each call before invoking these methods, including calendar and info.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from time import monotonic
from typing import Literal
from zoneinfo import ZoneInfo

import httpx

from app.settings import Settings

PACIFIC = ZoneInfo("America/Los_Angeles")
WEEKLY_ATTEMPTS = 20
SUNDAY_RESERVED = 2
COOLDOWN_SECONDS = 60
CFBD_FREE_CALLS = 1000
ODDS_FREE_CREDITS = 500
PROVIDER_RESERVE = Decimal("0.10")
REFRESH_SECONDS = 45


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An aware timestamp is required")
    return value


@dataclass(frozen=True)
class WeekWindow:
    start: datetime
    end: datetime

    def contains(self, kickoff: datetime) -> bool:
        return self.start <= aware(kickoff) < self.end

    @property
    def calendar_years(self) -> tuple[int, ...]:
        # Prior season is a calendar lookup candidate, never an inferred season.
        first = self.start.astimezone(PACIFIC).year
        last = (self.end.astimezone(PACIFIC) - timedelta(microseconds=1)).year
        return tuple(range(first - 1, last + 1))


def current_week(now: datetime) -> WeekWindow:
    local = aware(now).astimezone(PACIFIC)
    monday = local.date() - timedelta(days=local.weekday())
    return WeekWindow(
        datetime.combine(monday, time.min, PACIFIC).astimezone(UTC),
        datetime.combine(monday + timedelta(days=7), time.min, PACIFIC).astimezone(UTC),
    )


@dataclass(frozen=True)
class CalendarWeek:
    season: int
    season_type: Literal["regular", "postseason"]
    week: int
    start: datetime
    end: datetime

    def __post_init__(self):
        if (self.season_type not in {"regular", "postseason"} or self.week < 1
                or aware(self.start) >= aware(self.end)):
            raise ValueError("Invalid provider calendar week")


def overlapping_weeks(window: WeekWindow, calendar: list[CalendarWeek]) -> list[CalendarWeek]:
    """Select explicit provider windows; callers still filter individual kickoffs."""
    return sorted(
        {entry for entry in calendar if entry.start < window.end and entry.end > window.start},
        key=lambda entry: (entry.season, entry.season_type, entry.week),
    )


class ProviderError(Exception):
    """Safe failure without request URLs, response bodies, or underlying errors."""

    def __init__(self, reason: str, status: int | None = None, *, quota=None):
        self.reason = reason
        self.status = status
        self.quota = quota or {}
        super().__init__(reason)


class _CredentialFilter(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = re.sub(r"(?i)(apiKey=)[^&\s\"']+", r"\1[REDACTED]", message)
        message = re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[REDACTED]", message)
        record.msg, record.args = message, ()
        return True


# HTTPX logs request URLs at INFO, including the Odds API query credential.
logging.getLogger("httpx").addFilter(_CredentialFilter())
logging.getLogger("httpcore").addFilter(_CredentialFilter())


class ProviderClients:
    """Fixed free-access endpoints, no redirects/retries, one shared deadline.

    Use as an async context manager inside an admitted refresh. Calendar caching
    is owned by the later persistence/service layer, never by startup/read code.
    """

    def __init__(self, settings: Settings, *, transport=None, clock=monotonic):
        self._settings = settings
        self._clock = clock
        self._expires = clock() + REFRESH_SECONDS
        self._client = httpx.AsyncClient(
            transport=transport or httpx.AsyncHTTPTransport(retries=0),
            follow_redirects=False, trust_env=False, timeout=10,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get(self, provider: str, path: str, params: dict):
        key = (self._settings.cfbd_api_key if provider == "cfbd"
               else self._settings.odds_api_key).get_secret_value()
        if not key.strip():
            raise ProviderError("configuration_error")
        remaining = self._expires - self._clock()
        if remaining <= 0:
            raise ProviderError("deadline_exceeded")
        headers = {}
        params = dict(params)
        if provider == "cfbd":
            host = "https://api.collegefootballdata.com"
            headers["Authorization"] = f"Bearer {key}"
        else:
            host = "https://api.the-odds-api.com"
            params["apiKey"] = key
        reason = None
        status = None
        quota = {}
        try:
            async with asyncio.timeout(remaining):
                response = await self._client.get(
                    host + path, params=params, headers=headers,
                    timeout=httpx.Timeout(min(10, remaining), connect=min(3, remaining)),
                )
                status = response.status_code
                # Error responses can carry authoritative spending and throttle
                # metadata too. Retain only these headers, never the response.
                quota = {name: response.headers[name] for name in (
                    "x-requests-remaining", "x-requests-used", "x-requests-last",
                    "retry-after",
                ) if name in response.headers}
                if status in {401, 403}:
                    reason = "configuration_error"
                elif status == 429:
                    reason = "provider_rate_limit"
                elif not 200 <= status < 300:
                    reason = "provider_failure"
                else:
                    return response.json(parse_float=Decimal), quota
        except (httpx.HTTPError, TimeoutError, ValueError):
            reason = "provider_failure"
        # Raise outside the handler so chained transport exceptions cannot leak keys.
        raise ProviderError(reason, status, quota=quota)

    async def calendar(self, season: int):
        rows, quota = await self._get("cfbd", "/calendar", {"year": season})
        try:
            calendar = [CalendarWeek(
                season=season, season_type=row["seasonType"], week=row["week"],
                start=datetime.fromisoformat(row["startDate"]),
                end=datetime.fromisoformat(row["endDate"]),
            ) for row in rows]
        except (KeyError, TypeError, ValueError):
            calendar = None
        if calendar is None:
            raise ProviderError("invalid_calendar")
        return calendar, quota

    async def info(self):
        return await self._get("cfbd", "/info", {})

    async def schedule(self, week: CalendarWeek):
        # Schedule and historical /games payloads differ: normalization must not
        # assume schedule carries historical classification/final-score fields.
        return await self._get("cfbd", "/games/schedule", {
            "year": week.season, "seasonType": week.season_type, "week": week.week,
        })

    async def season_games(self, season: int):
        return await self._get("cfbd", "/games", {"year": season})

    async def odds(self, window: WeekWindow):
        return await self._get("odds", "/v4/sports/americanfootball_ncaaf/odds", {
            "regions": "us", "markets": "spreads", "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": window.start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commenceTimeTo": window.end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
