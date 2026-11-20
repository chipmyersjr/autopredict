"""Durable prediction boundaries on generated PostgreSQL databases; no services."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
from datetime import timedelta
from multiprocessing import get_context
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, null, text
from sqlalchemy.orm import Session

from app.models import Run, RunGame
from app.predictors import Prediction, PredictionFailure
from app.run_worker import (LostClaim, begin_attempt, claim_next, execution_snapshot,
                            heartbeat, process_claim, release, save_attempt)
from app.seed import demo_games, seed_demo
from app.seed_strategy import RANDOM_STRATEGY_ID, seed_strategy
from app.seed_user import LOCAL_USER_ID, seed_user
from app.strategies import utc_now


@pytest.fixture
def queued(migrated_database):
    engine, _ = migrated_database
    seed_user(engine)
    seed_strategy(engine)
    now = utc_now()
    games = demo_games(now.date())[:2]
    for game in games:
        game.start_time = now + timedelta(days=1)
    seed_demo(engine, games)
    with Session(engine) as session, session.begin():
        run = Run(user_id=LOCAL_USER_ID, strategy_id=RANDOM_STRATEGY_ID,
                  request_id=uuid4(), request_payload={}, starting_bankroll=100,
                  stake_per_bet=10, start_time=now, status="open",
                  execution_status="queued", execution_finished_at=null())
        session.add(run)
        session.flush()
        for position, game in enumerate(reversed(games)):
            session.add(RunGame(run_id=run.id, game_id=game.id, position=position,
                                included_at=now, state="queued"))
        run_id = run.id
    return engine, run_id


def expire(engine, run_id):
    with engine.begin() as connection:
        connection.execute(text("UPDATE runs SET execution_lease_expires_at = clock_timestamp() - interval '1 second' WHERE id=:id"), {"id": run_id})


def snapshot(engine, run_id):
    with Session(engine) as session:
        return execution_snapshot(session, run_id, LOCAL_USER_ID)


def child_claim(url):
    engine = create_engine(url)
    try:
        return claim_next(engine)
    finally:
        engine.dispose()


def test_process_claim_exclusion_and_fencing(queued):
    engine, run_id = queued
    url = engine.url.render_as_string(hide_password=False)
    with ProcessPoolExecutor(2, mp_context=get_context("spawn")) as pool:
        futures = [pool.submit(child_claim, url) for _ in range(2)]
        claims = [f.result(timeout=30) for f in futures]
    assert sum(c is not None for c in claims) == 1
    old = next(c for c in claims if c is not None)
    assert claim_next(engine) is None
    row, value, *_ = begin_attempt(engine, old)
    heartbeat(engine, old)
    expire(engine, run_id)
    with pytest.raises(LostClaim):
        heartbeat(engine, old)
    new = claim_next(engine)
    assert new.generation == old.generation + 1 and new.token != old.token
    for action in (lambda: begin_attempt(engine, old),
                   lambda: release(engine, old),
                   lambda: save_attempt(engine, old, row, prediction=Prediction(selection_id=value.selections[0].selection_id))):
        with pytest.raises(LostClaim):
            action()
    assert snapshot(engine, run_id)["games"][0]["attempts"] == 1


def test_restart_boundaries_and_retained_prediction(queued):
    engine, run_id = queued
    first = claim_next(engine)
    # Crash immediately after claim: no attempt has been spent.
    expire(engine, run_id)
    second = claim_next(engine)
    row, value, *_ = begin_attempt(engine, second)
    assert snapshot(engine, run_id)["games"][0]["attempts"] == 1
    # Crash after durable attempt, before result: the attempt remains spent.
    expire(engine, run_id)
    third = claim_next(engine)
    retried, value, *_ = begin_attempt(engine, third)
    assert retried == row
    save_attempt(engine, third, row, prediction=Prediction(selection_id=value.selections[0].selection_id))
    expire(engine, run_id)
    fourth = claim_next(engine)
    other, *_ = begin_attempt(engine, fourth)
    assert other != row
    expire(engine, run_id)
    fifth = claim_next(engine)
    other_again, *_ = begin_attempt(engine, fifth)
    assert other_again == other
    expire(engine, run_id)
    sixth = claim_next(engine)
    assert begin_attempt(engine, sixth) is None
    progress = snapshot(engine, run_id)
    assert progress["completed_games"] == progress["total_games"] == 2
    assert progress["predicted_games"] == progress["skipped_games"] == 1
    assert [g["attempts"] for g in progress["games"]] == [2, 2]
    with Session(engine) as session:
        saved = session.get(RunGame, row)
        assert saved.validated_prediction["selection_id"] == str(value.selections[0].selection_id)
        assert execution_snapshot(session, run_id, uuid4()) is None


def test_prediction_failure_retry_and_no_open_transaction(queued):
    engine, run_id = queued
    calls = []

    class Fake:
        async def predict(self, value):
            # An independent connection can lock every worker row during inference.
            with engine.begin() as connection:
                connection.execute(text("SELECT id FROM runs FOR UPDATE NOWAIT"))
                connection.execute(text("SELECT id FROM run_games FOR UPDATE NOWAIT"))
                connection.execute(text("SELECT id FROM games FOR UPDATE NOWAIT"))
            calls.append(value.game_id)
            raise PredictionFailure("research_failed")

    claim = claim_next(engine)
    asyncio.run(process_claim(engine, claim, lambda *_: Fake()))
    progress = snapshot(engine, run_id)
    assert len(calls) == 4
    assert progress["completed_games"] == progress["skipped_games"] == 2
    assert all(g["attempts"] == 2 and g["skip_reason"] == "research_failed" for g in progress["games"])
    # Repeated reads never invoke a predictor or mutate durable progress.
    assert snapshot(engine, run_id) == progress
    assert len(calls) == 4


def test_retry_progress_order_and_atomic_result_validation(queued):
    engine, run_id = queued
    claim = claim_next(engine)
    initial = snapshot(engine, run_id)
    assert initial["queued_games"] == initial["total_games"] == 2
    row, value, *_ = begin_attempt(engine, claim)
    assert value.game_id == initial["games"][0]["game_id"]
    # A rejected write rolls back, preserving the committed attempt/input.
    with pytest.raises(PredictionFailure):
        save_attempt(engine, claim, row, prediction=Prediction(selection_id=uuid4()))
    progress = snapshot(engine, run_id)
    assert progress["games"][0]["state"] == "analysing"
    assert progress["games"][0]["attempts"] == 1
    save_attempt(engine, claim, row, failure="research_failed")
    assert snapshot(engine, run_id)["retrying_games"] == 1
    row_again, fresh, *_ = begin_attempt(engine, claim)
    assert row_again == row
    decision = Prediction(selection_id=fresh.selections[0].selection_id)
    save_attempt(engine, claim, row, prediction=decision)
    # A duplicate completion cannot overwrite the saved prediction.
    with pytest.raises(LostClaim):
        save_attempt(engine, claim, row, failure="agent_unavailable")
    final = snapshot(engine, run_id)
    assert final["predicted_games"] == final["completed_games"] == 1
    assert final["queued_games"] == 1 and final["retrying_games"] == 0
    assert [g["game_id"] for g in final["games"]] == [g["game_id"] for g in initial["games"]]
    assert 0 <= final["completed_games"] <= final["total_games"]


def test_cancellation_releases_lease_and_restart_spends_only_remaining_attempt(queued):
    engine, run_id = queued
    started = asyncio.Event()

    class Waiting:
        async def predict(self, value):
            started.set()
            await asyncio.Future()

    async def cancel():
        claim = claim_next(engine)
        job = asyncio.create_task(process_claim(engine, claim, lambda *_: Waiting()))
        await started.wait()
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
    asyncio.run(cancel())
    assert snapshot(engine, run_id)["games"][0]["attempts"] == 1
    claim = claim_next(engine)
    assert claim is not None
    row, value, *_ = begin_attempt(engine, claim)
    save_attempt(engine, claim, row, prediction=Prediction(selection_id=value.selections[0].selection_id))
    assert snapshot(engine, run_id)["games"][0]["attempts"] == 2


def test_heartbeat_loss_cancels_prediction_without_late_result(queued, monkeypatch):
    engine, run_id = queued
    cancelled = []

    class Waiting:
        async def predict(self, value):
            try:
                await asyncio.Future()
            finally:
                cancelled.append(True)

    monkeypatch.setattr("app.run_worker.HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr("app.run_worker.heartbeat", lambda *_: (_ for _ in ()).throw(LostClaim()))
    with pytest.raises(LostClaim):
        asyncio.run(process_claim(engine, claim_next(engine), lambda *_: Waiting()))
    assert cancelled == [True]
    progress = snapshot(engine, run_id)
    assert progress["predicted_games"] == 0
    assert progress["games"][0]["attempts"] == 1
