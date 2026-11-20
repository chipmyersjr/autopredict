"""Agent configuration, concise reasoning and durable execution on existing tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

RUN_CHECKS = {
    "execution_status": "execution_status IN ('queued', 'running', 'completed', 'failed')",
    "execution_generation": "execution_generation >= 0",
    "execution_owner": "(execution_status = 'running' AND execution_owner_token IS NOT NULL AND execution_lease_expires_at IS NOT NULL AND execution_started_at IS NOT NULL AND execution_generation > 0) OR (execution_status <> 'running' AND execution_owner_token IS NULL AND execution_lease_expires_at IS NULL)",
    "execution_terminal": "(execution_status IN ('queued', 'running') AND execution_finished_at IS NULL AND execution_message IS NULL AND status = 'open') OR (execution_status IN ('completed', 'failed') AND execution_finished_at IS NOT NULL)",
    "execution_queued": "execution_status <> 'queued' OR execution_started_at IS NULL",
    "execution_failed": "execution_status <> 'failed' OR (status = 'open' AND final_bankroll IS NULL AND total_profit IS NULL AND roi IS NULL AND end_time IS NULL)",
    "execution_times": "execution_finished_at IS NULL OR execution_started_at IS NULL OR execution_finished_at >= execution_started_at",
}
GAME_CHECKS = {
    "state": "state IN ('queued', 'analysing', 'retrying', 'predicted', 'bet_created', 'skipped')",
    "attempts": "attempts BETWEEN 0 AND 2",
    "state_skip": "(state = 'skipped' AND skip_reason IS NOT NULL) OR (state <> 'skipped' AND skip_reason IS NULL)",
    "state_attempts": "state NOT IN ('analysing', 'retrying', 'predicted') OR attempts > 0",
    "retry": "state <> 'retrying' OR attempts = 1",
    "input": "prediction_input IS NULL OR jsonb_typeof(prediction_input) = 'object'",
    "prediction": "validated_prediction IS NULL OR jsonb_typeof(validated_prediction) = 'object'",
    "predicted": "state <> 'predicted' OR (prediction_input IS NOT NULL AND validated_prediction IS NOT NULL)",
}
LEGACY_SKIP = "skip_reason IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable')"


def upgrade():
    op.drop_constraint("ck_strategies_type", "strategies", type_="check")
    op.drop_constraint("ck_strategies_config", "strategies", type_="check")
    op.create_check_constraint("ck_strategies_type", "strategies", "type IN ('random', 'agent')")
    op.create_check_constraint("ck_strategies_config", "strategies", "(type = 'random' AND (config IS NULL OR config = '{}'::jsonb)) OR (type = 'agent' AND config IS NOT NULL AND config = '{\"profile\":\"FootballAnalysisExpert\"}'::jsonb)")
    op.add_column("bets", sa.Column("reasoning", sa.String(1000), nullable=True))
    op.create_check_constraint("ck_bets_reasoning", "bets", "reasoning IS NULL OR (length(reasoning) BETWEEN 1 AND 1000 AND reasoning !~ '^[[:space:]]|[[:space:]]$')")
    for column in (
        sa.Column("execution_status", sa.String(20), nullable=False, server_default="completed"),
        sa.Column("execution_started_at", sa.DateTime(timezone=True)),
        sa.Column("execution_finished_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("execution_message", sa.String(255)),
        sa.Column("execution_owner_token", UUID()),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("execution_lease_expires_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("runs", column)
    op.execute("UPDATE runs SET execution_started_at = start_time, execution_finished_at = COALESCE(end_time, start_time)")
    for suffix, condition in RUN_CHECKS.items():
        op.create_check_constraint("ck_runs_" + suffix, "runs", condition)
    for column in (
        sa.Column("state", sa.String(20), nullable=False, server_default="bet_created"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prediction_input", JSONB(none_as_null=True)),
        sa.Column("validated_prediction", JSONB(none_as_null=True)),
    ):
        op.add_column("run_games", column)
    op.execute("UPDATE run_games SET state = 'skipped' WHERE skip_reason IS NOT NULL")
    op.drop_constraint("ck_run_games_skip", "run_games", type_="check")
    op.create_check_constraint("ck_run_games_skip", "run_games", "skip_reason IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable', 'agent_unavailable', 'research_failed', 'invalid_agent_decision', 'quote_changed')")
    for suffix, condition in GAME_CHECKS.items():
        op.create_check_constraint("ck_run_games_" + suffix, "run_games", condition)


def downgrade():
    # Fail before any DDL: old code cannot safely represent these records.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM strategies WHERE type = 'agent')
        OR EXISTS (SELECT 1 FROM bets WHERE reasoning IS NOT NULL)
        OR EXISTS (SELECT 1 FROM runs WHERE execution_status <> 'completed'
                   OR execution_generation <> 0 OR execution_message IS NOT NULL)
        OR EXISTS (SELECT 1 FROM run_games WHERE attempts <> 0
                   OR prediction_input IS NOT NULL OR validated_prediction IS NOT NULL
                   OR state NOT IN ('bet_created', 'skipped')
                   OR skip_reason NOT IN ('game_not_scheduled', 'kickoff_reached', 'spread_unavailable'))
        THEN RAISE EXCEPTION 'Cannot downgrade: incompatible Agent execution data exists';
        END IF;
    END $$""")
    for suffix in GAME_CHECKS:
        op.drop_constraint("ck_run_games_" + suffix, "run_games", type_="check")
    op.drop_constraint("ck_run_games_skip", "run_games", type_="check")
    op.create_check_constraint("ck_run_games_skip", "run_games", LEGACY_SKIP)
    for column in ("validated_prediction", "prediction_input", "attempts", "state"):
        op.drop_column("run_games", column)
    for suffix in RUN_CHECKS:
        op.drop_constraint("ck_runs_" + suffix, "runs", type_="check")
    for column in ("execution_lease_expires_at", "execution_generation", "execution_owner_token",
                   "execution_message", "execution_finished_at", "execution_started_at", "execution_status"):
        op.drop_column("runs", column)
    op.drop_constraint("ck_bets_reasoning", "bets", type_="check")
    op.drop_column("bets", "reasoning")
    op.drop_constraint("ck_strategies_config", "strategies", type_="check")
    op.drop_constraint("ck_strategies_type", "strategies", type_="check")
    op.create_check_constraint("ck_strategies_type", "strategies", "type = 'random'")
    op.create_check_constraint("ck_strategies_config", "strategies", "config IS NULL OR config = '{}'::jsonb")
