"""Persisted HTTP progress and reasoning, using only controlled predictions."""
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Run, User
from app.predictors import AgentDecision, Prediction
from app.run_worker import begin_attempt, claim_next, finalize, save_attempt
from app.seed_strategy import AGENT_STRATEGY_ID, seed_agent_strategy
from test_runs import api, body, post


def progress(client, run_id):
    response = client.get(f"/api/runs/{run_id}/execution")
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["total_games"] == len(value["games"])
    assert value["completed_games"] == sum(
        g["state"] in {"predicted", "bet_created", "skipped"} for g in value["games"])
    assert value["predicted_games"] == sum(
        g["state"] in {"predicted", "bet_created"} for g in value["games"])
    for counter, state in [("skipped_games", "skipped"), ("queued_games", "queued"),
                           ("retrying_games", "retrying")]:
        assert value[counter] == sum(g["state"] == state for g in value["games"])
    assert 0 <= value["completed_games"] <= value["total_games"]
    assert all(set(g) == {"game_id", "state", "attempts", "skip_reason"} for g in value["games"])
    return value


@pytest.mark.parametrize("agent", [False, True])
def test_processing_partial_replay_and_reasoning_reads(api, agent, monkeypatch):
    client, engine, games = api
    if agent:
        seed_agent_strategy(engine)
    payload = body(list(reversed(games)))
    if agent:
        payload["strategy_id"] = str(AGENT_STRATEGY_ID)
    key = uuid4()
    accepted = post(client, payload, key)
    assert accepted.status_code == 201
    saved = accepted.json()
    run_id = saved["run"]["id"]
    assert saved["bets"] == []
    initial = progress(client, run_id)
    assert initial["status"] == "queued"
    assert initial["queued_games"] == 4 and initial["skipped_games"] == 1
    assert [g["game_id"] for g in initial["games"]] == payload["game_ids"]
    assert post(client, payload, key).status_code == 200
    assert progress(client, run_id) == initial
    claim = claim_next(engine)
    row_id, value, *_ = begin_attempt(engine, claim)
    active = progress(client, run_id)
    assert active["status"] == "running"
    assert active["games"][1]["state"] == "analysing"
    save_attempt(engine, claim, row_id, failure="research_failed")
    assert progress(client, run_id)["retrying_games"] == 1
    row_id, value, *_ = begin_attempt(engine, claim)
    save_attempt(engine, claim, row_id, failure="research_failed")
    reasoning = "Saved evidence <script>plain text</script>" if agent else None
    while (work := begin_attempt(engine, claim)) is not None:
        row_id, value, *_ = work
        decision = (AgentDecision if agent else Prediction)(
            selection_id=value.selections[0].selection_id, reasoning=reasoning)
        save_attempt(engine, claim, row_id, prediction=decision)
    predicted = progress(client, run_id)
    assert predicted["predicted_games"] == 3 and predicted["completed_games"] == 5
    assert client.get(f"/api/runs/{run_id}/bets").json() == []
    assert finalize(engine, claim)
    terminal = progress(client, run_id)
    assert terminal["status"] == "completed" and terminal["message"] is None
    replay = post(client, payload, key).json()
    assert replay["run"]["execution_started_at"].endswith("+00:00")
    assert replay["run"]["execution_finished_at"].endswith("+00:00")
    assert len(replay["bets"]) == 3
    assert all(b["reasoning"] == reasoning for b in replay["bets"])
    # Reads cannot create predictions, claim work, or call a provider.
    def forbidden(*args, **kwargs):
        raise AssertionError("Read attempted inference")
    monkeypatch.setattr("app.predictors.RandomPredictor.predict", forbidden)
    monkeypatch.setattr("app.predictors.AgentPredictor.predict", forbidden)
    assert client.get(f"/api/runs/{run_id}").json() == replay["run"]
    assert client.get("/api/runs").json() == [replay["run"]]
    assert client.get(f"/api/runs/{run_id}/bets").json() == replay["bets"]
    for bet in replay["bets"]:
        assert client.get(f'/api/bets/{bet["id"]}').json() == bet
    assert progress(client, run_id) == terminal
    # Saved final scores, rather than any provider refresh, drive settlement.
    from app.models import Game
    with Session(engine) as session, session.begin():
        for game in session.scalars(select(Game)):
            game.status, game.home_score, game.away_score = "completed", 28, 14
    settled = client.post(f"/api/runs/{run_id}/settle")
    assert settled.status_code == 200, settled.text
    assert all(b["reasoning"] == reasoning for b in settled.json()["bets"])
    assert all(b["reasoning"] == reasoning for b in client.get("/api/dashboard").json()["recent_results"])


def test_failed_execution_and_owner_scope(api):
    client, engine, games = api
    payload = body(games[:1])
    key = uuid4()
    run_id = post(client, payload, key).json()["run"]["id"]
    claim = claim_next(engine)
    for _ in range(2):
        row_id, *_ = begin_attempt(engine, claim)
        save_attempt(engine, claim, row_id, failure="invalid_agent_decision")
    assert finalize(engine, claim)
    value = progress(client, run_id)
    assert value["status"] == "failed" and value["message"]
    assert value["completed_games"] == value["skipped_games"] == 1
    assert value["games"][0]["attempts"] == 2
    replay = post(client, payload, key).json()
    assert replay["bets"] == []
    assert replay["run"]["available_bankroll"] == "40.00"
    assert replay["run"]["total_profit"] is replay["run"]["roi"] is None
    assert client.post(f"/api/runs/{run_id}/settle").status_code == 409
    assert client.get(f"/api/runs/{uuid4()}/execution").status_code == 404
    assert client.get("/api/runs/bad/execution").status_code == 422
    with Session(engine) as session, session.begin():
        other = User(name="Other owner", email="other-execution@example.test")
        session.add(other)
        session.flush()
        session.get(Run, claim.run_id).user_id = other.id
    assert client.get(f"/api/runs/{run_id}/execution").status_code == 404
