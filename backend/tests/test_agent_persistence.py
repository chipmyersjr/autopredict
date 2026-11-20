"""Agent schema contracts and migration safety on disposable PostgreSQL only."""
from uuid import uuid4

import pytest
from alembic import command
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, DataError, IntegrityError

from app.schemas import BetDecision, StrategyCreate
from test_runs import api, body, finished_post as post, legacy_execution_fixture


@pytest.mark.parametrize("config", [None, {}, {"profile": "unknown"},
                                    {"profile": "../FootballAnalysisExpert"},
                                    {"profile": "FootballAnalysisExpert", "model": "other"}])
def test_agent_configuration_rejected(config):
    with pytest.raises(ValidationError):
        StrategyCreate(name="Agent", type="agent", config=config)


def test_agent_configuration_and_reasoning():
    strategy = StrategyCreate(name="Agent", type="agent", config={"profile": "FootballAnalysisExpert"})
    assert strategy.type == "agent"
    decision = dict(game_id=uuid4(), market_id=uuid4(), selection_id=uuid4(),
                    side="home", line="-3.50", price="1.9091")
    assert BetDecision(**decision).reasoning is None
    assert BetDecision(**decision, reasoning="x" * 1000).reasoning == "x" * 1000
    for reasoning in ("", " ", "\n", " padded ", "x" * 1001):
        with pytest.raises(ValidationError):
            BetDecision(**decision, reasoning=reasoning)


def test_legacy_backfill_snapshots_and_cycle(api, migrated_database):
    client, engine, games = api
    _, config = migrated_database
    saved = post(client, body(games)).json()
    legacy_execution_fixture(engine)
    run_id = saved["run"]["id"]
    with engine.connect() as connection:
        before = connection.execute(text("SELECT id, side, line, price, stake, home_team, away_team, kickoff_at_placement, observation_id, bookmaker, source_timestamp, fetched_at FROM bets ORDER BY id")).all()
    command.downgrade(config, "0005")
    command.upgrade(config, "head")
    command.check(config)
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["execution_status"] == "completed"
    assert run["execution_started_at"] == run["start_time"]
    assert run["execution_finished_at"] == run["start_time"]
    assert all(b["reasoning"] is None for b in client.get(f"/api/runs/{run_id}/bets").json())
    with engine.connect() as connection:
        after = connection.execute(text("SELECT id, side, line, price, stake, home_team, away_team, kickoff_at_placement, observation_id, bookmaker, source_timestamp, fetched_at FROM bets ORDER BY id")).all()
        assert before == after
        states = connection.execute(text("SELECT state, skip_reason, attempts FROM run_games")).all()
        assert all(state == ("skipped" if reason else "bet_created") and attempts == 0
                   for state, reason, attempts in states)


@pytest.mark.parametrize("statement", [
    "UPDATE strategies SET type='agent', config=NULL",
    "UPDATE strategies SET type='agent', config='{}'::jsonb",
    "UPDATE strategies SET type='agent', config='{\"profile\":\"unknown\"}'::jsonb",
    "UPDATE strategies SET config='{\"profile\":\"FootballAnalysisExpert\"}'::jsonb",
    "UPDATE bets SET reasoning=' '",
    "UPDATE bets SET reasoning=chr(9)",
    "UPDATE bets SET reasoning=chr(10)",
    "UPDATE bets SET reasoning=' padded '",
    "UPDATE runs SET execution_status='unknown'",
    "UPDATE runs SET execution_status='running'",
    "UPDATE runs SET execution_status='queued'",
    "UPDATE runs SET execution_generation=-1",
    "UPDATE runs SET execution_owner_token=gen_random_uuid()",
    "UPDATE run_games SET attempts=3",
    "UPDATE run_games SET state='unknown'",
    "UPDATE run_games SET state='skipped', skip_reason=NULL",
    "UPDATE run_games SET state='predicted', skip_reason=NULL, attempts=1",
    "UPDATE run_games SET prediction_input='[]'::jsonb",
    "UPDATE run_games SET validated_prediction='[]'::jsonb",
])
def test_database_rejects_invalid_contracts(api, statement):
    client, engine, games = api
    assert post(client, body(games)).status_code == 200
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            with connection.begin_nested():
                connection.execute(text(statement))


def test_database_rejects_overlong_reasoning(api):
    client, engine, games = api
    assert post(client, body(games)).status_code == 200
    with engine.begin() as connection:
        with pytest.raises(DataError) as rejected:
            with connection.begin_nested():
                connection.execute(text("UPDATE bets SET reasoning=repeat('x',1001)"))
        # VARCHAR(1000) rejects the value before CHECK constraints execute.
        assert rejected.value.orig.sqlstate == "22001"
        assert connection.scalar(text("SELECT count(*) FROM bets WHERE reasoning IS NOT NULL")) == 0
        connection.execute(text("UPDATE bets SET reasoning=repeat('x',1000)"))
        assert connection.scalar(text("SELECT min(length(reasoning)) FROM bets")) == 1000


@pytest.mark.parametrize("statement", [
    "UPDATE strategies SET type='agent', config='{\"profile\":\"FootballAnalysisExpert\"}'::jsonb",
    "UPDATE bets SET reasoning='Evidence supports covering the saved spread.'",
    "UPDATE runs SET execution_status='queued', execution_started_at=NULL, execution_finished_at=NULL",
    "UPDATE run_games SET attempts=1",
    "UPDATE run_games SET state='skipped', skip_reason='research_failed'",
])
def test_downgrade_refuses_incompatible_data(api, migrated_database, statement):
    client, engine, games = api
    _, config = migrated_database
    assert post(client, body(games)).status_code == 200
    legacy_execution_fixture(engine)
    with engine.begin() as connection:
        connection.execute(text(statement))
    with pytest.raises(DBAPIError, match="incompatible Agent execution data"):
        command.downgrade(config, "0005")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
    command.check(config)
