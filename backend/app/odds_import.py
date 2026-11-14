"""Admitted, single-region spread import. No provider work on reads or startup.

Aliases are explicit season-scoped records, never fuzzy name guesses. Initial
matches allow at most five minutes of kickoff drift; established event IDs
follow CFBD rescheduling. Decimal normalization uses ROUND_HALF_UP.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json

from sqlalchemy import select

from app.cfbd_import import identity, name, timestamp
from app.ingress import ProviderError
from app.models import Game, Market, Selection, ProviderGameLink, QuoteObservation, TeamAlias, RefreshRun
from app.odds_aliases import seed_odds_aliases
from app.refresh_admission import AdmissionRejected


def number(value, places, limit):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("invalid_number")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) >= limit:
            raise ValueError("invalid_number")
        result = result.quantize(Decimal(places), rounding=ROUND_HALF_UP)
        if abs(result) >= limit:
            raise ValueError("invalid_number")
        return result
    except InvalidOperation:
        raise ValueError("invalid_number") from None


def paired_books(row):
    """Return valid pairs and invalid book count; never join partial markets."""
    home, away = name(row["home_team"]), name(row["away_team"])
    if home == away:
        raise ValueError("ambiguous_teams")
    books, invalid = {}, 0
    entries = row.get("bookmakers", [])
    if not isinstance(entries, list):
        raise ValueError("invalid_books")
    duplicates = {book.get("key") for book in entries if isinstance(book, dict) and isinstance(book.get("key"), str)
                  and sum(isinstance(other, dict) and other.get("key") == book.get("key")
                          for other in entries) > 1}
    for book in entries:
        try:
            key = identity(book["key"])
            if len(key) > 128 or key in duplicates:
                raise ValueError("invalid_book")
            markets = [m for m in book["markets"] if m["key"] == "spreads"]
            if not markets:
                continue
            if len(markets) != 1:
                raise ValueError("invalid_market")
            market = markets[0]
            outcomes = market["outcomes"]
            if len(outcomes) != 2 or {o["name"] for o in outcomes} != {home, away}:
                raise ValueError("invalid_pair")
            sides = {o["name"]: o for o in outcomes}
            # Opposite signs must hold before rounding, too.
            if Decimal(str(sides[home]["point"])) != -Decimal(str(sides[away]["point"])):
                raise ValueError("invalid_pair")
            values = {}
            for side, team in (("home", home), ("away", away)):
                values[side + "_line"] = number(sides[team]["point"], ".01", Decimal("1e8"))
                values[side + "_price"] = number(sides[team]["price"], ".0001", Decimal("1e6"))
                if values[side + "_price"] <= 1:
                    raise ValueError("invalid_price")
            source = market.get("last_update", book.get("last_update"))
            values["source_timestamp"] = timestamp(source) if source else None
            books[key] = values
        except (KeyError, TypeError, ValueError, InvalidOperation):
            invalid += 1
    return books, invalid


def quota_metadata(headers, now):
    result = {}
    for header, field in (("x-requests-used", "used"), ("x-requests-remaining", "remaining"),
                          ("x-requests-last", "actual_cost")):
        value = headers.get(header)
        if isinstance(value, str) and value.isdigit():
            result[field] = int(value)
    retry = headers.get("retry-after")
    if isinstance(retry, str) and retry.isdigit():
        result["retry_at"] = now + timedelta(seconds=int(retry))
    return result


class OddsImporter:
    def __init__(self, owner, clients):
        self.owner, self.clients = owner, clients

    def eligible(self, session, window):
        return list(session.scalars(select(Game).join(ProviderGameLink).where(
            ProviderGameLink.provider == "cfbd", ProviderGameLink.home_classification == "fbs",
            ProviderGameLink.away_classification == "fbs", Game.status == "scheduled",
            Game.start_time > self.owner.clock(), Game.start_time >= window.start,
            Game.start_time < window.end)).unique())

    async def run(self, window):
        outcome = {"status": "fetched-and-applied", "applied": 0, "quarantined": 0}
        with self.owner.transaction() as (session, _):
            needed = bool(self.eligible(session, window))
        if not needed:
            outcome["status"] = "skipped-not-needed"
        else:
            try:
                call = self.owner.reserve_call("odds", "spreads", configured=self.clients.odds_configured)
                self.owner.dispatch(call)
                try:
                    rows, headers = await self.clients.odds(window)
                except ProviderError as error:
                    self.owner.finish_call(call, succeeded=False, http_status=error.status,
                        **quota_metadata(error.quota, self.owner.clock()))
                    raise
                self.owner.finish_call(call, succeeded=True, **quota_metadata(headers, self.owner.clock()))
                if not isinstance(rows, list):
                    raise ProviderError("invalid_odds")
                outcome = self.apply(rows, window)
            except (ProviderError, AdmissionRejected) as error:
                outcome.update(status="quota-blocked" if isinstance(error, AdmissionRejected) else "failed",
                               reason=error.reason)
                if isinstance(error, AdmissionRejected) and error.retry_at is not None:
                    outcome["retry_at"] = error.retry_at.isoformat()
        with self.owner.transaction() as (_, run):
            stages = run.stage_outcomes or {}
            run.stage_outcomes = {**stages, "odds": {**stages.get("odds", {}), **outcome}}
        return outcome

    def apply(self, rows, window, *, fetched_at=None):
        """Apply only a successfully fetched complete scope, in one fenced commit."""
        if not isinstance(rows, list):
            raise ProviderError("invalid_odds")
        fetched = fetched_at or self.owner.clock()
        outcome = {"status": "fetched-and-applied", "applied": 0, "quarantined": 0}
        with self.owner.transaction() as (session, run):
            # An empty successful scope must fence late responses even when no
            # event link or quote has ever existed. Retain its watermark in the
            # durable stage audit rather than fabricate an event/observation.
            for prior in session.scalars(select(RefreshRun)):
                scope = (prior.stage_outcomes or {}).get("odds", {})
                if (scope.get("window_start") == window.start.isoformat()
                        and scope.get("window_end") == window.end.isoformat()
                        and scope.get("fetched_at") is not None
                        and timestamp(scope["fetched_at"]) >= fetched):
                    return outcome
            seed_odds_aliases(session)
            games = self.eligible(session, window)
            resolved = {}
            failures = list(run.item_failures or [])
            event_ids = [row.get("id") for row in rows if isinstance(row, dict)]
            for index, row in enumerate(rows):
                try:
                    external = identity(row["id"])
                    if event_ids.count(row["id"]) != 1:
                        raise ValueError("duplicate_event")
                    home, away = name(row["home_team"]), name(row["away_team"])
                    kickoff = timestamp(row["commence_time"])
                    if not window.contains(kickoff) or kickoff <= self.owner.clock():
                        continue
                    link = session.scalar(select(ProviderGameLink).where(
                        ProviderGameLink.provider == "odds", ProviderGameLink.external_id == external))
                    candidates = []
                    for game in games:
                        aliases = list(session.scalars(select(TeamAlias).where(
                            TeamAlias.provider == "odds", TeamAlias.season == game.season,
                            TeamAlias.source_name.in_([home, away]))))
                        mapped = {team: [a.canonical_team for a in aliases if a.source_name == team]
                                  for team in (home, away)}
                        if any(len(v) != 1 for v in mapped.values()):
                            continue
                        normal = (mapped[home][0], mapped[away][0]) == (game.home_team, game.away_team)
                        cfbd = session.scalar(select(ProviderGameLink).where(
                            ProviderGameLink.provider == "cfbd", ProviderGameLink.game_id == game.id))
                        reverse = cfbd.neutral_site and (mapped[away][0], mapped[home][0]) == (game.home_team, game.away_team)
                        if (normal or reverse) and ((link and link.game_id == game.id) or
                                (not link and abs(game.start_time - kickoff) <= timedelta(minutes=5))):
                            candidates.append((game, bool(reverse)))
                    if len(candidates) != 1:
                        raise ValueError("unmatched_or_ambiguous_event")
                    game, reverse = candidates[0]
                    books, invalid = paired_books(row)
                    outcome["quarantined"] += invalid
                    if invalid:
                        failures.append({"provider": "odds", "index": index, "reason": "invalid_paired_book"})
                    if reverse:
                        books = {key: {**value, **{side + suffix: value[other + suffix]
                            for side, other in (("home", "away"), ("away", "home"))
                            for suffix in ("_line", "_price")}} for key, value in books.items()}
                    resolved.setdefault(game.id, []).append((external, home, away, kickoff, books, link))
                except (KeyError, TypeError, ValueError):
                    outcome["quarantined"] += 1
                    failures.append({"provider": "odds", "index": index, "reason": "invalid_or_unmatched_event"})
            for game in games:
                entries = resolved.get(game.id, [])
                links = list(session.scalars(select(ProviderGameLink).where(
                    ProviderGameLink.provider == "odds", ProviderGameLink.game_id == game.id)))
                cfbd = session.scalar(select(ProviderGameLink).where(
                    ProviderGameLink.provider == "cfbd", ProviderGameLink.game_id == game.id))
                if cfbd.fetched_at > fetched or any(link.fetched_at >= fetched for link in links):
                    continue
                history = list(session.scalars(select(QuoteObservation).where(QuoteObservation.game_id == game.id)))
                if any(q.fetched_at >= fetched for q in history):
                    continue
                current = next((q for q in history if q.is_current), None)
                previous = current or max(history, key=lambda q: (q.fetched_at, str(q.id)), default=None)
                chosen = None
                if len(entries) == 1:
                    external, home, away, kickoff, books, link = entries[0]
                    if books:
                        key = previous.bookmaker if previous and previous.bookmaker in books else min(books)
                        values = books[key]
                        # Compare with all history, including invalidated observations.
                        times = [q.source_timestamp for q in history if q.source_timestamp is not None]
                        if times and (values["source_timestamp"] is None or values["source_timestamp"] < max(times)):
                            continue
                        if any(q.bookmaker == key and q.source_timestamp is not None
                               and q.source_timestamp == values["source_timestamp"]
                               and any(getattr(q, field) != value for field, value in values.items())
                               for q in history):
                            continue
                        chosen = (external, key, values)
                    if link is None:
                        link = ProviderGameLink(provider="odds", external_id=external, game_id=game.id,
                            season=game.season, week=game.week, home_identity=home, away_identity=away)
                        session.add(link)
                        links.append(link)
                elif len(entries) > 1:
                    outcome["quarantined"] += 1
                    failures.append({"provider": "odds", "reason": "ambiguous_game_events"})
                for link in links:
                    link.fetched_at = fetched
                    if len(entries) == 1:
                        link.source_kickoff = entries[0][3]
                market = session.scalar(select(Market).where(Market.game_id == game.id, Market.type == "spread"))
                if current:
                    current.is_current = False
                    session.flush()
                if chosen is None:
                    if market:
                        changed = market.status == "active" or any(s.is_active for s in market.selections)
                        market.status = "closed"
                        for selection in market.selections:
                            selection.is_active = False
                        run.data_changed = run.data_changed or changed
                    continue
                external, key, values = chosen
                if market is None:
                    market = Market(game_id=game.id, type="spread", status="active")
                    session.add(market)
                    session.flush()
                content = {**{k: str(v) for k, v in values.items()}, "event": external, "book": key}
                digest = sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()
                quote = next((q for q in history if q.content_hash == digest and q.market_id == market.id), None)
                if quote is None:
                    quote = QuoteObservation(game_id=game.id, market_id=market.id, run_id=run.id,
                        external_event_id=external, bookmaker=key, **values, fetched_at=fetched,
                        content_hash=digest, is_current=True)
                    session.add(quote)
                else:
                    quote.is_current = True
                changed = current is None or current.content_hash != digest or market.status != "active"
                market.status = "active"
                for side in ("home", "away"):
                    selection = next((s for s in market.selections if s.side == side), None)
                    if selection is None:
                        selection = Selection(market_id=market.id, side=side)
                        session.add(selection)
                    selection.line, selection.price = values[side + "_line"], values[side + "_price"]
                    selection.is_active = True
                run.data_changed = run.data_changed or changed
                outcome["applied"] += 1
            run.item_failures = failures
            if outcome["quarantined"]:
                outcome["status"] = "rejected/quarantined"
            outcome.update(fetched_at=fetched.isoformat(), window_start=window.start.isoformat(),
                           window_end=window.end.isoformat())
            run.stage_outcomes = {**(run.stage_outcomes or {}), "odds": outcome}
        return outcome
