import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingress import CalendarWeek, ProviderClients, ProviderError, current_week, overlapping_weeks
from app.settings import Settings


def stamp(value):
    return datetime.fromisoformat(value)


@pytest.mark.parametrize("now,start,end,hours", [
    ("2026-03-08T23:00:00-07:00", "2026-03-02T08:00:00+00:00", "2026-03-09T07:00:00+00:00", 167),
    ("2026-11-01T23:00:00-08:00", "2026-10-26T07:00:00+00:00", "2026-11-02T08:00:00+00:00", 169),
    ("2026-10-05T00:00:00-07:00", "2026-10-05T07:00:00+00:00", "2026-10-12T07:00:00+00:00", 168),
])
def test_pacific_calendar_boundaries(now, start, end, hours):
    window = current_week(stamp(now))
    assert (window.start, window.end) == (stamp(start), stamp(end))
    assert window.end - window.start == timedelta(hours=hours)
    assert window.contains(window.start)
    assert window.contains(window.end - timedelta(microseconds=1))
    assert not window.contains(window.end)


def test_january_resolves_prior_season_from_calendar():
    window = current_week(stamp("2027-01-02T12:00:00+00:00"))
    assert window.calendar_years == (2025, 2026, 2027)
    postseason = CalendarWeek(2026, "postseason", 2, stamp("2026-12-30T00:00:00Z"), stamp("2027-01-05T00:00:00Z"))
    excluded = CalendarWeek(2027, "regular", 1, window.end, window.end + timedelta(days=7))
    assert overlapping_weeks(window, [excluded, postseason, postseason]) == [postseason]


def test_naive_clock_rejected():
    with pytest.raises(ValueError):
        current_week(datetime(2026, 1, 1))


def test_provider_calendar_postseason_contract():
    def handler(request):
        return httpx.Response(200, json=[{
            "seasonType": "postseason", "week": 3,
            "startDate": "2027-01-01T00:00:00Z", "endDate": "2027-01-08T00:00:00Z",
        }])

    async def run():
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key="secret"), transport=httpx.MockTransport(handler)) as clients:
            calendar, _ = await clients.calendar(2026)
            matched = overlapping_weeks(current_week(stamp("2027-01-02T12:00:00Z")), calendar)
            assert [(week.season, week.week, week.season_type) for week in matched] == [(2026, 3, "postseason")]
    asyncio.run(run())


def test_explicit_authenticated_contracts_and_redaction(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[], headers={"x-requests-remaining": "499"})

    async def run():
        settings = Settings(_env_file=None, cfbd_api_key="cfbd-secret", odds_api_key="odds-secret")
        assert "cfbd-secret" not in repr(settings)
        async with ProviderClients(settings, transport=httpx.MockTransport(handler)) as clients:
            assert requests == []
            await clients.calendar(2026)
            await clients.info()
            await clients.schedule(CalendarWeek(2026, "postseason", 2, datetime(2026, 12, 28, tzinfo=UTC), datetime(2027, 1, 4, tzinfo=UTC)))
            await clients.season_games(2026)
            data, quota = await clients.odds(current_week(datetime(2026, 10, 4, tzinfo=UTC)))
            assert data == [] and quota == {"x-requests-remaining": "499"}

    with caplog.at_level(logging.DEBUG):
        asyncio.run(run())
    assert "odds-secret" not in caplog.text
    assert "cfbd-secret" not in caplog.text
    assert requests[0].headers["Authorization"] == "Bearer cfbd-secret"
    assert dict(requests[0].url.params) == {"year": "2026"}
    assert requests[2].url.params["seasonType"] == "postseason"
    assert requests[-1].url.host == "api.the-odds-api.com"
    assert requests[-1].url.params["apiKey"] == "odds-secret"
    assert requests[-1].url.params["markets"] == "spreads"
    assert requests[-1].url.params["regions"] == "us"


@pytest.mark.parametrize("status,reason", [(302, "provider_failure"), (401, "configuration_error"), (403, "configuration_error"), (429, "provider_rate_limit"), (500, "provider_failure")])
def test_errors_do_not_retry_or_expose_response(status, reason):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="private-key", headers={"location": "https://other.example"})

    async def run():
        async with ProviderClients(Settings(_env_file=None, odds_api_key="private-key"), transport=httpx.MockTransport(handler)) as clients:
            with pytest.raises(ProviderError) as error:
                await clients.odds(current_week(datetime.now(UTC)))
            assert str(error.value) == reason
            assert error.value.__context__ is None
    asyncio.run(run())
    assert len(calls) == 1


def test_missing_credentials_and_total_deadline_do_not_dispatch():
    def handler(request):
        pytest.fail("Unexpected provider request")

    async def run():
        now = [0]
        async with ProviderClients(Settings(_env_file=None), transport=httpx.MockTransport(handler)) as clients:
            with pytest.raises(ProviderError, match="configuration_error"):
                await clients.info()
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key="secret"), transport=httpx.MockTransport(handler), clock=lambda: now[0]) as clients:
            now[0] = 45
            with pytest.raises(ProviderError, match="deadline_exceeded"):
                await clients.info()
    asyncio.run(run())


def test_transport_failure_is_sanitized():
    def handler(request):
        raise httpx.ReadTimeout("secret URL", request=request)

    async def run():
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key="secret"), transport=httpx.MockTransport(handler)) as clients:
            with pytest.raises(ProviderError) as error:
                await clients.info()
            assert str(error.value) == "provider_failure"
            assert error.value.__context__ is None
    asyncio.run(run())


@pytest.mark.parametrize("status", [200, 429, 500])
def test_failed_response_retains_only_accounting_headers(status):
    def handler(request):
        return httpx.Response(status, text="invalid-json-private-body", headers={
            "x-requests-remaining": "50", "x-requests-used": "450",
            "x-requests-last": "1", "retry-after": "120",
            "set-cookie": "private-cookie",
        })

    async def run():
        async with ProviderClients(Settings(_env_file=None, odds_api_key="fake"),
                                   transport=httpx.MockTransport(handler)) as clients:
            with pytest.raises(ProviderError) as error:
                await clients.odds(current_week(datetime.now(UTC)))
            assert error.value.quota == {
                "x-requests-remaining": "50", "x-requests-used": "450",
                "x-requests-last": "1", "retry-after": "120",
            }
            assert error.value.status == status
            assert error.value.__context__ is None
            assert "private" not in str(error.value)
    asyncio.run(run())


def test_total_deadline_bounds_inflight_request():
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    async def run():
        now = [0]
        async with ProviderClients(Settings(_env_file=None, cfbd_api_key="secret"), transport=httpx.MockTransport(handler), clock=lambda: now[0]) as clients:
            now[0] = 44.99
            with pytest.raises(ProviderError, match="provider_failure"):
                await clients.info()
    asyncio.run(run())
    assert len(calls) == 1
