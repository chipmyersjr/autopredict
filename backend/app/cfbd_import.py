"""CFBD game stage, invoked only by an admitted explicit refresh.

Schedule is the window discovery feed; /games supplies season classification and
explicit completed/points fields absent from some schedule versions. Both calls
are charged. No elapsed-clock status inference, settlement, or API side effects.
"""

from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select

from app.ingress import CalendarWeek, ProviderError, aware, overlapping_weeks
from app.models import Game, GameResultChange, ProviderCalendar, ProviderGameLink, QuoteObservation, TeamAlias
from app.refresh_admission import AdmissionRejected


def timestamp(value):
    return aware(datetime.fromisoformat(value))


def positive_int(value):
    if type(value) is not int or not 0 < value < 2**31:
        raise ValueError("invalid_integer")
    return value


def identity(value):
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and value.strip() and len(value) <= 128:
        return value.strip()
    raise ValueError("invalid_identity")


def name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError("invalid_team")
    if value.strip().lower() in {"tbd", "tba", "unknown"}:
        raise ValueError("ambiguous_team")
    return value.strip()


def normalize(row):
    """Normalize the documented flat /games contract with optional schedule state.

    `completed: false` does not establish live play or cancellation. Schedule
    states must be explicit; postponed cannot fit the canonical enum and is
    quarantined. Scores are accepted only with explicit final confirmation.
    """
    external = identity(row["id"])
    season, week = positive_int(row["season"]), positive_int(row["week"])
    if row["seasonType"] not in {"regular", "postseason"}:
        raise ValueError("unknown_season_type")
    kickoff = timestamp(row["startDate"])
    if row.get("startTimeTBD") is not False:
        raise ValueError("unknown_kickoff")
    home, away = name(row["homeTeam"]), name(row["awayTeam"])
    home_id, away_id = identity(row["homeId"]), identity(row["awayId"])
    if home_id == away_id or home == away:
        raise ValueError("ambiguous_teams")
    if type(row.get("neutralSite")) is not bool:
        raise ValueError("unknown_neutral_site")
    states = {"scheduled": "scheduled", "in_progress": "in_progress",
              "in progress": "in_progress", "completed": "completed",
              "final": "completed", "canceled": "canceled", "cancelled": "canceled"}
    source = row.get("status")
    if source is not None:
        if not isinstance(source, str) or source.lower() not in states:
            raise ValueError("unknown_status")
        status = states[source.lower()]
        if row.get("completed") is True and status != "completed":
            raise ValueError("conflicting_status")
    elif type(row.get("completed")) is bool:
        status = "completed" if row["completed"] else "scheduled"
        source = "completed=true" if row["completed"] else "completed=false"
    else:
        raise ValueError("unknown_status")
    scores = (None, None)
    if status == "completed":
        scores = (row.get("homePoints"), row.get("awayPoints"))
        if any(type(score) is not int or not 0 <= score < 2**31 for score in scores):
            raise ValueError("invalid_final_scores")
    return dict(external=external, season=season, week=week, season_type=row["seasonType"],
                kickoff=kickoff, home=home, away=away, home_id=home_id, away_id=away_id,
                status=status, source=source, scores=scores, neutral=row["neutralSite"],
                source_time=timestamp(row["updatedAt"]) if row.get("updatedAt") else None)


class CFBDImporter:
    def __init__(self, owner, clients, *, configured=None):
        self.owner, self.clients = owner, clients
        self.configured = clients.cfbd_configured if configured is None and clients is not None else bool(configured)

    async def call(self, endpoint, method, *args):
        call = self.owner.reserve_call("cfbd", endpoint, configured=self.configured)
        self.owner.dispatch(call)
        try:
            payload, headers = await method(*args)
        except ProviderError as error:
            metadata = {}
            retry = error.quota.get("retry-after")
            if retry and retry.isdigit():
                metadata["retry_at"] = self.owner.clock() + timedelta(seconds=int(retry))
            self.owner.finish_call(call, succeeded=False, http_status=error.status, **metadata)
            raise
        metadata = {}
        if endpoint == "info" and isinstance(payload, dict):
            # Account responses expose these fields; absent metadata stays unknown.
            for source, target in (("remainingCalls", "remaining"), ("monthlyAllowance", "allowance")):
                value = payload.get(source)
                if type(value) is int and value >= (1 if target == "allowance" else 0):
                    metadata[target] = value
            if payload.get("resetDate"):
                try:
                    metadata["resets_at"] = timestamp(payload["resetDate"])
                except (ValueError, TypeError):
                    pass
        self.owner.finish_call(call, succeeded=True, **metadata)
        return payload

    async def calendar(self, season):
        now = self.owner.clock()
        with self.owner.transaction() as (session, _):
            cached = session.scalar(select(ProviderCalendar).where(ProviderCalendar.season == season))
            if cached is not None and cached.expires_at is not None and cached.expires_at > now:
                return [CalendarWeek(**{**week, "start": timestamp(week["start"]),
                                        "end": timestamp(week["end"])}) for week in cached.weeks]
        weeks = await self.call("calendar", self.clients.calendar, season)
        with self.owner.transaction() as (session, _):
            cached = session.scalar(select(ProviderCalendar).where(ProviderCalendar.season == season))
            if cached is None:
                cached = ProviderCalendar(season=season)
                session.add(cached)
            cached.weeks = [{**asdict(week), "start": week.start.isoformat(),
                             "end": week.end.isoformat()} for week in weeks]
            cached.fetched_at, cached.expires_at = now, now + timedelta(days=1)
        return weeks

    async def run(self, window):
        outcome = {"status": "fetched-and-applied", "applied": 0, "excluded": 0, "quarantined": 0}
        try:
            await self.call("info", self.clients.info)
            calendar = []
            for season in window.calendar_years:
                calendar.extend(await self.calendar(season))
            histories = {}
            for week in overlapping_weeks(window, calendar):
                rows = await self.call("schedule", self.clients.schedule, week)
                if not isinstance(rows, list):
                    raise ProviderError("invalid_schedule")
                # A moved game may disappear from this schedule window. Revisit
                # known current-window identities using the season response.
                with self.owner.transaction() as (session, _):
                    known = set(session.scalars(select(ProviderGameLink.external_id).where(
                        ProviderGameLink.provider == "cfbd", ProviderGameLink.season == week.season,
                        ProviderGameLink.source_kickoff >= window.start,
                        ProviderGameLink.source_kickoff < window.end)))
                if (rows or known) and week.season not in histories:
                    history = await self.call("games", self.clients.season_games, week.season)
                    if not isinstance(history, list):
                        raise ProviderError("invalid_games")
                    histories[week.season] = history
                present = {str(row.get("id")) for row in rows if isinstance(row, dict)}
                moved = [row for row in histories.get(week.season, []) if isinstance(row, dict)
                         and str(row.get("id")) in known - present]
                self.apply(rows + moved, histories.get(week.season, []), window, outcome)
        except (ProviderError, AdmissionRejected) as error:
            outcome["status"] = "quota-blocked" if isinstance(error, AdmissionRejected) else "failed"
            outcome["reason"] = error.reason
            if isinstance(error, AdmissionRejected) and error.retry_at is not None:
                outcome["retry_at"] = error.retry_at.isoformat()
        with self.owner.transaction() as (session, run):
            run.stage_outcomes = {**(run.stage_outcomes or {}), "cfbd": outcome}
        return outcome

    def apply(self, rows, history, window, outcome=None):
        outcome = outcome if outcome is not None else {"applied": 0, "excluded": 0, "quarantined": 0}
        fetched = self.owner.clock()
        indexed = {}
        for row in history:
            if isinstance(row, dict):
                indexed.setdefault(str(row.get("id")), []).append(row)
        scheduled = {}
        ambiguous = set()
        for row in rows:
            if isinstance(row, dict):
                key = str(row.get("id"))
                if key in scheduled and scheduled[key] != row:
                    ambiguous.add(key)
                scheduled[key] = row
        with self.owner.transaction() as (session, run):
            failures = list(run.item_failures or [])
            for index, row in enumerate(rows):
                try:
                    with session.begin_nested():
                        if not isinstance(row, dict):
                            raise ValueError("invalid_record")
                        if str(row.get("id")) in ambiguous:
                            raise ValueError("ambiguous_schedule")
                        matches = indexed.get(str(row.get("id")), [])
                        if len(matches) > 1:
                            raise ValueError("ambiguous_history")
                        if matches and any(key in row and key in matches[0] and row[key] != matches[0][key]
                                           for key in ("season", "homeId", "awayId")):
                            raise ValueError("identity_conflict")
                        merged = {**(matches[0] if matches else {}), **row}
                        # Schedule fields win, while historical completed/points and
                        # classification fill missing fields only. Never join by names.
                        data = normalize(merged)
                        link = session.scalar(select(ProviderGameLink).where(
                            ProviderGameLink.provider == "cfbd", ProviderGameLink.external_id == data["external"]))
                        if merged.get("homeClassification") != "fbs" or merged.get("awayClassification") != "fbs":
                            if not all(merged.get(key) in {"fbs", "fcs", "ii", "iii"}
                                       for key in ("homeClassification", "awayClassification")):
                                raise ValueError("unknown_classification")
                            outcome["excluded"] += 1
                            continue
                        if link is None and not window.contains(data["kickoff"]):
                            outcome["excluded"] += 1
                            continue
                        if link is not None:
                            if fetched <= link.fetched_at or (link.source_timestamp is not None and
                                    (data["source_time"] is None or data["source_time"] <= link.source_timestamp)):
                                continue
                            if (link.season, link.home_identity, link.away_identity) != (
                                    data["season"], data["home_id"], data["away_id"]):
                                raise ValueError("identity_conflict")
                        teams = []
                        for side in ("home", "away"):
                            alias = session.scalar(select(TeamAlias).where(TeamAlias.provider == "cfbd",
                                TeamAlias.season == data["season"], TeamAlias.source_identity == data[side + "_id"]))
                            if alias is None:
                                alias = TeamAlias(provider="cfbd", season=data["season"],
                                    source_identity=data[side + "_id"], source_name=data[side],
                                    canonical_team=data[side], classification="fbs")
                                session.add(alias)
                            elif alias.source_name != data[side] or alias.classification != "fbs":
                                raise ValueError("team_alias_conflict")
                            teams.append(alias.canonical_team)
                        game = session.get(Game, link.game_id) if link else Game()
                        old = (game.status, game.home_score, game.away_score)
                        new = (data["status"], *data["scores"])
                        if link and game.status == "completed" and data["status"] != "completed":
                            raise ValueError("final_regression")
                        values = dict(season=data["season"], week=data["week"], home_team=teams[0], away_team=teams[1],
                                      start_time=data["kickoff"], status=new[0], home_score=new[1], away_score=new[2])
                        changed = not link or any(getattr(game, key) != value for key, value in values.items())
                        if link and (game.start_time != data["kickoff"] or data["status"] != "scheduled"):
                            for market in game.markets:
                                if market.status == "active":
                                    market.status = "closed"
                                for selection in market.selections:
                                    selection.is_active = False
                            for quote in session.scalars(select(QuoteObservation).where(
                                    QuoteObservation.game_id == game.id, QuoteObservation.is_current)):
                                quote.is_current = False
                        for key, value in values.items():
                            setattr(game, key, value)
                        session.add(game)
                        session.flush()
                        if (old[0] is not None and old != new) or (old[0] is None and new[0] == "completed"):
                            session.add(GameResultChange(game_id=game.id, run_id=run.id, old_status=old[0] or "scheduled",
                                new_status=new[0], old_home_score=old[1], old_away_score=old[2],
                                new_home_score=new[1], new_away_score=new[2], source_state=data["source"],
                                source_timestamp=data["source_time"], fetched_at=fetched))
                        if link is None:
                            link = ProviderGameLink(provider="cfbd", external_id=data["external"], game_id=game.id)
                            session.add(link)
                        for key, value in dict(season=data["season"], week=data["week"], season_type=data["season_type"],
                                home_identity=data["home_id"], away_identity=data["away_id"], home_classification="fbs",
                                away_classification="fbs", source_state=data["source"], source_kickoff=data["kickoff"],
                                neutral_site=data["neutral"], source_timestamp=data["source_time"], fetched_at=fetched).items():
                            setattr(link, key, value)
                        if changed:
                            run.data_changed = True
                        outcome["applied"] += 1
                except (KeyError, ValueError, TypeError) as error:
                    # Allow only our own fixed reason codes, never parser errors
                    # containing raw provider text or underlying request details.
                    reasons = {"invalid_record", "invalid_integer", "invalid_identity", "invalid_team",
                               "ambiguous_team", "unknown_season_type", "unknown_kickoff", "ambiguous_teams",
                               "unknown_neutral_site", "unknown_status", "conflicting_status", "invalid_final_scores",
                               "ambiguous_history", "ambiguous_schedule", "unknown_classification", "identity_conflict",
                               "team_alias_conflict", "final_regression"}
                    reason = str(error) if isinstance(error, ValueError) and str(error) in reasons else "invalid_required_field"
                    failures.append({"provider": "cfbd", "index": index, "reason": reason})
                    outcome["quarantined"] += 1
            run.item_failures = failures
        if outcome["quarantined"]:
            outcome["status"] = "rejected/quarantined"
        return outcome
