"""Durable prediction stage. Bet finalization is a separate, fenced transaction.

Every public mutation opens and closes its own transaction. No ORM objects or
connections cross the predictor boundary. An expired lease cannot be revived.
"""
import asyncio
import argparse
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Game, Run, RunGame, Strategy
from pydantic import ValidationError

from app.predictors import (AgentDecision, Prediction, PredictionFailure, PredictionInput,
                            get_predictor, resolve_prediction)
from app.schemas import BetDecision
from app.strategies import resolve_candidates

LEASE_SECONDS = 240
HEARTBEAT_SECONDS = 15
FAILURES = {"agent_unavailable", "research_failed", "invalid_agent_decision", "quote_changed"}


class LostClaim(Exception):
    """The caller must discard all outstanding results."""


@dataclass(frozen=True)
class Claim:
    run_id: UUID
    token: UUID
    generation: int


def db_now(session):
    return session.scalar(select(func.clock_timestamp()))


def owned(session, claim):
    run = session.scalar(select(Run).where(Run.id == claim.run_id).with_for_update())
    now = db_now(session)
    if (run is None or run.execution_status != "running"
            or run.execution_owner_token != claim.token
            or run.execution_generation != claim.generation
            or run.execution_lease_expires_at <= now):
        raise LostClaim()
    return run, now


def claim_next(engine):
    with Session(engine) as session, session.begin():
        now = db_now(session)
        run = session.scalar(select(Run).where(or_(
            Run.execution_status == "queued",
            (Run.execution_status == "running") & (Run.execution_lease_expires_at <= now),
        )).order_by(Run.created_at, Run.id).with_for_update(skip_locked=True).limit(1))
        if run is None:
            return None
        run.execution_status = "running"
        run.execution_started_at = run.execution_started_at or now
        run.execution_owner_token = uuid4()
        run.execution_generation += 1
        run.execution_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        return Claim(run.id, run.execution_owner_token, run.execution_generation)


def heartbeat(engine, claim):
    with Session(engine) as session, session.begin():
        run, now = owned(session, claim)
        run.execution_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)


def release(engine, claim):
    """Graceful shutdown makes the claim recoverable without resetting attempts."""
    with Session(engine) as session, session.begin():
        run, now = owned(session, claim)
        run.execution_lease_expires_at = now


def encode_input(value):
    return dict(game_id=str(value.game_id), home_team=value.home_team,
                away_team=value.away_team, kickoff=value.kickoff.isoformat(),
                selections=[s.model_dump(mode="json") for s in value.selections])


def decode_input(value):
    return PredictionInput(UUID(value["game_id"]), value["home_team"], value["away_team"],
                           datetime.fromisoformat(value["kickoff"]),
                           tuple(BetDecision.model_validate(s) for s in value["selections"]))


def begin_attempt(engine, claim):
    with Session(engine) as session, session.begin():
        run, now = owned(session, claim)
        rows = session.scalars(select(RunGame).where(RunGame.run_id == run.id)
                               .order_by(RunGame.position).with_for_update()).all()
        for row in rows:
            if row.state in {"predicted", "bet_created", "skipped"}:
                continue
            if row.attempts >= 2:
                row.state, row.skip_reason = "skipped", "agent_unavailable"
                continue
            game = session.get(Game, row.game_id)
            candidates, skip = resolve_candidates(game, now, session)
            if skip:
                row.state, row.skip_reason = "skipped", skip.reason
                continue
            value = PredictionInput(game.id, game.home_team, game.away_team,
                                    game.start_time, tuple(candidates))
            row.attempts += 1
            row.state = "analysing"
            row.prediction_input = encode_input(value)
            row.validated_prediction = None
            strategy = session.get(Strategy, run.strategy_id)
            return row.id, value, strategy.type, strategy.config
        return None


def save_attempt(engine, claim, row_id, *, prediction=None, failure=None):
    with Session(engine) as session, session.begin():
        owned(session, claim)
        row = session.scalar(select(RunGame).where(RunGame.id == row_id,
            RunGame.run_id == claim.run_id).with_for_update())
        if row is None or row.state != "analysing":
            raise LostClaim()
        if failure is not None:
            reason = failure if failure in FAILURES else "agent_unavailable"
            row.state = "retrying" if row.attempts < 2 else "skipped"
            row.skip_reason = reason if row.state == "skipped" else None
        else:
            value = decode_input(row.prediction_input)
            strategy = session.get(Strategy, session.get(Run, claim.run_id).strategy_id)
            prediction = (AgentDecision if strategy.type == "agent" else Prediction).model_validate(prediction)
            decision = resolve_prediction(value, prediction)
            row.validated_prediction = decision.model_dump(mode="json")
            row.state = "predicted"


def execution_snapshot(session, run_id, owner):
    """One SQL snapshot; this read never claims or runs work."""
    records = session.execute(select(Run, RunGame).outerjoin(RunGame, RunGame.run_id == Run.id)
        .where(Run.id == run_id, Run.user_id == owner).order_by(RunGame.position)
        .execution_options(populate_existing=True)).all()
    if not records:
        return None
    run = records[0][0]
    games = [dict(game_id=g.game_id, state=g.state, attempts=g.attempts, skip_reason=g.skip_reason)
             for _, g in records if g is not None]
    states = [g["state"] for g in games]
    return dict(run_id=run.id, status=run.execution_status, total_games=len(games),
                completed_games=sum(s in {"predicted", "bet_created", "skipped"} for s in states),
                predicted_games=sum(s in {"predicted", "bet_created"} for s in states),
                skipped_games=states.count("skipped"), retrying_games=states.count("retrying"),
                queued_games=states.count("queued"), games=games, message=run.execution_message)


async def process_claim(engine, claim, predictor_factory):
    revoked = asyncio.Event()

    async def renew():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            heartbeat(engine, claim)

    async def predict_games():
        while (work := begin_attempt(engine, claim)) is not None:
            row_id, value, kind, config = work
            try:
                predictor = predictor_factory(kind, config)
                async with asyncio.timeout(180):
                    prediction = await predictor.predict(value)
                if revoked.is_set():
                    raise LostClaim()
                # Validate before persisting; injected predictors obey the same rules.
                prediction = (AgentDecision if kind == "agent" else Prediction).model_validate(prediction)
                resolve_prediction(value, prediction)
            except LostClaim:
                raise
            except PredictionFailure as error:
                if revoked.is_set():
                    raise LostClaim()
                save_attempt(engine, claim, row_id, failure=error.reason)
            except ValidationError:
                save_attempt(engine, claim, row_id, failure="invalid_agent_decision")
            except Exception:
                save_attempt(engine, claim, row_id, failure="agent_unavailable")
            else:
                save_attempt(engine, claim, row_id, prediction=prediction)

    pulse = asyncio.create_task(renew())
    work = asyncio.create_task(predict_games())
    try:
        done, _ = await asyncio.wait({pulse, work}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        revoked.set()
        pulse.cancel()
        work.cancel()
        await asyncio.gather(pulse, work, return_exceptions=True)
        try:
            release(engine, claim)
        except LostClaim:
            pass


async def serve(engine, predictor_factory, *, once=False):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            claim = claim_next(engine)
            if claim:
                job = asyncio.create_task(process_claim(engine, claim, predictor_factory))
                stopping = asyncio.create_task(stop.wait())
                try:
                    await asyncio.wait({job, stopping}, return_when=asyncio.FIRST_COMPLETED)
                    if stop.is_set():
                        job.cancel()
                    await job
                except (LostClaim, asyncio.CancelledError):
                    pass
                finally:
                    stopping.cancel()
                    await asyncio.gather(stopping, return_exceptions=True)
            if once:
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main():
    from app.agent_services import DuckDuckGoSearch, local_model_client
    from app.database import create_database_engine
    from app.settings import Settings
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    engine = create_database_engine(settings)

    async def run():
        search = DuckDuckGoSearch()
        try:
            async with local_model_client(settings) as client:
                await serve(engine, lambda kind, config: get_predictor(kind, config,
                    client=client, search=search, model=settings.ollama_model), once=args.once)
        finally:
            await search.aclose()
    try:
        asyncio.run(run())
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
